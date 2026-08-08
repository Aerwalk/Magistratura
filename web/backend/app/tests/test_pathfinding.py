import unittest, sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.pathfinding import astar, manhattan


class TestPathfinding(unittest.TestCase):
    def test_manhattan_distance(self):
        self.assertEqual(manhattan((0, 0), (3, 4)), 7)
        self.assertEqual(manhattan((5, 5), (5, 5)), 0)

    def test_astar_straight_line(self):
        path = astar((1, 1), (1, 5))
        self.assertIsNotNone(path)
        self.assertGreater(len(path), 0)
        self.assertEqual(path[-1], (1, 5))

    def test_astar_no_path_blocked(self):
        blocked = {(1, 2), (1, 3), (1, 4)}
        path = astar((1, 1), (1, 5), blocked=blocked)
        self.assertIsNotNone(path, "should find alternative route")
        self.assertEqual(path[-1], (1, 5))

    def test_astar_self_position(self):
        path = astar((3, 3), (3, 3))
        self.assertEqual(path, [])

    def test_astar_avoids_obstacles(self):
        blocked = {(2, 2), (2, 3), (2, 4)}
        path = astar((1, 2), (3, 4), blocked=blocked)
        self.assertIsNotNone(path)
        for step in path:
            self.assertNotIn(step, blocked)


if __name__ == '__main__':
    unittest.main()
