import unittest, sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from entities.robot import Robot
from config.constants import BATTERY_TASK_DRAIN


class TestBatteryDrain(unittest.TestCase):
    def setUp(self):
        from core.state import get_state
        get_state().reset()
        self.robot = Robot(99, "metal", (1.0, 0.0, 0.0, 1.0), (10, 5))
        self.robot.agent_ready = True

    def test_initial_battery_full(self):
        self.assertEqual(self.robot.battery, 100.0)
        self.assertEqual(self.robot.battery_max, 100.0)

    def test_task_drain_constant(self):
        self.assertEqual(BATTERY_TASK_DRAIN, 15.0)

    def test_drain_battery_putaway(self):
        from simulation.robot_controller import _drain_battery
        self.robot.battery = 80.0
        _drain_battery(self.robot, "putaway")
        self.assertAlmostEqual(self.robot.battery, 80.0 - BATTERY_TASK_DRAIN)

    def test_drain_battery_never_below_zero(self):
        from simulation.robot_controller import _drain_battery
        self.robot.battery = 3.0
        _drain_battery(self.robot, "retrieve")
        self.assertEqual(self.robot.battery, 0.0)

    def test_drain_battery_retrieve(self):
        from simulation.robot_controller import _drain_battery
        self.robot.battery = 100.0
        _drain_battery(self.robot, "retrieve")
        self.assertAlmostEqual(self.robot.battery, 100.0 - BATTERY_TASK_DRAIN)

    def test_metrics_render_contains_robot(self):
        from metrics import render_prometheus
        body, _ = render_prometheus()
        self.assertIn("magsim_robot_battery_percent", body)


if __name__ == '__main__':
    unittest.main()