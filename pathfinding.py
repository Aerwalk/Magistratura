import heapq
from constants import AISLE_CELLS, EXIT_CELL, SHELF_X


def manhattan(a, b):
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def shelf_access_cells(shelf):
    x, y = shelf
    result = []
    for nx, ny in [(x - 1, y), (x + 1, y)]:
        if (nx, ny) in AISLE_CELLS:
            result.append((nx, ny))
    return result


def shelf_distance_score(shelf):
    return manhattan(shelf, EXIT_CELL)


def astar(start, goal, blocked=None):
    if blocked is None:
        blocked = set()

    if start == goal:
        return []

    open_heap = []
    heapq.heappush(open_heap, (manhattan(start, goal), 0, start))
    came_from = {}
    g_score = {start: 0}
    closed = set()

    while open_heap:
        _, g, current = heapq.heappop(open_heap)

        if current in closed:
            continue
        closed.add(current)

        if current == goal:
            path = []
            while current != start:
                path.append(current)
                current = came_from[current]
            path.reverse()
            return path

        for dx, dy in [(1, 0), (-1, 0), (0, 1), (0, -1)]:
            nxt = (current[0] + dx, current[1] + dy)
            if nxt not in AISLE_CELLS:
                continue
            if nxt in blocked and nxt != goal:
                continue

            ng = g + 1
            if ng < g_score.get(nxt, 10**9):
                g_score[nxt] = ng
                came_from[nxt] = current
                f = ng + manhattan(nxt, goal)
                heapq.heappush(open_heap, (f, ng, nxt))

    return []
