"""Robot controller module."""

import numpy as np

from src.config import SHELF_CAPACITY, EXIT_CELL, INBOUND_PICK_CELL
from src.core.state import get_state, count_on_shelves, product_hotness
from src.core.grid import shelf_access_cells, manhattan, all_shelves, shelf_distance_score
from src.core.pathfinding import astar
from src.entities import robots
from src.entities.base import move_agent_towards_2d, close2


def _start_robot_next_segment(robot) -> None:
    """Start next segment of robot route."""
    if robot.current_target is None and robot.route:
        robot.current_target = robot.route.pop(0)


def _update_single_robot_motion(robot) -> None:
    """Update motion for single robot."""
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
    """Move all robots one step."""
    for robot in robots:
        _update_single_robot_motion(robot)


def _get_blocked_cells(exclude_robot=None) -> set:
    """Get cells blocked by other robots."""
    blocked = set()
    for r in robots:
        if r != exclude_robot and r.current_target is None:
            blocked.add(r.pos)
    return blocked


def _choose_best_put_shelf(product: str):
    """Choose best shelf for putting away a product."""
    state = get_state()
    candidates = []
    for shelf, info in state.shelf_state.items():
        if shelf in state.reserved_put_shelves:
            continue
        if info["count"] == 0 or (info["product"] == product and info["count"] < SHELF_CAPACITY):
            candidates.append(shelf)

    if not candidates:
        return None

    def score(shelf):
        info = state.shelf_state[shelf]
        hotness = 1 + state.demand.get(product, 0)
        same_partial_bonus = -10 if info["product"] == product and 0 < info["count"] < SHELF_CAPACITY else 0
        return shelf_distance_score(shelf) / hotness + same_partial_bonus

    return min(candidates, key=score)


def _handle_putaway_phase(r, task):
    """Handle putaway task phase."""
    state = get_state()
    
    if r.phase == "to_pickup_zone":
        r.carry = task["product"]
        r.pickup_anim_ticks = 15

        shelf = _choose_best_put_shelf(r.carry)
        if shelf is None:
            r.carry = None
            state.robot_task_queues[r.product].appendleft(
                {"type": "putaway", "product": r.product, "source": task.get("source", "labeled")}
            )
            r.task = None
            r.phase = "idle"
            state.event_log.appendleft(f"Нет свободной полки для {r.product}, задача возвращена в очередь")
            return

        accesses = shelf_access_cells(shelf)
        if not accesses:
            r.carry = None
            state.robot_task_queues[r.product].appendleft(
                {"type": "putaway", "product": r.product, "source": task.get("source", "labeled")}
            )
            r.task = None
            r.phase = "idle"
            state.event_log.appendleft(f"Нет прохода к полке {shelf} для {r.product}")
            return

        state.reserved_put_shelves.add(shelf)
        blocked = _get_blocked_cells(exclude_robot=r)
        access = min(accesses, key=lambda c: manhattan(r.pos, c))
        r.route = astar(r.pos, access, blocked=blocked)
        r.target_shelf = shelf
        r.phase = "to_shelf_for_put"

    elif r.phase == "to_shelf_for_put":
        shelf = r.target_shelf
        if shelf is None:
            r.phase = "idle"
            return
        info = state.shelf_state[shelf]

        if info["count"] == 0 or (info["product"] == r.carry and info["count"] < SHELF_CAPACITY):
            if info["count"] == 0:
                info["product"] = r.carry
            info["count"] += 1
            state.event_log.appendleft(
                f"РТС-{r.id} ({r.product}) разместил {r.carry} на полке {shelf} [{info['count']}/{SHELF_CAPACITY}]"
            )
        else:
            state.robot_task_queues[r.product].appendleft(
                {"type": "putaway", "product": r.product, "source": task.get("source", "labeled")}
            )
            state.event_log.appendleft(f"Полка {shelf} недоступна для {r.product}, задача возвращена в очередь")

        state.reserved_put_shelves.discard(shelf)
        r.carry = None
        r.task = None
        r.target_shelf = None

        if state.robot_task_queues[r.product]:
            blocked = _get_blocked_cells(exclude_robot=r)
            route = astar(r.pos, INBOUND_PICK_CELL, blocked=blocked)
            if route:
                r.task = state.robot_task_queues[r.product].popleft()
                r.phase = "to_pickup_zone"
                r.route = route
            else:
                r.phase = "idle"
        else:
            r.phase = "idle"


def _handle_retrieve_phase(r, task):
    """Handle retrieve task phase."""
    state = get_state()
    
    if r.phase == "to_shelf_for_pick":
        shelf = task["shelf"]
        info = state.shelf_state[shelf]

        if info["product"] == task["product"] and info["count"] > 0:
            info["count"] -= 1
            r.carry = task["product"]
            r.pickup_anim_ticks = 15
            state.stock_total[task["product"]] -= 1

            if info["count"] == 0:
                info["product"] = None

            state.event_log.appendleft(f"РТС-{r.id} ({r.product}) забрал {task['product']} с полки {shelf}")
        else:
            state.event_log.appendleft(f"РТС-{r.id} не нашёл {task['product']} на полке {shelf}")

        state.reserved_pick_shelves.discard(shelf)
        blocked = _get_blocked_cells(exclude_robot=r)
        r.route = astar(r.pos, EXIT_CELL, blocked=blocked)
        r.final_route_after_exit = astar(EXIT_CELL, r.home, blocked=blocked)
        r.phase = "to_exit"

    elif r.phase == "to_exit":
        if r.carry is not None:
            state.event_log.appendleft(f"РТС-{r.id} ({r.product}) доставил {r.carry} к выходу")
            state.delivered_total[r.carry] += 1
            r.delivery_anim_ticks = 25

        r.carry = None
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
                        r.task = state.robot_task_queues[r.product].popleft()
                        r.task["shelf"] = shelf
                        r.phase = "to_shelf_for_pick"
                        r.route = route
                        r.next_route_after_phase = []
                        r.final_route_after_exit = []
                        r.target_shelf = shelf
                    else:
                        state.reserved_pick_shelves.discard(shelf)
                        r.phase = "idle"
                        r.route = astar(r.pos, r.home, blocked=blocked)
                else:
                    state.reserved_pick_shelves.discard(shelf)
                    r.phase = "idle"
                    r.route = astar(r.pos, r.home, blocked=blocked)
            else:
                r.phase = "idle"
                r.route = astar(r.pos, r.home, blocked=blocked)
        else:
            r.phase = "idle"
            blocked = _get_blocked_cells(exclude_robot=r)
            r.route = astar(r.pos, r.home, blocked=blocked)


def _handle_rebalance_phase(r, task):
    """Handle rebalance task phase."""
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

            if info["count"] == 0:
                info["product"] = r.carry
                info["count"] = 1
            elif info["product"] == r.carry and info["count"] < SHELF_CAPACITY:
                info["count"] += 1

            state.event_log.appendleft(f"РТС-{r.id} разместил {r.carry} на {target_shelf} (ребалансировка)")

        r.carry = None
        r.task = None
        r.target_shelf = None
        r.phase = "idle"


def advance_robot_phases() -> None:
    """Advance robot task phases."""
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
    """Check and reset stuck robots."""
    for robot in robots:
        if robot.check_stuck():
            state = get_state()
            state.event_log.appendleft(f"ВНИМАНИЕ: РТС-{robot.id} застрял! Выполняется сброс...")
            robot.reset()
            state.event_log.appendleft(f"РТС-{robot.id} сброшен на домашнюю позицию")
