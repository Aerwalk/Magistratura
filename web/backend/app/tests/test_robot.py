import unittest, sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from entities.robot import Robot, robots


class TestRobot(unittest.TestCase):
    def setUp(self):
        self.robot = Robot(99, "metal", (1.0, 0.0, 0.0, 1.0), (10, 5))

    def test_robot_initial_state(self):
        self.assertEqual(self.robot.pos, (10, 5))
        self.assertEqual(self.robot.carry, None)
        self.assertEqual(self.robot.phase, "idle")
        self.assertEqual(self.robot.capacity, 1)

    def test_robot_is_moving(self):
        self.assertFalse(self.robot.is_moving())
        self.robot.current_target = (11, 5)
        self.assertTrue(self.robot.is_moving())

    def test_robot_is_active_with_route(self):
        self.assertFalse(self.robot.is_active())
        self.robot.route = [(11, 5)]
        self.assertTrue(self.robot.is_active())

    def test_robot_check_stuck(self):
        self.assertFalse(self.robot.check_stuck())
        self.robot.last_pos = self.robot.pos
        self.robot.current_target = (11, 5)
        self.robot.stuck_ticks = 0
        for _ in range(101):
            self.robot.check_stuck()
        self.assertGreater(self.robot.stuck_ticks, 100)

    def test_robot_reset(self):
        self.robot.carry = "metal"
        self.robot.route = [(11, 5)]
        self.robot.phase = "to_shelf_for_put"
        self.robot.reset()
        self.assertIsNone(self.robot.carry)
        self.assertEqual(self.robot.route, [])
        self.assertEqual(self.robot.phase, "idle")

    def test_robot_products_set(self):
        self.assertIn("metal", self.robot.products)
        self.robot.products.add("plastic")
        self.assertIn("plastic", self.robot.products)


if __name__ == '__main__':
    unittest.main()
