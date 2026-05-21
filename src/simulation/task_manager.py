"""Task manager module."""

import random

from src.config import PRODUCTS
from src.core.state import get_state
from src.core.grid import shelf_access_cells, shelf_distance_score, manhattan, all_shelves
from src.core.pathfinding import astar
from src.entities import robots


def supply_labeled(product: str, qty: int) -> None:
    """Add labeled supply to warehouse."""
    state = get_state()
    if qty <= 0:
        return
    for _ in range(qty):
        state.stock_total[product] += 1
        state.robot_task_queues[product].append(
            {"type": "putaway", "product": product, "source": "labeled"}
        )
    state.event_log.appendleft(f"Поставка с меткой: {product}, количество {qty}")


def supply_unlabeled(qty: int) -> None:
    """Add unlabeled supply to UAV scanning queue."""
    state = get_state()
    if qty <= 0:
        return
    state.uav_scan_queue.append(qty)
    state.event_log.appendleft(
        f"Пришла поставка без метки, количество {qty}. БВС начал распознавание."
    )


def request_product(product: str, qty: int) -> None:
    """Request product from warehouse."""
    state = get_state()
    if qty <= 0:
        return

    available = sum(
        info["count"]
        for info in state.shelf_state.values()
        if info["product"] == product
    )
    qty = min(qty, available)
    if qty <= 0:
        state.event_log.appendleft(f"Товар {product} недоступен на полках")
        return

    state.demand[product] += qty

    for _ in range(qty):
        state.robot_task_queues[product].append(
            {"type": "retrieve", "product": product}
        )
    state.event_log.appendleft(f"Запрос: {product}, количество {qty}")


def _choose_best_put_shelf(product: str) -> tuple:
    """Choose best shelf for putting away a product."""
    state = get_state()
    candidates = []
    for shelf, info in state.shelf_state.items():
        if shelf in state.reserved_put_shelves:
            continue
        if info["count"] == 0 or (info["product"] == product and info["count"] < 5):
            candidates.append(shelf)

    if not candidates:
        return None

    def score(shelf):
        info = state.shelf_state[shelf]
        hotness = 1 + state.demand.get(product, 0)
        same_partial_bonus = -10 if info["product"] == product and 0 < info["count"] < 5 else 0
        return shelf_distance_score(shelf) / hotness + same_partial_bonus

    return min(candidates, key=score)


def _choose_best_pick_shelf(product: str) -> tuple:
    """Choose best shelf for picking a product."""
    state = get_state()
    candidates = []
    for shelf, info in state.shelf_state.items():
        if shelf in state.reserved_pick_shelves:
            continue
        if info["product"] == product and info["count"] > 0:
            candidates.append(shelf)

    if not candidates:
        return None

    return min(candidates, key=shelf_distance_score)


def _get_blocked_cells(exclude_robot=None) -> set:
    """Get cells blocked by other robots."""
    blocked = set()
    for r in robots:
        if r != exclude_robot and r.current_target is None:
            blocked.add(r.pos)
    return blocked


def assign_tasks() -> None:
    """Assign tasks to idle robots."""
    state = get_state()
    
    for robot in robots:
        if robot.task is not None:
            continue
        if robot.is_active():
            continue

        queue = state.robot_task_queues[robot.product]

        if not queue:
            if robot.pos != robot.home:
                blocked = _get_blocked_cells(exclude_robot=robot)
                route = astar(robot.pos, robot.home, blocked=blocked)
                if route:
                    robot.route = route
                    robot.phase = "to_home"
            continue

        task = queue[0]

        if task["type"] == "rebalance":
            from_shelf = task["from_shelf"]
            info = state.shelf_state[from_shelf]

            if info["count"] == 0 or info["product"] != robot.product:
                queue.popleft()
                continue

            accesses = shelf_access_cells(from_shelf)
            if not accesses:
                queue.popleft()
                continue

            blocked = _get_blocked_cells(exclude_robot=robot)
            access = min(accesses, key=lambda c: manhattan(robot.pos, c))
            route = astar(robot.pos, access, blocked=blocked)

            if route:
                robot.task = queue.popleft()
                robot.phase = "rebalance_pick"
                robot.route = route
                robot.target_shelf = from_shelf
            continue

        blocked = _get_blocked_cells(exclude_robot=robot)

        if task["type"] == "putaway":
            route = astar(robot.pos, (2, 1), blocked=blocked)
            if len(route) == 0:
                continue
            robot.task = queue.popleft()
            robot.phase = "to_pickup_zone"
            robot.route = route
            robot.carry = None
            robot.target_shelf = None

        elif task["type"] == "retrieve":
            shelf = _choose_best_pick_shelf(robot.product)
            if shelf is None:
                queue.popleft()
                state.event_log.appendleft(f"Не найдена полка для выдачи {robot.product}")
                continue

            accesses = shelf_access_cells(shelf)
            if not accesses:
                queue.popleft()
                state.event_log.appendleft(f"Нет прохода к полке {shelf}")
                continue

            state.reserved_pick_shelves.add(shelf)
            access = min(accesses, key=lambda c: manhattan(robot.pos, c))
            blocked_for_route = _get_blocked_cells(exclude_robot=robot)
            route1 = astar(robot.pos, access, blocked=blocked_for_route)
            route2 = astar(access, (0, 5), blocked=blocked_for_route)
            route3 = astar((0, 5), robot.home, blocked=blocked_for_route)

            if len(route1) == 0:
                state.reserved_pick_shelves.discard(shelf)
                continue

            robot.task = queue.popleft()
            robot.task["shelf"] = shelf
            robot.phase = "to_shelf_for_pick"
            robot.route = route1
            robot.next_route_after_phase = route2
            robot.final_route_after_exit = route3
            robot.carry = None
            robot.target_shelf = shelf
