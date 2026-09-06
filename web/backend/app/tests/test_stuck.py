import unittest, sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from entities.robot import Robot, robots
from simulation import robot_controller as rc


class TestStuckDetection(unittest.TestCase):
    def setUp(self):
        from core.state import get_state
        get_state().reset()
        self.orig_stuck_ticks = rc.STUCK_TICKS
        rc.STUCK_TICKS = 5  # speed up: alert after 5 ticks instead of 600
        self.r = Robot(99, "metal", (1.0, 0.0, 0.0, 1.0), (10, 5))
        self.r.agent_ready = True
        robots.append(self.r)

    def tearDown(self):
        robots.remove(self.r)
        rc.STUCK_TICKS = self.orig_stuck_ticks

    def make_stationary(self):
        self.r.pos = (5, 5)
        self.r.draw_pos = [5.0, 5.0]
        self.r._stuck_sample_pos = [5.0, 5.0]
        self.r.task = {"type": "putaway", "product": "metal", "qty": 1}
        self.r.executing = True

    def test_alert_raised_after_threshold(self):
        from core.state import get_state
        self.make_stationary()
        for _ in range(6):
            rc.detect_stuck_robots()
        self.assertTrue(self.r.stuck_alert_raised)
        self.assertGreater(self.r.stationary_ticks, 5)
        log = list(get_state().event_log)
        self.assertTrue(any("застрял" in e for e in log))

    def test_no_alert_while_moving(self):
        self.r.pos = (5, 5)
        self.r.task = {"type": "putaway", "product": "metal", "qty": 1}
        step = 0.1
        for i in range(10):
            self.r.draw_pos = [5.0 + step * i, 5.0]
            rc.detect_stuck_robots()
        self.assertFalse(self.r.stuck_alert_raised)

    def test_no_alert_parked_at_home(self):
        self.r.pos = self.r.home
        self.r.draw_pos = [float(self.r.home[0]), float(self.r.home[1])]
        self.r._stuck_sample_pos = list(self.r.draw_pos)
        self.r.task = None
        self.r.executing = True  # active, but standing at base
        for _ in range(6):
            rc.detect_stuck_robots()
        self.assertFalse(self.r.stuck_alert_raised)

    def test_no_alert_while_charging(self):
        self.r.pos = self.r.home
        self.r.draw_pos = [float(self.r.home[0]), float(self.r.home[1])]
        self.r._stuck_sample_pos = list(self.r.draw_pos)
        self.r.phase = "charging"
        for _ in range(6):
            rc.detect_stuck_robots()
        self.assertFalse(self.r.stuck_alert_raised)

    def test_alert_fires_only_once(self):
        from metrics import robot_stuck_events_counter
        before = robot_stuck_events_counter.labels(robot_id="99", name="РТС-99")._value.get()
        self.make_stationary()
        for _ in range(12):
            rc.detect_stuck_robots()
        self.assertTrue(self.r.stuck_alert_raised)
        after = robot_stuck_events_counter.labels(robot_id="99", name="РТС-99")._value.get()
        self.assertEqual(after - before, 1)

    def test_alert_clears_when_robot_moves(self):
        from core.state import get_state
        self.make_stationary()
        for _ in range(6):
            rc.detect_stuck_robots()
        self.assertTrue(self.r.stuck_alert_raised)
        self.r.draw_pos = [6.0, 5.0]
        rc.detect_stuck_robots()
        self.assertFalse(self.r.stuck_alert_raised)
        self.assertEqual(self.r.stationary_ticks, 0)
        log = list(get_state().event_log)
        self.assertTrue(any("алерт снят" in e for e in log))

    def test_stuck_counted_in_metrics_render(self):
        from metrics import render_prometheus
        self.make_stationary()
        for _ in range(6):
            rc.detect_stuck_robots()
        body, _ = render_prometheus()
        self.assertRegex(body, r'magsim_robot_stuck\{[^}]*robot_id="99"[^}]*\}\s+1\.0')


if __name__ == '__main__':
    unittest.main()