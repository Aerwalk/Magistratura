import unittest, sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.state import get_state, WarehouseState
from config import PRODUCTS
from simulation.task_manager import supply_labeled, request_product, _has_robot_for, _warn_no_robot


class TestTaskManager(unittest.TestCase):
    def setUp(self):
        s = get_state()
        s.reset()

    def test_supply_labeled_creates_tasks(self):
        supply_labeled("metal", 5)
        s = get_state()
        self.assertEqual(len(s.robot_task_queues["metal"]), 5)
        for task in s.robot_task_queues["metal"]:
            self.assertEqual(task["type"], "putaway")

    def test_request_product_creates_retrieve_tasks(self):
        s = get_state()
        s.shelf_state[(5, 5)] = {"product": "metal", "count": 10}
        request_product("metal", 3)
        self.assertGreaterEqual(len(s.robot_task_queues["metal"]), 3)

    def test_supply_unlabeled_adds_to_uav_queue(self):
        from simulation.task_manager import supply_unlabeled
        supply_unlabeled(4)
        s = get_state()
        self.assertEqual(len(s.uav_scan_queue), 1)

    def test_has_robot_for(self):
        from entities import robots
        has_metal = any("metal" in r.products for r in robots)
        self.assertEqual(_has_robot_for("metal"), has_metal)


if __name__ == '__main__':
    unittest.main()
