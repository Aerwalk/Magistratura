"""Grid module - warehouse layout and spatial calculations."""

from src.config import (
    GRID_W,
    GRID_H,
    SHELF_X,
    EXIT_CELL,
    INBOUND_CELL,
    INBOUND_PICK_CELL,
    HOME_CELLS,
)


def is_shelf_cell(x: int, y: int) -> bool:
    """Check if cell is a shelf position."""
    return x in SHELF_X and y not in {0, 1, 2, 7, 8, 9} and 0 <= y < GRID_H


def all_shelves():
    """Generate all shelf positions in the grid."""
    for x in range(GRID_W):
        for y in range(GRID_H):
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
    return manhattan(shelf, EXIT_CELL)


def manhattan(a: tuple, b: tuple) -> int:
    """Calculate Manhattan distance between two points."""
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


# Build aisle cells set
AISLE_CELLS = set()
for x in range(GRID_W):
    for y in range(GRID_H):
        if x not in SHELF_X or y in {0, 1, 2, 7, 8, 9}:
            AISLE_CELLS.add((x, y))

for home in HOME_CELLS:
    AISLE_CELLS.add(home)

AISLE_CELLS.add(EXIT_CELL)
AISLE_CELLS.add(INBOUND_CELL)
AISLE_CELLS.add(INBOUND_PICK_CELL)
