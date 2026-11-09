import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import display  # noqa: E402
import gestures as G  # noqa: E402
import logic as L  # noqa: E402


def feed(g, timeline):
    """timeline: Liste (ms, gedrueckt). Simuliert 1-ms-Abtastung bis zum letzten Zeitpunkt+1000."""
    out = []
    events = dict(timeline)
    level = False
    end = max(events) + 1000
    for t in range(0, end):
        if t in events:
            level = events[t]
        for x in g.update(level, t):
            out.append((t, x))
    return [x for _, x in out]


class GestureTests(unittest.TestCase):
    def test_short(self):
        self.assertEqual(feed(G.Gestures(), [(100, True), (250, False)]), ["short"])

    def test_bounce_is_ignored(self):
        tl = [(100, True), (105, False), (108, True), (300, False), (303, True), (306, False)]
        self.assertEqual(feed(G.Gestures(), tl), ["short"])

    def test_long_fires_while_held_and_only_once(self):
        self.assertEqual(feed(G.Gestures(), [(100, True), (3000, False)]), ["long"])

    def test_double(self):
        tl = [(100, True), (200, False), (350, True), (450, False)]
        self.assertEqual(feed(G.Gestures(), tl), ["double"])

    def test_two_slow_clicks_are_two_shorts(self):
        tl = [(100, True), (200, False), (1000, True), (1100, False)]
        self.assertEqual(feed(G.Gestures(), tl), ["short", "short"])

    def test_click_then_long(self):
        tl = [(100, True), (200, False), (300, True), (1500, False)]
        self.assertEqual(feed(G.Gestures(), tl), ["long"])


def ok(c, job, now, boost=(False, 0)):
    c.result(job, True, boost, now)


class ControllerTests(unittest.TestCase):
    def test_short_in_idle_starts_selected_boost(self):
        c = L.Controller(0)
        job = c.gesture("short", 0)
        self.assertEqual(job["ops"], [("boost", 900)])
        self.assertTrue(c.busy)
        self.assertIsNone(c.gesture("short", 10))  # waehrend busy ignoriert
        ok(c, job, 1000, (True, 899))
        self.assertEqual(c.mode, L.BOOST)
        self.assertEqual(c.link, "ok")
        self.assertEqual(c.boost_end, 1000 + 899_000)

    def test_boost_runs_out_locally(self):
        c = L.Controller(0)
        ok(c, c.gesture("short", 0), 0, (True, 10))
        c.tick(10_001)
        self.assertEqual(c.mode, L.IDLE)

    def test_short_in_boost_stops(self):
        c = L.Controller(0)
        ok(c, c.gesture("short", 0), 0, (True, 900))
        job = c.gesture("short", 5000)
        self.assertEqual(job["ops"], [("boost", 0)])
        ok(c, job, 6000)
        self.assertEqual(c.mode, L.IDLE)

    def test_double_in_idle_cycles_duration(self):
        c = L.Controller(0)
        self.assertIsNone(c.gesture("double", 0))
        self.assertEqual(c.dur_idx, 2)
        self.assertEqual(c.gesture("short", 2000)["ops"], [("boost", 1800)])
        self.assertEqual(c.persisted()["dur_idx"], 2)

    def test_double_in_boost_extends(self):
        c = L.Controller(0)
        ok(c, c.gesture("short", 0), 0, (True, 900))
        self.assertEqual(c.gesture("double", 100)["ops"], [("boost_extend", 900)])

    def test_failed_connect_changes_nothing(self):
        c = L.Controller(0)
        job = c.gesture("short", 0)
        c.result(job, False, None, 100)
        self.assertEqual(c.mode, L.IDLE)
        self.assertEqual(c.link, "error")
        self.assertEqual(c.feedback[0], "cross")

    def test_bath_sets_flag_before_job_and_restores_after_timer(self):
        c = L.Controller(0)
        job = c.gesture("long", 0)
        self.assertTrue(c.persisted()["bath"])  # vor dem BLE-Job gesetzt
        self.assertEqual(job["ops"], [("humidity", False)])
        ok(c, job, 0)
        self.assertEqual(c.mode, L.BATH)
        self.assertIsNone(c.tick(L.BATH_MIN * 60_000 - 1))
        job = c.tick(L.BATH_MIN * 60_000)
        self.assertEqual(job["ops"], [("humidity", True)])
        ok(c, job, L.BATH_MIN * 60_000 + 100)
        self.assertEqual(c.mode, L.IDLE)
        self.assertFalse(c.persisted()["bath"])

    def test_long_in_boost_stops_boost_and_starts_bath(self):
        c = L.Controller(0)
        ok(c, c.gesture("short", 0), 0, (True, 900))
        job = c.gesture("long", 100)
        self.assertEqual(job["ops"], [("boost", 0), ("humidity", False)])

    def test_bath_start_fail_before_write_clears_flag(self):
        c = L.Controller(0)
        c.result(c.gesture("long", 0), False, None, 10, maybe_written=False)
        self.assertFalse(c.persisted()["bath"])
        self.assertFalse(c.restore_pending)

    def test_bath_start_fail_after_write_triggers_restore(self):
        c = L.Controller(0)
        c.result(c.gesture("long", 0), False, None, 10, maybe_written=True)
        self.assertTrue(c.persisted()["bath"])
        self.assertTrue(c.restore_pending)
        self.assertIsNone(c.tick(10 + L.RETRY_MIN_MS - 1))
        self.assertEqual(c.tick(10 + L.RETRY_MIN_MS)["kind"], "restore")

    def test_boot_with_flag_restores_with_backoff(self):
        c = L.Controller(0, {"bath": True})
        job = c.tick(0)
        self.assertEqual(job["kind"], "restore")
        c.result(job, False, None, 0)
        self.assertIsNone(c.tick(L.RETRY_MIN_MS - 1))
        job = c.tick(L.RETRY_MIN_MS)
        c.result(job, False, None, L.RETRY_MIN_MS)
        # Backoff verdoppelt sich
        self.assertIsNone(c.tick(L.RETRY_MIN_MS + 2 * L.RETRY_MIN_MS - 1))
        job = c.tick(L.RETRY_MIN_MS + 2 * L.RETRY_MIN_MS)
        self.assertIsNotNone(job)
        ok(c, job, 20_000)
        self.assertFalse(c.persisted()["bath"])

    def test_backoff_is_capped(self):
        c = L.Controller(0, {"bath": True})
        now = 0
        for _ in range(20):
            job = c.tick(now)
            self.assertIsNotNone(job)
            c.result(job, False, None, now)
            now = c.retry_at
        self.assertEqual(c.retry_delay, L.RETRY_MAX_MS)

    def test_app_stopped_boost_syncs_to_idle(self):
        c = L.Controller(0)
        ok(c, c.gesture("short", 0), 0, (True, 900))
        c.mode = L.BOOST
        job = c.gesture("double", 100)
        ok(c, job, 200, (False, 0))
        self.assertEqual(c.mode, L.IDLE)

    def test_table_covers_all_modes_and_gestures(self):
        for m in (L.IDLE, L.BOOST, L.BATH):
            for g in ("short", "long", "double"):
                self.assertIn((m, g), L.ACTIONS)


class DisplayTests(unittest.TestCase):
    def test_idle_center_pixel_colors(self):
        c = L.Controller(0)
        c.link = "ok"
        px = display.render(c, 0)
        self.assertEqual(px[12], display.GREEN)
        self.assertEqual(sum(1 for p in px if p != display.OFF), 1)
        c.link = "error"
        self.assertEqual(display.render(c, 0)[12], display.RED)

    def test_countdown(self):
        self.assertEqual(display.countdown(900_000, 900_000).count(display.ORANGE), 25)
        self.assertEqual(display.countdown(36_000, 900_000).count(display.ORANGE), 1)
        self.assertEqual(display.countdown(36_001, 900_000).count(display.ORANGE), 2)
        self.assertEqual(display.countdown(0, 900_000).count(display.ORANGE), 0)

    def test_feedback_overrides(self):
        c = L.Controller(0)
        c.feedback = ("check", 500)
        self.assertEqual(display.render(c, 100), display.bitmap(display.CHECK, display.GREEN))
        self.assertNotEqual(display.render(c, 500), display.bitmap(display.CHECK, display.GREEN))

    def test_bath_bar_shrinks(self):
        c = L.Controller(0)
        c.mode = L.BATH
        c.bath_start, c.bath_end = 0, 1000
        full = display.render(c, 0)[20:25].count(display.BAR)
        half = display.render(c, 500)[20:25].count(display.BAR)
        self.assertEqual((full, half), (5, 3))

    def test_busy_pulses_center(self):
        c = L.Controller(0)
        c.busy = True
        self.assertNotEqual(display.render(c, 0)[12], display.render(c, 500)[12])

    def test_bitmaps_are_5x5(self):
        for bm in (display.CHECK, display.CROSS, display.DROP):
            self.assertEqual(len(bm), 5)
            self.assertTrue(all(len(r) == 5 for r in bm))

class SyncTests(unittest.TestCase):
    def test_boot_sync_reads_running_boost(self):
        c = L.Controller(0)
        job = c.tick(0)
        self.assertEqual((job["kind"], job["ops"]), ("sync", []))
        c.result(job, True, (True, 300), 1000)
        self.assertEqual(c.mode, L.BOOST)
        self.assertEqual(c.boost_end, 1000 + 300_000)
        self.assertIsNone(c.feedback)  # kein Haken beim stillen Abgleich
        self.assertIsNone(c.tick(2000))

    def test_boot_sync_idle_when_no_boost(self):
        c = L.Controller(0)
        c.result(c.tick(0), True, (False, 0), 10)
        self.assertEqual((c.mode, c.link), (L.IDLE, "ok"))

    def test_boot_sync_gives_up_after_limited_attempts(self):
        c = L.Controller(0)
        now, jobs = 0, 0
        for _ in range(10):
            job = c.tick(now)
            if job:
                jobs += 1
                c.result(job, False, None, now)
                self.assertIsNone(c.feedback)
            now += L.RETRY_MAX_MS
        self.assertEqual(jobs, L.SYNC_ATTEMPTS)
        self.assertEqual(c.link, "error")

    def test_no_separate_sync_when_restore_pending(self):
        c = L.Controller(0, {"bath": True})
        self.assertEqual(c.tick(0)["kind"], "restore")

    def test_button_during_pending_sync_replaces_it(self):
        c = L.Controller(0)
        job = c.gesture("short", 0)
        c.result(job, True, (True, 900), 100)
        self.assertFalse(c.sync_pending)

    def test_boost_started_via_app_is_picked_up(self):
        c = L.Controller(0)
        c.sync_pending = False
        job = c.gesture("long", 0)
        c.result(job, True, (True, 600), 10)  # Bademodus: Boost-Status wird ignoriert
        self.assertEqual(c.mode, L.BATH)


if __name__ == "__main__":
    unittest.main()
