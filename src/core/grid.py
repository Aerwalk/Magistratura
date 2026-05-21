"""Grid module - warehouse layout and spatial calculations."""

import src.config.constants as _consts

# Dynamic extensions beyond static config
CUSTOM_SHELF_CELLS: set = set()
REMOVED_SHELF_CELLS: set = set()
_EXIT_CELL_OVERRIDE = None
_INBOUND_CELL_OVERRIDE = None
_INBOUND_PICK_CELL_OVERRIDE = None


def get_grid_w() -> int:
    return _consts.GRID_W


def get_grid_h() -> int:
    return _consts.GRID_H


def get_exit_cell() -> tuple:
    return _EXIT_CELL_OVERRIDE if _EXIT_CELL_OVERRIDE else _consts.EXIT_CELL


def get_inbound_cell() -> tuple:
    return _INBOUND_CELL_OVERRIDE if _INBOUND_CELL_OVERRIDE else _consts.INBOUND_CELL


def get_inbound_pick_cell() -> tuple:
    return _INBOUND_PICK_CELL_OVERRIDE if _INBOUND_PICK_CELL_OVERRIDE else _consts.INBOUND_PICK_CELL


def is_shelf_cell(x: int, y: int) -> bool:
    """Check if cell is a shelf position."""
    w = get_grid_w()
    h = get_grid_h()
    if not (0 <= x < w and 0 <= y < h):
        return False
    if (x, y) in CUSTOM_SHELF_CELLS:
        return True
    if (x, y) in REMOVED_SHELF_CELLS:
        return False
    return x in _consts.SHELF_X and y not in {0, 1, 2, 7, 8, 9} and 0 <= y < h


def all_shelves():
    """Generate all shelf positions in the grid."""
    for y in range(get_grid_h()):
        for x in range(get_grid_w()):
            if is_shelf_cell(x, y):
                yield (x, y)


def shelf_access_cells(shelf: tuple) -> list:
    """Get accessible cells adjacent to a shelf."""
    x, y = shelf
    result = []
    for nx, ny in [(x - 1, y), (x + 1, y)]:
        if (nx, ny) in AISLE_CELLS:
            result.append((nx, ny))
    return result


def shelf_distance_score(shelf: tuple) -> float:
    """Calculate shelf score based on distance to exit."""
    return manhattan(shelf, get_exit_cell())


def manhattan(a: tuple, b: tuple) -> int:
    """Calculate Manhattan distance between two points."""
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def add_home_cell(cell: tuple) -> None:
    """Dynamically add a new home cell to the aisle cells set."""
    AISLE_CELLS.add(cell)


def add_custom_shelf(x: int, y: int) -> None:
    """Add a custom shelf at the given position."""
    CUSTOM_SHELF_CELLS.add((x, y))
    from src.core.state import get_state
    state = get_state()
    if (x, y) not in state.shelf_state:
        state.shelf_state[(x, y)] = {"count": 0, "product": None}
    state.reserved_put_shelves.discard((x, y))
    state.reserved_pick_shelves.discard((x, y))
    rebuild_aisle_cells()


def remove_custom_shelf(x: int, y: int) -> None:
    """Remove a custom shelf at the given position."""
    CUSTOM_SHELF_CELLS.discard((x, y))
    from src.core.state import get_state
    state = get_state()
    # Only remove shelf_state if it's not a standard config shelf
    if not is_standard_shelf(x, y):
        state.shelf_state.pop((x, y), None)
    state.reserved_pick_shelves.discard((x, y))
    state.reserved_put_shelves.discard((x, y))
    rebuild_aisle_cells()


def is_custom_shelf(x: int, y: int) -> bool:
    """Check if cell is a user-added custom shelf."""
    return (x, y) in CUSTOM_SHELF_CELLS


def is_standard_shelf(x: int, y: int) -> bool:
    """Check if cell is an original predefined shelf."""
    w = get_grid_w()
    h = get_grid_h()
    if not (0 <= x < w and 0 <= y < h):
        return False
    if (x, y) in REMOVED_SHELF_CELLS:
        return False
    return x in _consts.SHELF_X and y not in {0, 1, 2, 7, 8, 9} and 0 <= y < h


def set_exit_cell(x: int, y: int) -> None:
    """Set a new exit cell position."""
    global _EXIT_CELL_OVERRIDE
    old = get_exit_cell()
    _EXIT_CELL_OVERRIDE = (x, y)
    _consts.EXIT_CELL = (x, y)
    if old != (x, y):
        rebuild_aisle_cells()


def set_inbound_cell(x: int, y: int) -> None:
    """Set a new inbound cell position."""
    global _INBOUND_CELL_OVERRIDE
    _INBOUND_CELL_OVERRIDE = (x, y)
    _consts.INBOUND_CELL = (x, y)


def set_inbound_pick_cell(x: int, y: int) -> None:
    """Set a new inbound pick cell position."""
    global _INBOUND_PICK_CELL_OVERRIDE
    _INBOUND_PICK_CELL_OVERRIDE = (x, y)
    _consts.INBOUND_PICK_CELL = (x, y)


def set_grid_size(new_w: int, new_h: int) -> None:
    """Resize the warehouse grid and update state."""
    old_w = get_grid_w()
    old_h = get_grid_h()
    _consts.GRID_W = new_w
    _consts.GRID_H = new_h

    from src.core.state import get_state
    state = get_state()
    for x in range(old_w, new_w):
        for y in range(new_h):
            if is_shelf_cell(x, y) and (x, y) not in state.shelf_state:
                state.shelf_state[(x, y)] = {"count": 0, "product": None}
    for y in range(old_h, new_h):
        for x in range(min(old_w, new_w)):
            if is_shelf_cell(x, y) and (x, y) not in state.shelf_state:
                state.shelf_state[(x, y)] = {"count": 0, "product": None}

    rebuild_aisle_cells()


def rebuild_aisle_cells() -> None:
    """Rebuild the AISLE_CELLS set based on current grid dimensions."""
    global AISLE_CELLS
    w = get_grid_w()
    h = get_grid_h()
    cells = set()
    for x in range(w):
        for y in range(h):
            if not is_shelf_cell(x, y):
                cells.add((x, y))
    for home in _consts.HOME_CELLS:
        cells.add(home)
    cells.add(get_exit_cell())
    cells.add(get_inbound_cell())
    cells.add(get_inbound_pick_cell())
    AISLE_CELLS = cells


# Build aisle cells set
rebuild_aisle_cells()
