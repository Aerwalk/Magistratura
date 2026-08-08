import numpy as np

from core.state import get_state, count_on_shelves, product_hotness, get_shelf_max_capacity, get_shelf_allowed_products
from core.grid import shelf_access_cells, manhattan, all_shelves, shelf_distance_score, get_exit_cell, get_inbound_pick_cell
from core.pathfinding import astar
from entities import robots
from entities.base import move_agent_towards_2d, close2


def _start_robot_next_segment(robot) -> None:
    if robot.current_target is None and robot.route:
        robot.current_target = robot.route.pop(0)


def _update_single_robot_motion(robot) -> None:
    if robot.delivery_anim_ticks > 0:
        robot.delivery_anim_ticks -= 1
        progress = 1.0 - (robot.delivery_anim_ticks / 25.0)
        robot.carry_bob = abs(progress - 0.5) * 0.3
    if robot.pickup_anim_ticks > 0:
        robot.pickup_anim_ticks -= 1
        progress = 1.0 - (robot.pickup_anim_ticks / 15.0)
        robot.carry_appear_scale = progress
    if robot.wait_ticks > 0:
        robot.wait_ticks -= 1
        return
    if robot.current_target is None and robot.route:
        _start_robot_next_segment(robot)
    if robot.current_target is None:
        return
    tx, ty = robot.current_target
    robot.draw_pos = move_agent_towards_2d(robot.draw_pos, (tx, ty), robot.speed)
    if close2(robot.draw_pos, (tx, ty)):
        robot.draw_pos = [float(tx), float(ty)]
        robot.pos = (tx, ty)
        robot.current_target = None
        robot.wait_ticks = 2
        _start_robot_next_segment(robot)


def move_robots_one_step() -> None:
    for robot in robots:
        _update_single_robot_motion(robot)


def _get_blocked_cells(exclude_robot=None) -> set:
    blocked = set()
    for r in robots:
        if r != exclude_robot and r.current_target is None:
            blocked.add(r.pos)
    return blocked


def _choose_best_put_shelf(product: str):
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


def _handle_putaway_phase(r, task):
    state = get_state()
    if r.phase == "to_pickup_zone":
        r.carry = task["product"]
        r.carry_qty = task.get("qty", 1)
        r.pickup_anim_ticks = 15
        shelf = _choose_best_put_shelf(r.carry)
        if shelf is None:
            state.stock_total[r.carry] = state.stock_total.get(r.carry, 0) + r.carry_qty
            event = f"Нет свободной полки для {r.product}, {r.carry_qty} ед. возвращено на склад"
            r.carry = None
            r.carry_qty = 0
            r.task = None
            r.phase = "idle"
            state.event_log.appendleft(event)
            return
        accesses = shelf_access_cells(shelf)
        if not accesses:
            state.stock_total[r.carry] = state.stock_total.get(r.carry, 0) + r.carry_qty
            event = f"Нет прохода к полке {shelf} для {r.product}, {r.carry_qty} ед. возвращено"
            r.carry = None
            r.carry_qty = 0
            r.task = None
            r.phase = "idle"
            state.event_log.appendleft(event)
            return
        state.reserved_put_shelves.add(shelf)
        blocked = _get_blocked_cells(exclude_robot=r)
        access = min(accesses, key=lambda c: manhattan(r.pos, c))
        r.route = astar(r.pos, access, blocked=blocked)
        if not r.route:
            state.stock_total[r.carry] = state.stock_total.get(r.carry, 0) + r.carry_qty
            state.event_log.appendleft(f"{r.name}: нет пути к полке {shelf}, {r.carry_qty} ед. возвращено")
            state.reserved_put_shelves.discard(shelf)
            r.carry = None
            r.carry_qty = 0
            r.task = None
            r.phase = "idle"
            return
        r.target_shelf = shelf
        r.phase = "to_shelf_for_put"
    elif r.phase == "to_shelf_for_put":
        shelf = r.target_shelf
        if shelf is None:
            r.phase = "idle"
            return
        info = state.shelf_state[shelf]
        cap = get_shelf_max_capacity(shelf)
        placed = 0
        if info["count"] == 0 or (info["product"] == r.carry and info["count"] < cap):
            if info["count"] == 0:
                info["product"] = r.carry
            space = cap - info["count"]
            batch = min(r.carry_qty, space)
            info["count"] += batch
            r.carry_qty -= batch
            placed = batch
            state.event_log.appendleft(
                f"РТС-{r.id} ({r.product}) разместил {r.carry}×{batch} на полке {shelf} [{info['count']}/{cap}], осталось {r.carry_qty}"
            )
        if placed == 0:
            state.event_log.appendleft(f"Полка {shelf} недоступна для {r.product}, {r.carry_qty} ед. возвращено на склад")
            state.stock_total[r.carry] = state.stock_total.get(r.carry, 0) + r.carry_qty
            r.carry_qty = 0
        state.reserved_put_shelves.discard(shelf)
        r.target_shelf = None
        # Place remaining items on another shelf
        if r.carry_qty > 0:
            shelf = _choose_best_put_shelf(r.carry)
            if shelf:
                accesses = shelf_access_cells(shelf)
                if accesses:
                    state.reserved_put_shelves.add(shelf)
                    blocked = _get_blocked_cells(exclude_robot=r)
                    access = min(accesses, key=lambda c: manhattan(r.pos, c))
                    route = astar(r.pos, access, blocked=blocked)
                    if route:
                        r.target_shelf = shelf
                        r.route = route
                        r.phase = "to_shelf_for_put"
                        return
            # Can't place remaining items — return to stock
            state.event_log.appendleft(
                f"РТС-{r.id}: нет полок для оставшихся {r.carry_qty}×{r.carry}, возвращено на склад"
            )
            state.stock_total[r.carry] = state.stock_total.get(r.carry, 0) + r.carry_qty
            r.carry_qty = 0
        # All items placed — finish
        r.carry = None
        r.task = None
        if state.robot_task_queues[r.product]:
            blocked = _get_blocked_cells(exclude_robot=r)
            route = astar(r.pos, get_inbound_pick_cell(), blocked=blocked)
            if route:
                r.task = state.robot_task_queues[r.product].popleft()
                r.phase = "to_pickup_zone"
                r.route = route
            else:
                state.event_log.appendleft(f"⚠ {r.name}: нет пути к зоне забора для следующей задачи!")
                r.phase = "idle"
        else:
            r.phase = "idle"


def _handle_retrieve_phase(r, task):
    state = get_state()
    if r.phase == "to_shelf_for_pick":
        shelf = task["shelf"]
        info = state.shelf_state[shelf]
        remaining = task["qty"] - (r.carry_qty or 0)
        if info["product"] == task["product"] and info["count"] > 0:
            take = min(remaining, info["count"])
            info["count"] -= take
            r.carry = task["product"]
            r.carry_qty = (r.carry_qty or 0) + take
            r.pickup_anim_ticks = 15
            state.stock_total[task["product"]] -= take
            state.retrieved_total[task["product"]] += take
            if info["count"] == 0:
                info["product"] = None
            state.event_log.appendleft(f"РТС-{r.id} ({r.product}) забрал {task['product']}×{take} с полки {shelf}")
        else:
            state.event_log.appendleft(f"РТС-{r.id} не нашёл {task['product']} на полке {shelf}")
        state.reserved_pick_shelves.discard(shelf)

        remaining = task["qty"] - (r.carry_qty or 0)
        if remaining > 0:
            next_shelf = _choose_best_pick_shelf(task["product"])
            if next_shelf:
                accesses = shelf_access_cells(next_shelf)
                if accesses:
                    state.reserved_pick_shelves.add(next_shelf)
                    blocked = _get_blocked_cells(exclude_robot=r)
                    access = min(accesses, key=lambda c: manhattan(r.pos, c))
                    route = astar(r.pos, access, blocked=blocked)
                    if route:
                        r.task["shelf"] = next_shelf
                        r.target_shelf = next_shelf
                        r.route = route
                        r.phase = "to_shelf_for_pick"
                        return
            state.event_log.appendleft(
                f"РТС-{r.id}: больше нет полок с {task['product']}, везёт {r.carry_qty} ед. к выходу"
            )

        blocked = _get_blocked_cells(exclude_robot=r)
        r.route = astar(r.pos, get_exit_cell(), blocked=blocked)
        if not r.route:
            state.event_log.appendleft(f"⚠ {r.name}: нет пути к выходу!")
            r.carry = None
            r.carry_qty = 0
            r.task = None
            r.phase = "idle"
            return
        r.final_route_after_exit = astar(get_exit_cell(), r.home, blocked=blocked)
        if not r.final_route_after_exit:
            state.event_log.appendleft(f"⚠ {r.name}: нет пути домой от выхода!")
        r.phase = "to_exit"
    elif r.phase == "to_exit":
        qty = r.carry_qty or 0
        if r.carry is not None and qty > 0:
            state.event_log.appendleft(f"РТС-{r.id} ({r.product}) доставил {r.carry}×{qty} к выходу")
            state.delivered_total[r.carry] = state.delivered_total.get(r.carry, 0) + qty
            r.delivery_anim_ticks = 25
        r.carry = None
        r.carry_qty = 0
        r.task = None
        r.target_shelf = None
        r.final_route_after_exit = []
        if state.robot_task_queues[r.product]:
            blocked = _get_blocked_cells(exclude_robot=r)
            shelf = None
            for s, info in state.shelf_state.items():
                if s not in state.reserved_pick_shelves and info["product"] == r.product and info["count"] > 0:
                    shelf = s
                    break
            if shelf:
                accesses = shelf_access_cells(shelf)
                if accesses:
                    state.reserved_pick_shelves.add(shelf)
                    access = min(accesses, key=lambda c: manhattan(r.pos, c))
                    route = astar(r.pos, access, blocked=blocked)
                    if route:
                        q = state.robot_task_queues[r.product]
                        qty2 = 1
                        while qty2 < r.capacity and len(q) > 0 and q[0]["type"] == "retrieve" and q[0]["product"] == r.product:
                            q.popleft()
                            qty2 += 1
                        r.task = {"type": "retrieve", "product": r.product, "qty": qty2, "shelf": shelf}
                        r.phase = "to_shelf_for_pick"
                        r.route = route
                        r.target_shelf = shelf
                    else:
                        state.reserved_pick_shelves.discard(shelf)
                        r.phase = "idle"
                        r.route = astar(r.pos, r.home, blocked=blocked)
                        if not r.route:
                            state.event_log.appendleft(f"⚠ {r.name}: нет пути домой от {r.pos}!")
                else:
                    state.reserved_pick_shelves.discard(shelf)
                    r.phase = "idle"
                    r.route = astar(r.pos, r.home, blocked=blocked)
                    if not r.route:
                        state.event_log.appendleft(f"⚠ {r.name}: нет пути домой от {r.pos}!")
            else:
                r.phase = "idle"
                r.route = astar(r.pos, r.home, blocked=blocked)
                if not r.route:
                    state.event_log.appendleft(f"⚠ {r.name}: нет пути домой от {r.pos}!")
        else:
            r.phase = "idle"
            blocked = _get_blocked_cells(exclude_robot=r)
            r.route = astar(r.pos, r.home, blocked=blocked)
            if not r.route:
                state.event_log.appendleft(f"⚠ {r.name}: нет пути домой от {r.pos}!")


def _handle_rebalance_phase(r, task):
    state = get_state()
    if r.phase == "rebalance_pick":
        shelf = r.target_shelf
        if shelf is None:
            r.phase = "idle"
            return
        info = state.shelf_state[shelf]
        if info["count"] > 0 and info["product"] == r.product:
            r.carry = info["product"]
            r.pickup_anim_ticks = 15
            info["count"] -= 1
            if info["count"] == 0:
                info["product"] = None
            state.event_log.appendleft(f"РТС-{r.id} взял {r.carry} для ребалансировки")
        target_shelf = task["to_shelf"]
        accesses = shelf_access_cells(target_shelf)
        if accesses:
            blocked = _get_blocked_cells(exclude_robot=r)
            access = min(accesses, key=lambda c: manhattan(r.pos, c))
            r.route = astar(r.pos, access, blocked=blocked)
            r.target_shelf = target_shelf
            r.phase = "rebalance_put"
        else:
            r.carry = None
            r.task = None
            r.phase = "idle"
    elif r.phase == "rebalance_put":
        if r.carry is not None:
            target_shelf = r.target_shelf
            if target_shelf is None:
                r.carry = None
                r.task = None
                r.phase = "idle"
                return
            info = state.shelf_state[target_shelf]
            cap = get_shelf_max_capacity(target_shelf)
            if info["count"] == 0:
                info["product"] = r.carry
                info["count"] = 1
            elif info["product"] == r.carry and info["count"] < cap:
                info["count"] += 1
            state.event_log.appendleft(f"РТС-{r.id} разместил {r.carry} на {target_shelf} (ребалансировка)")
        r.carry = None
        r.task = None
        r.target_shelf = None
        r.phase = "idle"


def advance_robot_phases() -> None:
    for r in robots:
        if r.is_moving():
            continue
        if r.route:
            continue
        if r.wait_ticks > 0:
            continue
        if r.task is None:
            if r.phase in ("to_home", "return_home"):
                r.phase = "idle"
            continue
        task = r.task
        if task["type"] == "putaway":
            _handle_putaway_phase(r, task)
        elif task["type"] == "retrieve":
            _handle_retrieve_phase(r, task)
        elif task["type"] == "rebalance":
            _handle_rebalance_phase(r, task)


def check_stuck_robots() -> None:
    for robot in robots:
        if robot.check_stuck():
            state = get_state()
            state.event_log.appendleft(f"ВНИМАНИЕ: РТС-{robot.id} застрял! Выполняется сброс...")
            robot.reset()
            state.event_log.appendleft(f"РТС-{robot.id} сброшен на домашнюю позицию")
