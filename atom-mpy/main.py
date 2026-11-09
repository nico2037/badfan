# Pulsar-Fernbedienung auf dem M5Stack Atom Matrix (MicroPython).
# Taste GPIO39 (aktiv low), 5x5 WS2812 an GPIO27.

import asyncio
import json
import os
import time

import neopixel
from machine import Pin

import display
import gestures
import logic
import pulsar

BRIGHTNESS = 20  # 0..255, global begrenzt
STATE_FILE = "state.json"

np = neopixel.NeoPixel(Pin(27), 25)
btn = Pin(39, Pin.IN)  # externer Pull-up auf dem Atom


class Clock:
    """Monotone ms ohne ticks_ms-Ueberlauf (Python-int waechst beliebig)."""

    def __init__(self):
        self.last = time.ticks_ms()
        self.t = 0

    def now(self):
        cur = time.ticks_ms()
        self.t += time.ticks_diff(cur, self.last)
        self.last = cur
        return self.t


def load_state():
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


_saved = None


def save_state(c):
    global _saved
    st = c.persisted()
    if st == _saved:
        return
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(st, f)
    os.rename(tmp, STATE_FILE)
    _saved = st


def show(px):
    for i, c in enumerate(px):
        np[i] = display.scale(c, BRIGHTNESS)
    np.write()


clock = Clock()
ctl = logic.Controller(clock.now(), load_state())
_saved = ctl.persisted()


def start(job):
    save_state(ctl)  # Bademodus-Flag liegt im Flash, bevor geschrieben wird
    print("job:", job["kind"])
    asyncio.create_task(run_job(job))


async def run_job(job):
    try:
        st = await pulsar.run(job["ops"])
        print("ok:", job["kind"], "boost=", st)
        ctl.result(job, True, st, clock.now())
    except pulsar.PulsarError as e:
        print("fehler:", job["kind"], e, "geschrieben?", e.maybe_written)
        ctl.result(job, False, None, clock.now(), e.maybe_written)
    except Exception as e:
        print("fehler:", job["kind"], repr(e))
        ctl.result(job, False, None, clock.now(), True)
    save_state(ctl)


async def button_task():
    g = gestures.Gestures()
    while True:
        now = clock.now()
        for gest in g.update(btn.value() == 0, now):
            print("geste:", gest, "modus:", ctl.mode)
            job = ctl.gesture(gest, now)
            save_state(ctl)
            if job:
                start(job)
        await asyncio.sleep_ms(10)


async def ui_task():
    while True:
        now = clock.now()
        job = ctl.tick(now)
        if job:
            start(job)
        show(display.render(ctl, now))
        await asyncio.sleep_ms(40)


async def main():
    if ctl.restore_pending:
        print("Bademodus-Flag gesetzt -> Feuchtesensor wird wieder eingeschaltet")
    await asyncio.gather(button_task(), ui_task())


asyncio.run(main())
