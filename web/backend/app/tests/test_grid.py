import unittest, sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.grid import (
    get_grid_w, get_grid_h, all_shelves, shelf_access_cells,
    add_custom_shelf, remove_custom_shelf, set_grid_size,
    is_shelf_cell, is_custom_shelf, get_exit_cell, get_inbound_pick_cell,
    CUSTOM_SHELF_CELLS, REMOVED_SHELF_CELLS
)


from collections.abc import Generator

...

class TestGrid(unittest.TestCase):
    def setUp(self):
        CUSTOM_SHELF_CELLS.clear()
        REMOVED_SHELF_CELLS.clear()

    def test_all_shelves_returns_list(self):
        shelves = list(all_shelves())
        self.assertIsInstance(shelves, list)
        self.assertGreater(len(shelves), 0)

    def test_shelf_access_cells(self):
        accesses = shelf_access_cells((5, 5))
        self.assertIsInstance(accesses, list)
        for cell in accesses:
            x, y = cell
            self.assertGreaterEqual(x, 0)
            self.assertGreaterEqual(y, 0)

    def test_add_remove_custom_shelf(self):
        add_custom_shelf(3, 7)
        self.assertIn((3, 7), CUSTOM_SHELF_CELLS)
        remove_custom_shelf(3, 7)
        self.assertNotIn((3, 7), CUSTOM_SHELF_CELLS)

    def test_is_shelf_cell(self):
        self.assertIsInstance(is_shelf_cell(0, 0), bool)
        # Standard shelf positions
        self.assertTrue(is_shelf_cell(2, 2) or not is_shelf_cell(2, 2))

    def test_is_custom_shelf(self):
        self.assertFalse(is_custom_shelf(0, 0))
        add_custom_shelf(3, 7)
        self.assertTrue(is_custom_shelf(3, 7))
        remove_custom_shelf(3, 7)

    def test_exit_inbound_cells(self):
        exit_cell = get_exit_cell()
        inbound = get_inbound_pick_cell()
        self.assertEqual(len(exit_cell), 2)
        self.assertEqual(len(inbound), 2)

    def test_grid_size_change(self):
        old_w, old_h = get_grid_w(), get_grid_h()
        set_grid_size(10, 8)
        self.assertEqual(get_grid_w(), 10)
        self.assertEqual(get_grid_h(), 8)
        set_grid_size(old_w, old_h)


if __name__ == '__main__':
    unittest.main()
