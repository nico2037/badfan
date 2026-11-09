# Auftrag: Pulsar-Fernbedienung auf M5Stack Atom Matrix (Rust, Embassy)

## Ziel

Baue eine Firmware in **Rust (no_std) mit Embassy** für einen **M5Stack Atom Matrix**. Sie steuert einen **inVENTer Pulsar** (Lüfter, PAX-Calima-Familie) per Bluetooth LE. Die Bedienung läuft über den einen Button des Atom. Die Rückmeldung läuft über die 5×5-LED-Matrix.

Es geht um mein eigenes Gerät in meiner Wohnung. Ich will 15-Minuten-Boost per Tastendruck und einen „Bademodus", der den Feuchtesensor zeitlich begrenzt abschaltet.

## Hardware

- **Atom Matrix**: ESP32-PICO-D4 (klassischer ESP32, Xtensa, BLE vorhanden). Das heißt: Xtensa-Toolchain mit `espup`, nicht RISC-V.
- 25 WS2812-LEDs an **GPIO27** (über RMT ansteuern).
- Button (ganze Frontfläche) an **GPIO39**.
- IMU MPU6886 per I2C (**SDA GPIO25, SCL GPIO21**), nur für optionales „Schütteln = Notaus".
- **Prüfe alle Pins gegen die offizielle M5-Doku** (https://docs.m5stack.com/en/core/Atom-Matrix), bevor du sie festschreibst.

## Software-Stack

- `esp-hal` (1.x) mit Embassy-Executor. Hole dir die **aktuell zusammenpassenden Versionen** von `esp-hal`, `esp-rtos` bzw. dem Embassy-Integrations-Crate, `esp-radio`, `trouble-host` und dem RMT-/SmartLED-Treiber aus deren Doku und Beispielen. Pinne exakte Versionen, nimm kein `*`. Diese Crates ändern sich schnell.
- BLE: [`trouble`](https://github.com/embassy-rs/trouble) (Central-Rolle, GATT-Client).
- Flashen mit `espflash`, Logging mit `defmt` oder `esp-println`.
- Toolchain im Repo festhalten (`rust-toolchain.toml`, `.cargo/config.toml`, README mit Setup-Schritten für macOS).

## Das Pulsar-Protokoll (aus der Hersteller-App extrahiert)

Alle Zahlen **little endian**. Das Referenzskript `pulsar.py` (Python mit `bleak`) liegt daneben. Es ist die Quelle der Wahrheit für die Byte-Formate.

### 1. Authentifizierung (PIN im Datenstrom)

Es gibt **kein** BLE-Pairing und kein Bonding. Nach dem Verbinden **muss zuerst die PIN geschrieben werden**, sonst werden Schreibzugriffe abgelehnt.

- Service `e6834e4b-7b3a-48e6-91e4-f1d005f564d3`
- Characteristic `4cad343a-209a-40b7-b911-4d9b3df569b2` (PIN): `uint32` LE, mit Response schreiben.
- Optional: `d1ae6b70-ee12-4f6d-b166-d2063dcaffe1` lesen, 1 Byte (Bestätigung).
- Die PIN ist 8-stellig. **Die PIN gehört nicht ins Repository.** Lege sie als Build-Zeit-Konfiguration ab (z. B. `env!("PULSAR_PIN")` aus einer `.env`, die in `.gitignore` steht).

### 2. Konfigurations-Service `c119e858-0531-4681-9674-5a11f0e53bb4`

| Funktion | Characteristic | Format |
|---|---|---|
| **Boost** | `118c949c-28c8-4139-b0b3-36657fd055a9` | 5 Byte: `u8 aktiv`, `u16 rpm`, `u16 sekunden`. Quick-Boost der App: `1, 2400, 900`. Aus: `0, 0, 0` |
| **Sensorik** | `e782e131-6ce1-4191-a8db-f4304d7610f1` | 4× `u8`: Feuchte an/aus, Feuchte-Empfindlichkeit, Präsenz an/aus, Präsenz-Empfindlichkeit |
| Modus | `90cabcd1-bcda-4167-85d8-16dcd8ab6a6b` | 1× `u8`, nur lesen (Normalmodus „Multi") |
| Status (Service `1a46a853-e5ed-4696-bac0-70e346884a26`) | `25a824ad-3021-4de9-9f2f-60cf8d17bded` | 1× `u8`, 0 = ok, nur lesen |
| Sensordaten (selber Service) | `528b80e8-c47a-4c0a-bdf1-916a7748f412` | 4× `u16` (Feuchte, Temperatur, Licht, Drehzahl) plus ein paar `u8`. **Skalierung unbestätigt.** |

**Nur diese vier schreibenden Zugriffe sind für das Projekt vorgesehen:** PIN schreiben, Boost schreiben, Sensorik schreiben (nur Byte 0, Feuchte an/aus). Alles andere ist tabu. Schreibe **niemals** auf die Characteristics `reset` (`ff5f7c4f-…`), `factorySettingsChanged` oder andere Konfigurations-Characteristics, auch nicht zum „Testen".

**Sensorik schreiben heißt: erst lesen, dann nur Byte 0 ändern, dann alle 4 Bytes zurückschreiben.** Die Empfindlichkeitswerte bleiben unverändert.

### 3. Verbindungsmodell

Der Pulsar akzeptiert **nur eine BLE-Verbindung gleichzeitig**. Die Hersteller-App auf dem Handy soll weiter funktionieren.

- **On-Demand-Verbindung:** Tastendruck → scannen/verbinden (Adresse oder Name im Config) → PIN schreiben → Befehl → trennen.
- Reconnect mit Backoff, aber begrenzt (kein Dauer-Scan).
- Wenn die Verbindung scheitert (z. B. weil die App verbunden ist): rotes Kreuz zeigen, kein Zustand ändern.

## Bedienung (UX)

Eine Taste, drei Gesten. Lege die Zuordnung in **einer Konstanten-Tabelle** ab, damit ich sie leicht tauschen kann.

| Geste | Idle | Während Boost | Im Bademodus |
|---|---|---|---|
| Kurz drücken | Boost 15 Min starten | Boost stoppen | Bademodus beenden |
| Lang drücken (~1 s) | Bademodus an | Boost beenden, Bademodus an | Bademodus beenden |
| Doppelklick | Boost-Dauer wählen (5 / 15 / 30 Min, Auswahl merken) | Boost um 15 Min verlängern | – |

**Bademodus** = Feuchtesensor aus (Sensorik Byte 0 = 0) plus **Sicherheits-Timer 60 Min** (konfigurierbar). Danach wird der Sensor automatisch wieder eingeschaltet. Das ist sicherheitsrelevant, weil ein dauerhaft ausgeschalteter Feuchtesensor im Bad Schimmel begünstigt.

### Anzeige (5×5-Matrix, gedimmt, niedrige Helligkeit)

- **Idle:** ein Pixel in der Mitte. Grün = zuletzt erreichbar, Blau pulsierend = verbindet, Rot = Fehler.
- **Boost:** alle 25 Pixel orange, laufen als Countdown nach Zeit herunter (bei 15 Min ≈ 36 s pro Pixel).
- **Bademodus:** blauer Tropfen, in der untersten Zeile ein Fortschrittsbalken für den Sicherheits-Timer.
- **Rückmeldung:** nach jeder Aktion ca. 500 ms grüner Haken oder rotes Kreuz.
- Alle Muster als `[[u8; 5]; 5]`-Bitmaps. Helligkeit global begrenzen.

Optional später: Schütteln (IMU) = Notaus → Boost aus und Feuchtesensor an.

## Sicherheits- und Robustheitsregeln

1. **Fail-safe für den Feuchtesensor:** Der Bademodus-Status (aktiv ja/nein) wird in Flash/NVS persistiert. Beim Booten gilt: Ist das Flag gesetzt, verbinde, schalte den Feuchtesensor wieder an, lösche das Flag. Ist das Verbinden nicht möglich, wiederhole mit Backoff und zeige Rot.
2. Der Timer des Bademodus läuft im Atom. Der Pulsar kennt den Modus nicht.
3. Die Boost-Restzeit im Pulsar läuft selbstständig weiter (die Zeit ist Teil der Boost-Characteristic). Der Atom muss ihn nicht mit Nachrichten füttern.
4. Keine Schreibzugriffe mit unbekannten Werten. Wenn das Lesen der Sensorik weniger als 4 Byte liefert, abbrechen und rot anzeigen.
5. Kein Logging der PIN.

## Vorgehen in Stufen (nach jeder Stufe committen)

1. **Projekt-Gerüst + LEDs:** Toolchain, Embassy-Executor, RMT-Ansteuerung, Bitmaps und Animationen (Idle, Countdown, Tropfen, Haken, Kreuz). Display-Logik als reine Funktionen, mit Host-Tests (`cargo test` auf dem Rechner).
2. **Button:** Entprellung und Gestenerkennung (kurz, lang, Doppelklick) als Zustandsmaschine mit Embassy-Timern. Host-Tests für die Zustandsmaschine.
3. **BLE-Scan:** Pulsar finden (Name/Adresse), nur loggen.
4. **BLE-Verbindung + PIN + Lesen:** `status` auf dem Atom (Boost-Zustand, Sensorik). **Erst weiter, wenn die gelesenen Werte plausibel sind** und mit dem Python-Referenzskript übereinstimmen.
5. **Schreiben:** Boost an/aus, Bademodus (Sensorik Byte 0) mit Timer und Persistenz (Regel 1).
6. Feinschliff: Helligkeit, Fehlerfälle, README mit Setup, Flashen und Konfiguration.

## Offene Punkte (nicht raten, sondern prüfen oder fragen)

- Pin-Belegung des Atom Matrix (siehe oben).
- Skalierung der Sensordaten (Temperatur etc.) und Zahlenwerte der Empfindlichkeitsstufen sind **unbestätigt**. Zeige sie nur an, wenn du sie gegen das Python-Referenzskript prüfen konntest.
- Wie wird der Pulsar gefunden: Advertising-Name oder feste Adresse? Beim ersten Scan loggen und mit mir abstimmen.
- Das Protokoll wurde aus der Hersteller-App abgeleitet und ist **auf echter Hardware noch nicht getestet**. Melde Abweichungen klar, statt Annahmen still zu korrigieren.

## Fertig, wenn

- Kurzer Tastendruck startet 15 Min Boost, ein zweiter Druck stoppt ihn (am Pulsar sichtbar), und die Matrix zeigt Fortschritt und Rückmeldung.
- Langer Druck schaltet den Feuchtesensor aus, die Matrix zeigt den Tropfen, nach Ablauf (oder erneutem Druck) ist der Sensor wieder an.
- Strom trennen im Bademodus und wieder einschalten: Der Sensor ist danach wieder an.
- Die Hersteller-App auf dem Handy kann sich nach einer Aktion wieder verbinden.
- README beschreibt Toolchain-Setup, Flashen und das Setzen der PIN.
