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

    def test_new_product_assigned_to_robot(self):
        from config import add_product
        from entities.robot import ensure_robot_for_product
        from entities import robots
        from random import randint
        name = f"mat_{randint(1000, 9999)}"
        add_product(name, (0.5, 0.5, 0.5, 1.0))
        self.assertTrue(_has_robot_for(name))
        carriers = [r for r in robots if name in r.products]
        self.assertTrue(carriers, "новый материал должен быть назначен хотя бы одному РТС")
        ensure_robot_for_product(name)
        self.assertEqual(len([r for r in robots if name in r.products]), len(carriers))

    def test_assign_tasks_uses_queue_product(self):
        from config import add_product
        from entities import robots
        from simulation.task_manager import assign_tasks
        from random import randint
        name = f"mat2_{randint(1000, 9999)}"
        add_product(name, (0.5, 0.5, 0.5, 1.0))
        carriers = [rb for rb in robots if name in rb.products]
        if not carriers:
            self.skipTest("новый материал не назначен РТС")
        r = carriers[0]
        r.agent_ready = True
        r.carry = None
        r.task = None
        s = get_state()
        s.robot_task_queues[name].append({"type": "putaway", "product": name, "source": "labeled"})
        assign_tasks()
        self.assertTrue(r.task, "РТС должен взять задачу")
        self.assertEqual(r.task["product"], name)


if __name__ == '__main__':
    unittest.main()
