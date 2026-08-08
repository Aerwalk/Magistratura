import unittest, sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.state import get_state, count_on_shelves, get_shelf_max_capacity, shelf_can_store_product
from config import SHELF_CAPACITY
from core.grid import all_shelves


class TestState(unittest.TestCase):
    def setUp(self):
        s = get_state()
        s.reset()

    def test_initial_state_empty(self):
        s = get_state()
        self.assertEqual(len(s.stock_total), 0)
        self.assertEqual(len(s.demand), 0)

    def test_count_on_shelves(self):
        s = get_state()
        shelf = list(all_shelves())[0]
        s.shelf_state[shelf] = {"product": "metal", "count": 5}
        self.assertEqual(count_on_shelves("metal"), 5)

    def test_shelf_capacity_default(self):
        shelf = list(all_shelves())[0]
        self.assertEqual(get_shelf_max_capacity(shelf), SHELF_CAPACITY)

    def test_shelf_can_store_product_empty(self):
        shelf = list(all_shelves())[0]
        self.assertTrue(shelf_can_store_product(shelf, "metal"))

    def test_shelf_can_store_product_full(self):
        s = get_state()
        shelf = list(all_shelves())[0]
        s.shelf_state[shelf] = {"product": "metal", "count": SHELF_CAPACITY}
        self.assertFalse(shelf_can_store_product(shelf, "metal"))

    def test_state_reset_clears_all(self):
        s = get_state()
        s.stock_total["metal"] = 100
        s.demand["plastic"] = 50
        s.reset()
        # stock_total and demand are defaultdicts, reset creates new ones
        self.assertEqual(s.stock_total.get("metal", 0), 0)
        self.assertEqual(s.demand.get("plastic", 0), 0)


if __name__ == '__main__':
    unittest.main()
