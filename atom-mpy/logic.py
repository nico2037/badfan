# Zustandsmaschine der Fernbedienung. Rein (keine Hardware, keine BLE), Zeit in ms.
#
# Ablauf: gesture() / tick() liefern einen Job (Liste von Pulsar-Operationen) oder None.
# main.py fuehrt den Job per BLE aus und meldet das Ergebnis mit result() zurueck.

IDLE = "idle"
BOOST = "boost"
BATH = "bath"

# --- Einstellungen ---------------------------------------------------------
DURATIONS_MIN = (5, 15, 30)  # Auswahl per Doppelklick im Idle
DEFAULT_DUR_IDX = 1  # 15 Min
EXTEND_S = 15 * 60  # Doppelklick waehrend Boost
BATH_MIN = 60  # Sicherheits-Timer Bademodus
FEEDBACK_MS = 500  # Haken / Kreuz
SELECT_SHOW_MS = 1500  # Anzeige der gewaehlten Boost-Dauer
RETRY_MIN_MS = 5_000  # Backoff fuers Wiedereinschalten des Feuchtesensors
RETRY_MAX_MS = 300_000

# --- Gesten-Tabelle: (Modus, Geste) -> Aktion. Hier umbelegen. ---------------
ACTIONS = {
    (IDLE, "short"): "boost_start",
    (IDLE, "long"): "bath_start",
    (IDLE, "double"): "select_duration",
    (BOOST, "short"): "boost_stop",
    (BOOST, "long"): "boost_stop_bath_start",
    (BOOST, "double"): "boost_extend",
    (BATH, "short"): "bath_end",
    (BATH, "long"): "bath_end",
    (BATH, "double"): None,
}

# Jobs, die den Feuchtesensor ausschalten koennten
_HUMIDITY_OFF_JOBS = ("bath_start", "boost_stop_bath_start")


class Controller:
    def __init__(self, now, persisted=None):
        p = persisted or {}
        self.mode = IDLE
        self.link = "unknown"  # unknown / ok / error
        self.busy = False
        self.dur_idx = p.get("dur_idx", DEFAULT_DUR_IDX)
        if not 0 <= self.dur_idx < len(DURATIONS_MIN):
            self.dur_idx = DEFAULT_DUR_IDX
        self.boost_end = 0
        self.boost_total = 1
        self.bath_start = 0
        self.bath_end = 0
        # Fail-safe: Flag gesetzt = Feuchtesensor koennte aus sein -> wieder einschalten
        self.bath_flag = bool(p.get("bath", False))
        self.restore_pending = self.bath_flag
        self.retry_at = now
        self.retry_delay = RETRY_MIN_MS
        self.feedback = None  # ("check"|"cross", bis)
        self.select_until = 0

    # --- Persistenz -------------------------------------------------------
    def persisted(self):
        return {"bath": self.bath_flag, "dur_idx": self.dur_idx}

    def boost_seconds(self):
        return DURATIONS_MIN[self.dur_idx] * 60

    # --- Eingaben ---------------------------------------------------------
    def gesture(self, g, now):
        if self.busy:
            return None
        action = ACTIONS.get((self.mode, g))
        if action is None:
            return None
        if action == "select_duration":
            self.dur_idx = (self.dur_idx + 1) % len(DURATIONS_MIN)
            self.select_until = now + SELECT_SHOW_MS
            return None
        if action == "bath_end":
            self.restore_pending = True
            self.retry_at = now
            self.retry_delay = RETRY_MIN_MS
            return self._start_restore()
        if action in _HUMIDITY_OFF_JOBS:
            # Flag VOR dem Schreiben setzen (main.py persistiert es vor dem BLE-Job)
            self.bath_flag = True
        return self._start(action)

    def tick(self, now):
        """Regelmaessig aufrufen. Liefert ggf. einen Job (Wiedereinschalten)."""
        if self.feedback and now >= self.feedback[1]:
            self.feedback = None
        if self.mode == BOOST and now >= self.boost_end:
            self.mode = IDLE
        if self.mode == BATH and now >= self.bath_end and not self.restore_pending:
            self.restore_pending = True
            self.retry_at = now
            self.retry_delay = RETRY_MIN_MS
        if self.restore_pending and not self.busy and now >= self.retry_at:
            return self._start_restore()
        return None

    # --- Jobs -------------------------------------------------------------
    def _start_restore(self):
        if self.busy:
            return None
        return self._start("restore")

    def _start(self, kind):
        self.busy = True
        return {"kind": kind, "ops": self._ops(kind)}

    def _ops(self, kind):
        if kind == "boost_start":
            return [("boost", self.boost_seconds())]
        if kind == "boost_stop":
            return [("boost", 0)]
        if kind == "boost_extend":
            return [("boost_extend", EXTEND_S)]
        if kind == "bath_start":
            return [("humidity", False)]
        if kind == "boost_stop_bath_start":
            return [("boost", 0), ("humidity", False)]
        if kind == "restore":
            return [("humidity", True)]
        raise ValueError(kind)

    def result(self, job, ok, boost_state, now, maybe_written=False):
        """boost_state = (aktiv, restsekunden) wie vom Pulsar gelesen, oder None."""
        self.busy = False
        kind = job["kind"]
        if not ok:
            self.link = "error"
            self.feedback = ("cross", now + FEEDBACK_MS)
            if kind == "restore":
                self.retry_at = now + self.retry_delay
                self.retry_delay = min(self.retry_delay * 2, RETRY_MAX_MS)
            elif kind in _HUMIDITY_OFF_JOBS:
                if maybe_written:
                    # Sensor evtl. schon aus -> sicherheitshalber wieder einschalten
                    self.restore_pending = True
                    self.retry_at = now + RETRY_MIN_MS
                    self.retry_delay = RETRY_MIN_MS
                else:
                    self.bath_flag = False  # nichts geschrieben, kein Zustand geaendert
            return

        self.link = "ok"
        self.feedback = ("check", now + FEEDBACK_MS)

        if kind in ("boost_start", "boost_extend"):
            if boost_state and boost_state[0]:
                self.mode = BOOST
                self.boost_total = max(boost_state[1], 1) * 1000
                self.boost_end = now + boost_state[1] * 1000
        elif kind == "boost_stop":
            self.mode = IDLE
        elif kind in _HUMIDITY_OFF_JOBS:
            self.mode = BATH
            self.bath_start = now
            self.bath_end = now + BATH_MIN * 60_000
        elif kind == "restore":
            self.bath_flag = False
            self.restore_pending = False
            self.retry_delay = RETRY_MIN_MS
            if self.mode == BATH:
                self.mode = IDLE

        # Abgleich mit dem Pulsar (z. B. Boost per App beendet)
        if self.mode == BOOST and boost_state is not None and not boost_state[0]:
            self.mode = IDLE
