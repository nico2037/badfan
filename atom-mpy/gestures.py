# Entprellung + Gestenerkennung (kurz / lang / doppelt) als reine Zustandsmaschine.
# Keine Hardware-Imports: laeuft auf dem Atom und unter CPython (Host-Tests).

DEBOUNCE_MS = 30
LONG_MS = 1000  # so lange halten = "long" (feuert schon waehrend des Haltens)
DOUBLE_MS = 350  # max. Pause zwischen zwei Klicks fuer "double"

SHORT = "short"
LONG = "long"
DOUBLE = "double"


class Gestures:
    def __init__(self):
        self.raw = False
        self.raw_since = 0
        self.stable = False
        self.press_at = None
        self.long_fired = False
        self.pending_click_at = None  # Zeit des ersten Loslassens, wartet auf 2. Klick

    def update(self, pressed, now):
        """Mit aktuellem Tastenpegel (True = gedrueckt) und Zeit in ms aufrufen.
        Gibt eine Liste erkannter Gesten zurueck (meist leer)."""
        out = []
        if pressed != self.raw:
            self.raw = pressed
            self.raw_since = now

        if self.raw != self.stable and now - self.raw_since >= DEBOUNCE_MS:
            self.stable = self.raw
            if self.stable:  # gedrueckt
                self.press_at = now
                self.long_fired = False
            else:  # losgelassen
                if not self.long_fired:
                    if self.pending_click_at is not None:
                        self.pending_click_at = None
                        out.append(DOUBLE)
                    else:
                        self.pending_click_at = now
                self.press_at = None

        if (
            self.stable
            and self.press_at is not None
            and not self.long_fired
            and now - self.press_at >= LONG_MS
        ):
            self.long_fired = True
            self.pending_click_at = None
            out.append(LONG)

        if (
            self.pending_click_at is not None
            and not self.stable
            and now - self.pending_click_at >= DOUBLE_MS
        ):
            self.pending_click_at = None
            out.append(SHORT)

        return out
