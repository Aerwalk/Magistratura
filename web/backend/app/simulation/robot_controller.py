from datetime import datetime, timezone

from config import BATTERY_LOW, BATTERY_CHARGE_THRESHOLD, STUCK_TICKS, TICK_MS
from config.constants import BATTERY_TASK_DRAIN
from core.state import get_state, get_shelf_max_capacity, get_shelf_allowed_products
from core.grid import (shelf_access_cells, manhattan, all_shelves, shelf_distance_score,
                       get_exit_cell, get_inbound_pick_cell, AISLE_CELLS)
from core.pathfinding import astar
from entities import robots
from agent_registry import agent_registry, fire_and_forget
from db import push_log
from metrics import record_cell_visit, record_task_completed, record_task_assigned, record_stuck_event
import obs


def _drain_battery(robot, task_type: str) -> None:
    robot.battery = max(0.0, robot.battery - BATTERY_TASK_DRAIN)
    record_task_completed(robot.id, task_type)


def detect_stuck_robots() -> None:
    """Raise an alert when a robot with an active task/route has not changed its
    position for >STUCK_SECONDS and is not standing at its home station."""
    state = get_state()
    for r in robots:
        if not r.agent_ready or r.phase == "charging":
            continue
        active = bool(r.route) or r.current_target is not None or r.task is not None or r.executing
        if not active:
            r.stationary_ticks = 0
            r._stuck_sample_pos = list(r.draw_pos)
            r.stuck_alert_raised = False
            r.stuck_since = None
            continue
        sample = list(r.draw_pos)
        moved = sample != r._stuck_sample_pos
        r._stuck_sample_pos = sample
        if moved:
            r.stationary_ticks = 0
            if r.stuck_alert_raised:
                r.stuck_alert_raised = False
                r.stuck_since = None
                state.event_log.appendleft(f"ℹ РТС-{r.id} снова в движении, алерт снят")
            continue
        r.stationary_ticks += 1
        if r.stationary_ticks > STUCK_TICKS and not r.stuck_alert_raised:
            if r.pos == r.home and r.task is None:
                continue
            r.stuck_alert_raised = True
            r.stuck_since = _now()
            secs = round(r.stationary_ticks * TICK_MS / 1000.0, 1)
            with obs.span("robot.stuck", robot_id=r.id, seconds=secs,
                          pos=list(r.pos), phase=r.phase):
                state.event_log.appendleft(
                    f"🚨 РТС-{r.id} застрял: стоит {secs:.0f} с на точке {r.pos}! (не базовая станция)"
                )
                push_log(r.id, "warning", "robot_stuck",
                         {"pos": list(r.pos), "seconds": secs, "phase": r.phase})
                record_stuck_event(r)
                # Auto-recovery: cancel the current route and stop the agent so the
                # next assign_tasks() pass can plan a fresh route.
                r.route = []
                r.current_target = None
                r.executing = False
                fire_and_forget(lambda: agent_registry.send_robot(r.id, {"cmd": "stop"}))


def _now() -> datetime:
    return datetime.now(timezone.utc)


_tick_reserved = set()


def _reset_tick_reservations() -> None:
    _tick_reserved.clear()


def _reserve_route(route) -> None:
    if route:
        _tick_reserved.add(tuple(route[0]))
        _tick_reserved.add(tuple(route[-1]))


def _start_charging(robot) -> None:
    with obs.span("robot.charging_start", robot_id=robot.id,
                  battery=round(robot.battery, 1), battery_max=round(robot.battery_max, 1)):
        robot.phase = "charging"
        robot.charging_ticks = 0
        robot.battery_at_charge_start = robot.battery
        robot.charging_start_ts = _now()
        push_log(robot.id, "info", "charging_start", {"battery": round(robot.battery, 1)})
        fire_and_forget(lambda: agent_registry.send_robot(robot.id, {"cmd": "start_charging"}))


def _get_blocked_cells(exclude_robot=None) -> set:
    blocked = set(_tick_reserved)
    for r in robots:
        if r == exclude_robot:
            continue
        blocked.add(r.pos)
        if r.current_target is not None:
            blocked.add(tuple(r.current_target))
    return blocked


def _route_to_shelf(robot, shelf, blocked):
    accesses = shelf_access_cells(shelf)
    if not accesses:
        return None
    best = None
    for access in accesses:
        route = astar(robot.pos, access, blocked=blocked)
        if route and (best is None or len(route) < len(best)):
            best = route
    return best


def _route_to_pickup_zone(robot, blocked):
    """Route to the inbound pick cell. If that cell is occupied by (or targeted
    by) another robot, route to the nearest free neighbouring wait cell instead
    so two robots never meet inside the pick zone."""
    pickup = get_inbound_pick_cell()
    if pickup not in blocked:
        return astar(robot.pos, pickup, blocked=blocked)
    wait_cells = []
    for nx, ny in ((pickup[0] - 1, pickup[1]), (pickup[0] + 1, pickup[1]),
                   (pickup[0], pickup[1] - 1), (pickup[0], pickup[1] + 1)):
        if (nx, ny) in AISLE_CELLS and (nx, ny) not in blocked:
            wait_cells.append((nx, ny))
    best = None
    for wc in wait_cells:
        route = astar(robot.pos, wc, blocked=blocked)
        if route and (best is None or len(route) < len(best)):
            best = route
    return best


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


def _start_putaway_leg(r, task) -> bool:
    """Pick a shelf for r.carry and start moving there. Returns False when the
    route is temporarily blocked so the caller can retry instead of losing goods."""
    state = get_state()
    shelf = _choose_best_put_shelf(r.carry)
    if shelf is None:
        r.stuck_ticks += 1
        if r.stuck_ticks == 1:
            state.event_log.appendleft(f"⚠ {r.name}: нет свободной полки для {r.carry}, ждёт...")
        return False
    accesses = shelf_access_cells(shelf)
    if not accesses:
        state.reserved_put_shelves.add(shelf)
        r.stuck_ticks += 1
        if r.stuck_ticks == 1:
            state.event_log.appendleft(f"⚠ {r.name}: полка {shelf} недоступна для прохода, пропущена")
        return False
    state.reserved_put_shelves.add(shelf)
    blocked = _get_blocked_cells(exclude_robot=r)
    route = _route_to_shelf(r, shelf, blocked)
    if not route:
        state.reserved_put_shelves.discard(shelf)
        r.stuck_ticks += 1
        if r.stuck_ticks == 1:
            state.event_log.appendleft(f"⚠ {r.name}: нет пути к полке {shelf}, повторная попытка...")
        return False
    r.route = route
    r.target_shelf = shelf
    r.phase = "to_shelf_for_put"
    r.stuck_ticks = 0
    _reserve_route(route)
    return True


def _handle_putaway_phase(r, task):
    state = get_state()
    if r.phase == "to_pickup_zone":
        pickup = get_inbound_pick_cell()
        if r.pos != pickup:
            blocked = _get_blocked_cells(exclude_robot=r)
            if pickup in blocked:
                return
            step = astar(r.pos, pickup, blocked=blocked)
            if step:
                r.route = step
                _reserve_route(step)
            return
        r.carry = task["product"]
        r.carry_qty = task.get("qty", 1)
        r.pickup_anim_ticks = 15
        if not _start_putaway_leg(r, task):
            if r.stuck_ticks > 100:
                state.stock_total[r.carry] = state.stock_total.get(r.carry, 0) + r.carry_qty
                state.event_log.appendleft(
                    f"⚠ {r.name}: не смог доставить {r.carry}×{r.carry_qty} на полку, возвращено на склад"
                )
                r.carry = None
                r.carry_qty = 0
                r.task = None
                r.phase = "idle"
                r.stuck_ticks = 0
            return
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
            with obs.span("robot.putaway", robot_id=r.id, product=r.carry,
                          shelf=str(shelf), qty=batch, slot=f"{info['count']}/{cap}"):
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
        if r.carry_qty > 0:
            if not _start_putaway_leg(r, task):
                if r.stuck_ticks > 100:
                    state.event_log.appendleft(
                        f"РТС-{r.id}: не смог разместить оставшиеся {r.carry_qty}×{r.carry}, возвращено на склад"
                    )
                    state.stock_total[r.carry] = state.stock_total.get(r.carry, 0) + r.carry_qty
                    r.carry_qty = 0
                    r.carry = None
                    r.task = None
                    r.phase = "idle"
                    r.stuck_ticks = 0
                return
            return
        r.carry = None
        r.task = None
        r.stuck_ticks = 0
        _drain_battery(r, "putaway")
        if state.robot_task_queues[r.product] and state.robot_task_queues[r.product][0]["type"] == "putaway":
            blocked = _get_blocked_cells(exclude_robot=r)
            route = _route_to_pickup_zone(r, blocked)
            if route:
                r.task = state.robot_task_queues[r.product].popleft()
                r.phase = "to_pickup_zone"
                r.route = route
                record_task_assigned(r.id, "putaway")
                _reserve_route(route)
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
                    route = _route_to_shelf(r, next_shelf, blocked)
                    if route:
                        r.task["shelf"] = next_shelf
                        r.target_shelf = next_shelf
                        r.route = route
                        r.phase = "to_shelf_for_pick"
                        _reserve_route(route)
                        return
                    state.reserved_pick_shelves.discard(next_shelf)
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
        _reserve_route(r.route)
        r.final_route_after_exit = astar(get_exit_cell(), r.home, blocked=blocked)
        if not r.final_route_after_exit:
            state.event_log.appendleft(f"⚠ {r.name}: нет пути домой от выхода!")
        r.phase = "to_exit"
    elif r.phase == "to_exit":
        qty = r.carry_qty or 0
        if r.carry is not None and qty > 0:
            with obs.span("robot.delivered", robot_id=r.id, product=r.carry, qty=qty):
                state.event_log.appendleft(f"РТС-{r.id} ({r.product}) доставил {r.carry}×{qty} к выходу")
                state.delivered_total[r.carry] = state.delivered_total.get(r.carry, 0) + qty
                r.delivery_anim_ticks = 25
                _drain_battery(r, "retrieve")
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
                    route = _route_to_shelf(r, shelf, blocked)
                    if route:
                        q = state.robot_task_queues[r.product]
                        qty2 = 1
                        q.popleft()
                        while qty2 < r.capacity and len(q) > 0 and q[0]["type"] == "retrieve" and q[0]["product"] == r.product:
                            q.popleft()
                            qty2 += 1
                        r.task = {"type": "retrieve", "product": r.product, "qty": qty2, "shelf": shelf}
                        r.phase = "to_shelf_for_pick"
                        r.route = route
                        record_task_assigned(r.id, "retrieve")
                        r.target_shelf = shelf
                        _reserve_route(route)
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
            r.carry = None
            r.task = None
            r.phase = "idle"
            return
        info = state.shelf_state[shelf]
        if r.carry is None and info["count"] > 0 and info["product"] == r.product:
            r.carry = info["product"]
            r.pickup_anim_ticks = 15
            info["count"] -= 1
            if info["count"] == 0:
                info["product"] = None
            state.event_log.appendleft(f"РТС-{r.id} взял {r.carry} для ребалансировки")
        target_shelf = task["to_shelf"]
        accesses = shelf_access_cells(target_shelf)
        if not accesses:
            r.carry = None
            r.task = None
            r.phase = "idle"
            return
        blocked = _get_blocked_cells(exclude_robot=r)
        route = _route_to_shelf(r, target_shelf, blocked)
        if route:
            r.route = route
            r.target_shelf = target_shelf
            r.phase = "rebalance_put"
            r.stuck_ticks = 0
            _reserve_route(route)
        else:
            r.stuck_ticks += 1
            if r.stuck_ticks == 1:
                state.event_log.appendleft(f"⚠ {r.name}: нет пути для ребалансировки, повторная попытка...")
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
        _drain_battery(r, "rebalance")


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


def advance_robot_phases() -> None:
    detect_stuck_robots()
    for r in robots:
        if r.delivery_anim_ticks > 0:
            r.delivery_anim_ticks -= 1
            progress = 1.0 - (r.delivery_anim_ticks / 25.0)
            r.carry_bob = abs(progress - 0.5) * 0.3
        if r.pickup_anim_ticks > 0:
            r.pickup_anim_ticks -= 1
            progress = 1.0 - (r.pickup_anim_ticks / 15.0)
            r.carry_appear_scale = progress
        if not r.agent_ready:
            continue
        if r.is_moving():
            continue
        if r.route:
            continue
        if r.wait_ticks > 0:
            r.wait_ticks -= 1
            continue
        if r.task is None:
            if r.phase in ("to_home", "return_home", "to_home_charge"):
                r.phase = "idle"
            if r.pos == r.home:
                if r.phase != "charging" and r.battery <= BATTERY_CHARGE_THRESHOLD:
                    _start_charging(r)
            elif r.battery < BATTERY_LOW:
                blocked = _get_blocked_cells(exclude_robot=r)
                route = astar(r.pos, r.home, blocked=blocked)
                if route:
                    r.route = route
                    r.phase = "to_home_charge"
                    _reserve_route(route)
            continue
        task = r.task
        if task["type"] == "putaway":
            _handle_putaway_phase(r, task)
        elif task["type"] == "retrieve":
            _handle_retrieve_phase(r, task)
        elif task["type"] == "rebalance":
            _handle_rebalance_phase(r, task)
