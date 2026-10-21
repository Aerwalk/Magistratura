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


class TestReleaseRobotShelfReservations(unittest.TestCase):
    def setUp(self):
        from core.state import get_state
        get_state().reset()
        self.r = Robot(99, "metal", (1.0, 0.0, 0.0, 1.0), (10, 5))
        robots.append(self.r)

    def tearDown(self):
        robots.remove(self.r)

    def test_release_clears_reserved_pick_shelf(self):
        from core.state import get_state
        s = get_state()
        shelf = (5, 5)
        self.r.task = {"type": "retrieve", "product": "metal", "qty": 2, "shelf": shelf}
        self.r.target_shelf = shelf
        s.reserved_pick_shelves.add(shelf)
        rc.release_robot_shelf_reservations(self.r)
        self.assertNotIn(shelf, s.reserved_pick_shelves)

    def test_release_clears_reserved_put_shelf(self):
        from core.state import get_state
        s = get_state()
        shelf = (5, 5)
        self.r.task = {"type": "putaway", "product": "metal", "qty": 1}
        self.r.target_shelf = shelf
        s.reserved_put_shelves.add(shelf)
        rc.release_robot_shelf_reservations(self.r)
        self.assertNotIn(shelf, s.reserved_put_shelves)

    def test_release_clears_both_sets_for_target(self):
        from core.state import get_state
        s = get_state()
        shelf = (5, 5)
        self.r.task = {"type": "putaway", "product": "metal", "qty": 1}
        self.r.target_shelf = shelf
        s.reserved_put_shelves.add(shelf)
        s.reserved_pick_shelves.add(shelf)
        rc.release_robot_shelf_reservations(self.r)
        self.assertNotIn(shelf, s.reserved_put_shelves)
        self.assertNotIn(shelf, s.reserved_pick_shelves)

    def test_release_clears_task_shelf_without_target(self):
        from core.state import get_state
        s = get_state()
        shelf = (5, 5)
        self.r.task = {"type": "retrieve", "product": "metal", "qty": 2, "shelf": shelf}
        self.r.target_shelf = None
        s.reserved_pick_shelves.add(shelf)
        rc.release_robot_shelf_reservations(self.r)
        self.assertNotIn(shelf, s.reserved_pick_shelves)


class TestReconcileShelfReservations(unittest.TestCase):
    def setUp(self):
        from core.state import get_state
        get_state().reset()
        self.r = Robot(99, "metal", (1.0, 0.0, 0.0, 1.0), (10, 5))
        robots.append(self.r)

    def tearDown(self):
        robots.remove(self.r)

    def test_stale_pick_reservation_is_released(self):
        from core.state import get_state
        s = get_state()
        shelf = (5, 5)
        s.reserved_pick_shelves.add(shelf)
        self.r.task = None
        self.r.target_shelf = None
        rc.reconcile_shelf_reservations()
        self.assertNotIn(shelf, s.reserved_pick_shelves)
        log = list(s.event_log)
        self.assertTrue(any("устаревшая резервация" in e for e in log))

    def test_stale_put_reservation_is_released(self):
        from core.state import get_state
        s = get_state()
        shelf = (5, 5)
        s.reserved_put_shelves.add(shelf)
        self.r.task = None
        self.r.target_shelf = None
        rc.reconcile_shelf_reservations()
        self.assertNotIn(shelf, s.reserved_put_shelves)

    def test_legit_pick_reservation_kept(self):
        from core.state import get_state
        s = get_state()
        shelf = (5, 5)
        s.reserved_pick_shelves.add(shelf)
        self.r.task = {"type": "retrieve", "product": "metal", "qty": 1, "shelf": shelf}
        self.r.target_shelf = shelf
        self.r.phase = "to_shelf_for_pick"
        rc.reconcile_shelf_reservations()
        self.assertIn(shelf, s.reserved_pick_shelves)

    def test_legit_put_reservation_kept(self):
        from core.state import get_state
        s = get_state()
        shelf = (5, 5)
        s.reserved_put_shelves.add(shelf)
        self.r.task = {"type": "putaway", "product": "metal", "qty": 1}
        self.r.target_shelf = shelf
        self.r.phase = "to_shelf_for_put"
        rc.reconcile_shelf_reservations()
        self.assertIn(shelf, s.reserved_put_shelves)


class TestRouteToPickupZone(unittest.TestCase):
    def setUp(self):
        from core.state import get_state
        get_state().reset()
        self.r = Robot(99, "metal", (1.0, 0.0, 0.0, 1.0), (14, 1))
        robots.append(self.r)

    def tearDown(self):
        robots.remove(self.r)

    def test_returns_route_when_standing_on_pickup(self):
        from core.grid import get_inbound_pick_cell
        pickup = get_inbound_pick_cell()
        self.r.pos = list(pickup)
        blocked = set()
        route = rc._route_to_pickup_zone(self.r, blocked)
        self.assertIsNotNone(route)
        self.assertEqual(tuple(route[0]), pickup)

    def test_self_route_is_truthy_path_for_assign(self):
        from core.grid import get_inbound_pick_cell
        from core.state import get_state
        from simulation.task_manager import assign_tasks
        s = get_state()
        pickup = get_inbound_pick_cell()
        self.r.pos = list(pickup)
        self.r.agent_ready = True
        self.r.phase = "idle"
        s.robot_task_queues["metal"].append({"type": "putaway", "product": "metal", "qty": 1})
        assign_tasks()
        self.assertIsNotNone(self.r.task)
        self.assertEqual(self.r.phase, "to_pickup_zone")
        self.assertGreaterEqual(len(self.r.route), 1)


class TestCriticalChargeAbort(unittest.TestCase):
    def setUp(self):
        from core.state import get_state
        get_state().reset()
        self.r = Robot(99, "metal", (1.0, 0.0, 0.0, 1.0), (14, 9))
        self.r.agent_ready = True
        robots.append(self.r)

    def tearDown(self):
        robots.remove(self.r)

    def test_abort_requeues_task_and_cargo(self):
        from core.state import get_state
        s = get_state()
        self.r.pos = (5, 5)
        self.r.battery = 10.0
        self.r.carry = "metal"
        self.r.task = {"type": "putaway", "product": "metal", "qty": 1}
        s.stock_total["metal"] = 0
        s.robot_task_queues["metal"].append({"type": "putaway", "product": "metal", "qty": 1})
        rc._abort_task_for_charge(self.r)
        self.assertIsNone(self.r.task)
        self.assertIsNone(self.r.carry)
        self.assertEqual(self.r.phase, "to_home_charge")
        self.assertEqual(s.stock_total["metal"], 1)
        self.assertEqual(tuple(self.r.route[-1]), self.r.home)

    def test_abort_no_path_keeps_phase(self):
        self.r.pos = (5, 5)
        self.r.battery = 10.0
        self.r.task = {"type": "retrieve", "product": "metal", "qty": 1, "shelf": (1, 1)}
        rc._abort_task_for_charge(self.r)
        self.assertIsNone(self.r.task)
        self.assertEqual(self.r.phase, "to_home_charge")


if __name__ == '__main__':
    unittest.main()