# Anzeige: reine Funktionen, die aus dem Controller-Zustand 25 RGB-Pixel machen.
# Index = zeile * 5 + spalte, Zeile 0 oben. Farben volle Skala; Helligkeit begrenzt main.py.

import logic

OFF = (0, 0, 0)
GREEN = (0, 255, 0)
RED = (255, 0, 0)
BLUE = (0, 0, 255)
ORANGE = (255, 90, 0)
BAR = (90, 140, 255)
DIM_WHITE = (60, 60, 60)

CHECK = [
    [0, 0, 0, 0, 0],
    [0, 0, 0, 0, 1],
    [0, 0, 0, 1, 0],
    [1, 0, 1, 0, 0],
    [0, 1, 0, 0, 0],
]
CROSS = [
    [1, 0, 0, 0, 1],
    [0, 1, 0, 1, 0],
    [0, 0, 1, 0, 0],
    [0, 1, 0, 1, 0],
    [1, 0, 0, 0, 1],
]
DROP = [
    [0, 0, 1, 0, 0],
    [0, 1, 1, 1, 0],
    [0, 1, 1, 1, 0],
    [0, 0, 1, 0, 0],
    [0, 0, 0, 0, 0],
]
CENTER = 12


def bitmap(bm, color):
    return [color if bm[i // 5][i % 5] else OFF for i in range(25)]


def scale(c, f):
    return (c[0] * f // 255, c[1] * f // 255, c[2] * f // 255)


def pulse(now, period=1000):
    """Dreieckswelle 40..255."""
    t = now % period
    half = period // 2
    x = t if t < half else period - t
    return 40 + (215 * x) // half


def ceil_div(a, b):
    return -(-a // b)


def countdown(remaining_ms, total_ms):
    lit = max(0, min(25, ceil_div(max(remaining_ms, 0) * 25, max(total_ms, 1))))
    return [ORANGE if i < lit else OFF for i in range(25)]


def bath(now, c):
    color = RED if (c.restore_pending and c.link == "error") else BLUE
    px = bitmap(DROP, color)
    total = max(c.bath_end - c.bath_start, 1)
    left = max(c.bath_end - now, 0)
    lit = max(0, min(5, ceil_div(left * 5, total)))
    for col in range(5):
        px[20 + col] = BAR if col < lit else OFF
    return px


def selection(dur_idx):
    rows = (1, 3, 5)[dur_idx] if dur_idx < 3 else 5
    return [ORANGE if i // 5 >= 5 - rows else OFF for i in range(25)]


def render(c, now):
    if c.feedback and now < c.feedback[1]:
        return bitmap(CHECK, GREEN) if c.feedback[0] == "check" else bitmap(CROSS, RED)
    if now < c.select_until:
        return selection(c.dur_idx)
    if c.mode == logic.BOOST:
        px = countdown(c.boost_end - now, c.boost_total)
    elif c.mode == logic.BATH:
        px = bath(now, c)
    else:
        px = [OFF] * 25
        if c.restore_pending and c.link == "error":
            px = bitmap(DROP, RED)  # Sensor evtl. noch aus, Wiedereinschalten scheitert
        else:
            px[CENTER] = {"ok": GREEN, "error": RED}.get(c.link, DIM_WHITE)
    if c.busy:
        px[CENTER] = scale(BLUE, pulse(now))
    return px
