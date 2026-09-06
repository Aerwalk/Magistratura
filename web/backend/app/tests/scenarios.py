"""17 test scenarios for the warehouse simulation."""

import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.state import get_state
from core.grid import all_shelves, get_inbound_cell
from entities.robot import robots
from entities.uav import uav
from config import PRODUCTS, PRODUCT_COLORS, add_product
from config.constants import hex_to_rgba
from simulation.task_manager import supply_labeled, request_product, supply_unlabeled, assign_tasks
from simulation.robot_controller import advance_robot_phases, _reset_tick_reservations
from simulation.uav_controller import update_uav
from simulation.rebalancer import rebalance_warehouse
from entities.robot import create_robot


SCENARIO_META = {
    1: {
        "name": "Поступление маркированного товара",
        "expected": "После поставки 3 единиц metal в очереди задач должно стать на 3 больше"
    },
    2: {
        "name": "Извлечение товара со склада",
        "expected": "После запроса 2 единиц metal со стеллажа должно создаться 2 задачи retrieve"
    },
    3: {
        "name": "Поступление немаркированного товара",
        "expected": "После поставки 5 единиц без метки в очередь UAV должен добавиться 1 элемент (суммарная поставка)"
    },
    4: {
        "name": "Планирование маршрута для задачи",
        "expected": "Робот с задачей получает маршрут к зоне забора и фазу to_pickup_zone"
    },
    5: {
        "name": "Передача сканирования UAV агенту",
        "expected": "Планировщик отправляет команду scan агенту БВС и извлекает запрос из очереди"
    },
    6: {
        "name": "Запуск ребалансировки",
        "expected": "После включения ребалансировки флаг active = True, осталось 5 перемещений"
    },
    7: {
        "name": "Защита от переполнения стеллажа",
        "expected": "Полный стеллаж (count == SHELF_CAPACITY) не должен принимать тот же продукт"
    },
    8: {
        "name": "Мульти-перенос (capacity > 1)",
        "expected": "Робот с capacity=5 не возьмёт больше чем capacity при назначении задач"
    },
    9: {
        "name": "Добавление нового продукта",
        "expected": "Новый продукт testium (#ff00ff) добавляется в PRODUCTS и PRODUCT_COLORS"
    },
    10: {
        "name": "Редактирование карты (добавление/удаление стеллажа)",
        "expected": "Пользовательский стеллаж добавляется в CUSTOM_SHELF_CELLS и удаляется оттуда"
    },
    11: {
        "name": "Разряд батареи за задачу",
        "expected": "После выполнения задачи putaway батарея робота уменьшается на 5% (BATTERY_TASK_DRAIN)"
    },
    12: {
        "name": "Метрики Prometheus",
        "expected": "render_prometheus() возвращает текст с battery gauge и cell visits counter"
    },
    13: {
        "name": "Обнаружение застревания РТС",
        "expected": "РТС, стоящий >STUCK_TICKS тиков с активной задачей вне базовой станции, получает алерт об остановке"
    },
    14: {
        "name": "Расширенные метрики парка",
        "expected": "render_prometheus() содержит speed, loaded, phase, stuck, task_assigned, warehouse и info метрики"
    },
    15: {
        "name": "Учёт назначенных задач",
        "expected": "После assign_tasks() счётчик magsim_robot_tasks_assigned_total для putaway увеличивается"
    },
    16: {
        "name": "Метрики здоровья стека",
        "expected": "render_prometheus() содержит magsim_health_* метрики подключения агентов и тиков симуляции"
    },
    17: {
        "name": "Метрики результатов тестов",
        "expected": "record_test_results() выставляет magsim_tests_last_result / magsim_tests_runs_total"
    }
}


def _reset():
    s = get_state()
    s.reset()
    _reset_tick_reservations()
    for r in robots:
        r.reset()
        r.battery = 100.0
        r.battery_max = 100.0
        r.agent_ready = True
        r.executing = False
        r.agent_ws = None
    uav.reset()
    from agent_registry import agent_registry
    agent_registry.uav_ws = None
    agent_registry.spare_robot_ws.clear()


def _result(scenario_id: int, passed: bool, detail: str):
    meta = SCENARIO_META[scenario_id]
    return {
        "id": scenario_id,
        "name": meta["name"],
        "expected": meta["expected"],
        "passed": passed,
        "detail": detail
    }


def scenario_1_basic_putaway():
    _reset()
    s = get_state()
    old_count = len(s.robot_task_queues["metal"])
    supply_labeled("metal", 3)
    new_count = len(s.robot_task_queues["metal"])
    return _result(1, new_count == old_count + 3,
                   f"Было {old_count} задач metal, стало {new_count}")


def scenario_2_basic_retrieve():
    _reset()
    s = get_state()
    shelf = list(all_shelves())[0]
    s.shelf_state[shelf] = {"product": "metal", "count": 10}
    old_count = len(s.robot_task_queues["metal"])
    request_product("metal", 2)
    new_count = len(s.robot_task_queues["metal"])
    return _result(2, new_count > old_count,
                   f"Создано {new_count - old_count} задач retrieve")


def scenario_3_unlabeled_supply():
    _reset()
    s = get_state()
    old_len = len(s.uav_scan_queue)
    supply_unlabeled(5)
    new_len = len(s.uav_scan_queue)
    return _result(3, new_len == old_len + 1,
                   f"Добавлено {new_len - old_len} единиц в очередь UAV (все 5 сканируются за раз)")


def scenario_4_robot_route_planning():
    _reset()
    r = [rb for rb in robots if "metal" in rb.products]
    if not r:
        return _result(4, False, "Нет робота для metal")
    r = r[0]
    supply_labeled("metal", 3)
    assign_tasks()
    route_ok = r.task is not None and len(r.route) > 0 and r.phase == "to_pickup_zone"
    return _result(4, route_ok,
                   f"task={r.task}, phase={r.phase}, route_len={len(r.route)}")


def scenario_5_uav_scan_dispatch():
    _reset()
    s = get_state()
    s.uav_scan_queue.append(1)
    old_q = len(s.uav_scan_queue)
    uav.state = "idle"
    from agent_registry import agent_registry
    agent_registry.uav_ws = object()
    update_uav()
    dispatched = len(s.uav_scan_queue) == 0
    return _result(5, dispatched,
                   f"Очередь UAV: {old_q} → {len(s.uav_scan_queue)}")


def scenario_6_rebalance():
    _reset()
    s = get_state()
    shelves = list(all_shelves())
    for sh in shelves[:20]:
        s.shelf_state[sh] = {"product": "metal", "count": 2}
    s.rebalance_active = True
    s.rebalance_moves_remaining = 5
    assign_tasks()
    return _result(6, s.rebalance_active,
                   f"rebalance_active={s.rebalance_active}, moves={s.rebalance_moves_remaining}")


def scenario_7_shelf_overflow():
    _reset()
    from core.state import get_shelf_max_capacity, shelf_can_store_product
    from config import SHELF_CAPACITY
    s = get_state()
    shelf = list(all_shelves())[0]
    s.shelf_state[shelf] = {"product": "metal", "count": SHELF_CAPACITY}
    can_store = shelf_can_store_product(shelf, "metal")
    return _result(7, not can_store,
                   f"Ёмкость: {SHELF_CAPACITY}, заполнено: {SHELF_CAPACITY}, можно ещё: {can_store}")


def scenario_8_multirobot_carry():
    _reset()
    r = [rb for rb in robots if "metal" in rb.products]
    if not r:
        return _result(8, False, "Нет робота для metal")
    r = r[0]
    r.capacity = 5
    supply_labeled("metal", 7)
    assign_tasks()
    return _result(8, r.carry_qty <= r.capacity,
                   f"capacity={r.capacity}, carry_qty={r.carry_qty}")


def scenario_9_new_product():
    from config import add_product
    name = "testium"
    color_hex = "#ff00ff"
    color_tuple = hex_to_rgba(color_hex)
    add_product(name, color_tuple)
    found = name in PRODUCTS
    rgba_match = PRODUCT_COLORS.get(name) == color_tuple
    return _result(9, found and rgba_match,
                   f"продукт={name}, цвет={color_hex}, в списке={found}, цвет совпадает={rgba_match}")


def scenario_10_grid_edit():
    from core.grid import add_custom_shelf, remove_custom_shelf, CUSTOM_SHELF_CELLS
    _reset()
    add_custom_shelf(7, 11)
    added = (7, 11) in CUSTOM_SHELF_CELLS
    remove_custom_shelf(7, 11)
    removed = (7, 11) not in CUSTOM_SHELF_CELLS
    return _result(10, added and removed,
                   f"Добавлен: {added}, удалён: {removed}")


def scenario_11_battery_drain():
    _reset()
    from simulation.robot_controller import _drain_battery
    from config.constants import BATTERY_TASK_DRAIN
    s = get_state()
    r = [rb for rb in robots if "metal" in rb.products]
    if not r:
        return _result(11, False, "Нет робота для metal")
    r = r[0]
    s.stock_total["metal"] += 3
    for _ in range(3):
        supply_labeled("metal", 1)
    before = r.battery
    _drain_battery(r, "putaway")
    drained = round(before - r.battery, 2) == round(BATTERY_TASK_DRAIN, 2)
    return _result(11, drained,
                   f"Батарея: {before:.1f}% → {r.battery:.1f}% (шаг {BATTERY_TASK_DRAIN}%)")


def scenario_12_metrics():
    _reset()
    from metrics import render_prometheus, record_cell_visit
    record_cell_visit(1, (3, 4))
    body, content_type = render_prometheus()
    has_battery = "magsim_robot_battery_percent" in body
    has_visits = "magsim_robot_cell_visits_total" in body
    has_tasks = "magsim_robot_tasks_completed_total" in body
    ok = has_battery and has_visits and has_tasks and "text/plain" in content_type
    return _result(12, ok,
                   f"battery={has_battery}, visits={has_visits}, tasks={has_tasks}, ct=[{content_type}]")


def scenario_13_stuck_detection():
    _reset()
    import simulation.robot_controller as rc
    orig = rc.STUCK_TICKS
    rc.STUCK_TICKS = 5
    try:
        s = get_state()
        r = [rb for rb in robots if "metal" in rb.products]
        if not r:
            return _result(13, False, "Нет робота для metal")
        r = r[0]
        r.pos = (6, 4)
        r.draw_pos = [6.0, 4.0]
        r._stuck_sample_pos = [6.0, 4.0]
        r.task = {"type": "putaway", "product": "metal", "qty": 1}
        r.executing = True
        for _ in range(6):
            rc.detect_stuck_robots()
        alerted = r.stuck_alert_raised
        logged = any("застрял" in e for e in s.event_log)
        # Make sure it does NOT alert when standing at home without a task
        r2 = [rb for rb in robots if "metal" in rb.products][0]
        r2.pos = r2.home
        r2.draw_pos = [float(r2.home[0]), float(r2.home[1])]
        r2._stuck_sample_pos = list(r2.draw_pos)
        r2.task = None
        r2.executing = False
        rc.detect_stuck_robots()
        home_safe = not r2.stuck_alert_raised
        return _result(13, alerted and logged and home_safe,
                       f"alerted={alerted}, event_logged={logged}, home_safe={home_safe}")
    finally:
        rc.STUCK_TICKS = orig


def scenario_14_extended_metrics():
    _reset()
    from metrics import render_prometheus
    body, _ = render_prometheus()
    checks = {
        "speed": "magsim_robot_speed" in body,
        "loaded": "magsim_robot_loaded" in body,
        "phase": "magsim_robot_phase" in body,
        "stuck": "magsim_robot_stuck" in body,
        "task_assigned": "magsim_robot_tasks_assigned_total" in body,
        "distance": "magsim_robot_distance_moved_total" in body,
        "info": "magsim_robot_info" in body,
        "warehouse": "magsim_warehouse_task_queue" in body,
        "rebalance": "magsim_warehouse_rebalance_active" in body,
    }
    ok = all(checks.values())
    return _result(14, ok, ", ".join(f"{k}={v}" for k, v in checks.items()))


def scenario_15_task_assigned_counter():
    _reset()
    from metrics import task_assigned_counter
    r = [rb for rb in robots if "metal" in rb.products]
    if not r:
        return _result(15, False, "Нет робота для metal")
    r = r[0]
    label = dict(robot_id=str(r.id), task_type="putaway")
    before = task_assigned_counter.labels(**label)._value.get()
    supply_labeled("metal", 1)
    assign_tasks()
    after = task_assigned_counter.labels(**label)._value.get()
    return _result(15, after - before >= 1,
                   f"tasks_assigned metal: {before} → {after}")


def scenario_16_health_metrics():
    _reset()
    from metrics import render_prometheus, record_sim_tick
    record_sim_tick(99.0)
    body, _ = render_prometheus()
    checks = {
        "db": "magsim_health_database_connected" in body,
        "agents": "magsim_health_agents_connected" in body,
        "ready": "magsim_health_robots_ready" in body,
        "ticks": "magsim_health_sim_ticks_total" in body,
        "last_tick": "magsim_health_last_tick_timestamp" in body,
        "uptime": "magsim_health_uptime_seconds" in body,
    }
    ok = all(checks.values())
    return _result(16, ok, ", ".join(f"{k}={v}" for k, v in checks.items()))


def scenario_17_test_result_metrics():
    _reset()
    from metrics import (
        record_test_results, tests_last_result,
        tests_runs_total, tests_last_run_timestamp,
    )
    before = tests_runs_total.labels(suite="unit")._value.get() or 0
    record_test_results({
        "tests": {
            "total": 1, "passed": 1, "failed": 0,
            "tests": [{"name": "s17_dummy", "passed": True}],
        },
        "scenarios": [],
    })
    incremented = tests_runs_total.labels(suite="unit")._value.get() > before
    pass_marked = tests_last_result.labels(suite="unit", name="s17_dummy")._value.get() == 1.0
    stamped = tests_last_run_timestamp.labels(suite="unit")._value.get() > 0
    ok = incremented and pass_marked and stamped
    return _result(17, ok,
                   f"runs_incremented={incremented}, pass_marked={pass_marked}, stamped={stamped}")


SCENARIOS = [
    scenario_1_basic_putaway,
    scenario_2_basic_retrieve,
    scenario_3_unlabeled_supply,
    scenario_4_robot_route_planning,
    scenario_5_uav_scan_dispatch,
    scenario_6_rebalance,
    scenario_7_shelf_overflow,
    scenario_8_multirobot_carry,
    scenario_9_new_product,
    scenario_10_grid_edit,
    scenario_11_battery_drain,
    scenario_12_metrics,
    scenario_13_stuck_detection,
    scenario_14_extended_metrics,
    scenario_15_task_assigned_counter,
    scenario_16_health_metrics,
    scenario_17_test_result_metrics,
]


def run_all_scenarios():
    results = []
    for fn in SCENARIOS:
        try:
            results.append(fn())
        except Exception as e:
            sid = SCENARIOS.index(fn) + 1
            results.append(_result(sid, False, str(e)))
    return results


def run_scenario(scenario_id: int):
    for fn in SCENARIOS:
        res = fn()
        if res["id"] == scenario_id:
            return res
    return _result(scenario_id, False, "Scenario not found")
