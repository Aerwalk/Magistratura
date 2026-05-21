"""Pathfinding module - A* algorithm implementation."""

import heapq

from .grid import AISLE_CELLS, manhattan


def astar(start: tuple, goal: tuple, blocked: set = None) -> list:
    """
    Find shortest path using A* algorithm.
    
    Args:
        start: Starting position (x, y)
        goal: Goal position (x, y)
        blocked: Set of blocked positions to avoid
        
    Returns:
        List of positions forming the path, empty list if no path found
    """
    if blocked is None:
        blocked = set()

    if start == goal:
        return []

    if start not in AISLE_CELLS or goal not in AISLE_CELLS:
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
            if ng < g_score.get(nxt, float('inf')):
                g_score[nxt] = ng
                came_from[nxt] = current
                f = ng + manhattan(nxt, goal)
                heapq.heappush(open_heap, (f, ng, nxt))

    return []
