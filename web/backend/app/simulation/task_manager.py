import random

from config import PRODUCTS
from core.state import get_state, get_shelf_max_capacity, get_shelf_allowed_products
from core.grid import shelf_access_cells, shelf_distance_score, manhattan, all_shelves, get_inbound_pick_cell, get_exit_cell
from core.pathfinding import astar
from entities import robots


def _has_robot_for(product: str) -> bool:
    return any(product in r.products for r in robots)


def _warn_no_robot(product: str):
    if not _has_robot_for(product):
        state = get_state()
        state.event_log.appendleft(f"⚠ ВНИМАНИЕ: нет РТС, способного возить {product}!")


def _warn_full_shelves(product: str):
    from core.state import get_state
    state = get_state()
    full = sum(
        1 for shelf, info in state.shelf_state.items()
        if info["product"] == product and info["count"] >= get_shelf_max_capacity(shelf) - 1
    )
    if full >= 3:
        state.event_log.appendleft(
            f"⚠ ВНИМАНИЕ: полки для {product} почти заполнены ({full} полок заняты)!"
        )


def supply_labeled(product: str, qty: int) -> None:
    state = get_state()
    if qty <= 0:
        return
    _warn_no_robot(product)
    for _ in range(qty):
        state.stock_total[product] += 1
        state.robot_task_queues[product].append(
            {"type": "putaway", "product": product, "source": "labeled"}
        )
    state.event_log.appendleft(f"Поставка с меткой: {product}, количество {qty}")


def supply_unlabeled(qty: int) -> None:
    state = get_state()
    if qty <= 0:
        return
    state.uav_scan_queue.append(qty)
    state.event_log.appendleft(
        f"Пришла поставка без метки, количество {qty}. БВС начал распознавание."
    )


def request_product(product: str, qty: int) -> None:
    state = get_state()
    if qty <= 0:
        return
    _warn_no_robot(product)
    _warn_full_shelves(product)
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
    state = get_state()
    candidates = []
    for shelf, info in state.shelf_state.items():
        if shelf in state.reserved_put_shelves:
            continue
        cap = get_shelf_max_capacity(shelf)
        allowed = get_shelf_allowed_products(shelf)
        if allowed is not None and product not in allowed:
            continue
        if info["count"] == 0 or (info["product"] == product and info["count"] < cap):
            candidates.append(shelf)
    if not candidates:
        return None
    def score(shelf):
        info = state.shelf_state[shelf]
        hotness = 1 + state.demand.get(product, 0)
        cap = get_shelf_max_capacity(shelf)
        same_partial_bonus = -10 if info["product"] == product and 0 < info["count"] < cap else 0
        return shelf_distance_score(shelf) / hotness + same_partial_bonus
    return min(candidates, key=score)


def _choose_best_pick_shelf(product: str) -> tuple:
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
    blocked = set()
    for r in robots:
        if r != exclude_robot and r.current_target is None:
            blocked.add(r.pos)
    return blocked


def assign_tasks() -> None:
    state = get_state()
    for robot in robots:
        if robot.task is not None:
            continue
        if robot.is_active():
            continue
        queue = _pick_robot_queue(robot, state)
        if queue is None:
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
            if info["count"] == 0 or info["product"] not in robot.products:
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
            else:
                state.event_log.appendleft(
                    f"⚠ {robot.name}: нет пути к полке {from_shelf} для ребалансировки!"
                )
            continue
        blocked = _get_blocked_cells(exclude_robot=robot)
        if task["type"] == "putaway":
            route = astar(robot.pos, get_inbound_pick_cell(), blocked=blocked)
            if len(route) == 0:
                state.event_log.appendleft(
                    f"⚠ {robot.name}: нет пути к зоне забора!"
                )
                continue
            qty = 1
            while qty < robot.capacity and len(queue) > 0 and queue[0]["type"] == "putaway":
                queue.popleft()
                qty += 1
            robot.task = {"type": "putaway", "product": robot.product, "qty": qty}
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
            # Pop first task + batch additional up to robot.capacity
            queue.popleft()
            qty = 1
            while qty < robot.capacity and len(queue) > 0 and queue[0]["type"] == "retrieve" and queue[0]["product"] == robot.product:
                queue.popleft()
                qty += 1
            access = min(accesses, key=lambda c: manhattan(robot.pos, c))
            blocked_for_route = _get_blocked_cells(exclude_robot=robot)
            ex = get_exit_cell()
            route1 = astar(robot.pos, access, blocked=blocked_for_route)
            route2 = astar(access, ex, blocked=blocked_for_route)
            route3 = astar(ex, robot.home, blocked=blocked_for_route)
            if len(route1) == 0:
                state.reserved_pick_shelves.discard(shelf)
                state.event_log.appendleft(
                    f"⚠ {robot.name}: нет пути к полке {shelf} для забора!"
                )
                for _ in range(qty):
                    state.robot_task_queues[robot.product].appendleft({"type": "retrieve", "product": robot.product})
                continue
            robot.task = {"type": "retrieve", "product": robot.product, "qty": qty, "shelf": shelf}
            robot.phase = "to_shelf_for_pick"
            robot.route = route1
            robot.next_route_after_phase = route2
            robot.final_route_after_exit = route3
            robot.carry = None
            robot.target_shelf = shelf


def _pick_robot_queue(robot, state):
    for p in robot.products:
        q = state.robot_task_queues.get(p)
        if q and len(q) > 0:
            return q
    return None
