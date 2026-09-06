import unittest, sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from entities.robot import robots
from metrics import (
    render_prometheus, record_task_assigned, record_distance_moved,
    record_stuck_event, record_charge_session, record_battery_replaced,
    record_cell_visit,
)


class TestFleetMetrics(unittest.TestCase):
    def setUp(self):
        from core.state import get_state
        get_state().reset()

    def _body(self):
        body, _ = render_prometheus()
        return body

    def test_render_exposes_all_metric_families(self):
        body = self._body()
        expected = [
            "magsim_robot_battery_percent",
            "magsim_robot_speed",
            "magsim_robot_loaded",
            "magsim_robot_phase",
            "magsim_robot_tasks_assigned_total",
            "magsim_robot_distance_moved_total",
            "magsim_robot_tasks_completed_total",
            "magsim_robot_stuck",
            "magsim_robot_stuck_events_total",
            "magsim_robot_charge_sessions_total",
            "magsim_robot_battery_replaced_total",
            "magsim_robot_info",
            "magsim_warehouse_stock_on_shelves",
            "magsim_warehouse_task_queue",
            "magsim_warehouse_delivered_total",
            "magsim_warehouse_rebalance_active",
        ]
        for name in expected:
            self.assertIn(name, body)

    def test_task_assigned_counter(self):
        rid = str(robots[0].id)
        from metrics import task_assigned_counter
        before = task_assigned_counter.labels(robot_id=rid, task_type="putaway")._value.get()
        record_task_assigned(robots[0].id, "putaway")
        after = task_assigned_counter.labels(robot_id=rid, task_type="putaway")._value.get()
        self.assertEqual(after - before, 1)
        body = self._body()
        self.assertRegex(body, r'tasks_assigned_total\{[^}]*robot_id="%s"[^}]*\}\s+%s' % (rid, str(after)))

    def test_distance_moved_counter(self):
        from metrics import distance_counter
        rid = str(robots[0].id)
        before = distance_counter.labels(robot_id=rid)._value.get()
        record_distance_moved(robots[0].id, 3.5)
        after = distance_counter.labels(robot_id=rid)._value.get()
        self.assertEqual(after - before, 3.5)
        self.assertRegex(self._body(), r'distance_moved_total\{[^}]*robot_id="%s"[^}]*\}\s+%s' % (rid, str(after)))

    def test_stuck_event_counter(self):
        from metrics import robot_stuck_events_counter
        rid = str(robots[0].id)
        name = robots[0].name
        before = robot_stuck_events_counter.labels(robot_id=rid, name=name)._value.get()
        record_stuck_event(robots[0])
        after = robot_stuck_events_counter.labels(robot_id=rid, name=name)._value.get()
        self.assertEqual(after - before, 1)

    def test_charge_and_replacement_counters(self):
        from metrics import charge_sessions_counter, battery_replaced_counter
        rid = str(robots[0].id)
        before_c = charge_sessions_counter.labels(robot_id=rid)._value.get()
        before_b = battery_replaced_counter.labels(robot_id=rid)._value.get()
        record_charge_session(robots[0])
        record_battery_replaced(robots[0])
        self.assertEqual(charge_sessions_counter.labels(robot_id=rid)._value.get() - before_c, 1)
        self.assertEqual(battery_replaced_counter.labels(robot_id=rid)._value.get() - before_b, 1)

    def test_warehouse_gauges_show_values(self):
        from core.state import get_state
        s = get_state()
        s.delivered_total["metal"] = 4
        s.stock_total["metal"] = 7
        shelf = next(iter(s.shelf_state))
        s.shelf_state[shelf] = {"product": "metal", "count": 3}
        body = self._body()
        self.assertRegex(body, r'delivered_total\{product="metal"\}\s+4\.0')
        self.assertRegex(body, r'stock_total\{product="metal"\}\s+7\.0')
        self.assertRegex(body, r'stock_on_shelves\{product="metal"\}\s+3\.0')

    def test_cell_visit_counter(self):
        from metrics import movement_counter
        cid = "({},{})".format(3, 4), "3", "4"
        before = movement_counter.labels(robot_id="1", cell=cid[0], x=cid[1], y=cid[2])._value.get()
        record_cell_visit(1, (3, 4))
        after = movement_counter.labels(robot_id="1", cell=cid[0], x=cid[1], y=cid[2])._value.get()
        self.assertEqual(after - before, 1)

    def test_health_metrics_exposed(self):
        body = self._body()
        for name in [
            "magsim_health_database_connected",
            "magsim_health_agents_connected",
            "magsim_health_robots_ready",
            "magsim_health_uav_connected",
            "magsim_health_sim_ticks_total",
            "magsim_health_last_tick_timestamp",
            "magsim_health_uptime_seconds",
            "magsim_tests_last_result",
            "magsim_tests_runs_total",
            "magsim_tests_failed_total",
            "magsim_tests_last_run_timestamp",
        ]:
            self.assertIn(name, body)

    def test_sim_tick_recording(self):
        from metrics import record_sim_tick, health_sim_ticks_total, health_last_tick_timestamp
        before = health_sim_ticks_total._value.get()
        record_sim_tick(1000.0)
        after = health_sim_ticks_total._value.get()
        self.assertEqual(after - before, 1)
        self.assertEqual(health_last_tick_timestamp._value.get(), 1000.0)

    def test_test_results_recording(self):
        from metrics import (
            record_test_results,
            tests_last_result, tests_runs_total,
            tests_failed_total, tests_last_run_timestamp,
        )
        before = tests_runs_total.labels(suite="unit")._value.get()
        payload = {
            "tests": {
                "total": 2, "passed": 1, "failed": 1,
                "tests": [
                    {"name": "ok_test", "passed": True},
                    {"name": "bad_test", "passed": False},
                ],
            },
            "scenarios": [
                {"name": "sc_ok", "passed": True},
            ],
        }
        record_test_results(payload)
        self.assertEqual(tests_runs_total.labels(suite="unit")._value.get() - before, 1)
        self.assertEqual(tests_last_result.labels(suite="unit", name="ok_test")._value.get(), 1.0)
        self.assertEqual(tests_last_result.labels(suite="unit", name="bad_test")._value.get(), 0.0)
        self.assertEqual(tests_failed_total.labels(suite="unit")._value.get() - before, 1)
        self.assertEqual(tests_last_result.labels(suite="scenario", name="sc_ok")._value.get(), 1.0)
        self.assertGreater(tests_last_run_timestamp.labels(suite="unit")._value.get(), 0)


if __name__ == '__main__':
    unittest.main()