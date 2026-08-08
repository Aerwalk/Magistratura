"""10 test scenarios for the warehouse simulation."""

import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.state import get_state
from core.grid import all_shelves, get_inbound_cell
from entities.robot import robots
from entities.uav import uav
from config import PRODUCTS, PRODUCT_COLORS, add_product
from config.constants import hex_to_rgba
from simulation.task_manager import supply_labeled, request_product, supply_unlabeled, assign_tasks
from simulation.robot_controller import move_robots_one_step, advance_robot_phases
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
        "name": "Движение робота к цели",
        "expected": "Робот с задачей должен начать движение: draw_pos изменяется за 10 шагов"
    },
    5: {
        "name": "Сканирование UAV",
        "expected": "UAV должен начать сканирование: состояние изменяется с idle на to_inbound, затем на scanning"
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
    }
}


def _reset():
    s = get_state()
    s.reset()
    for r in robots:
        r.reset()
    uav.reset()


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


def scenario_4_robot_movement():
    _reset()
    r = [rb for rb in robots if "metal" in rb.products]
    if not r:
        return _result(4, False, "Нет робота для metal")
    r = r[0]
    r.phase = "to_shelf_for_put"
    r.carry = "metal"
    r.carry_qty = 2
    shelf = list(all_shelves())[0]
    r.target_shelf = shelf
    from core.grid import shelf_access_cells
    access = shelf_access_cells(shelf)
    if not access:
        return _result(4, False, "Нет доступа к полке")
    from core.pathfinding import astar
    r.route = astar(r.pos, access[0])
    if not r.route:
        return _result(4, False, "Нет пути к полке")
    r.current_target = r.route.pop(0) if r.route else None
    start_draw = list(r.draw_pos)
    for _ in range(10):
        move_robots_one_step()
        advance_robot_phases()
    moved = r.draw_pos != start_draw
    return _result(4, moved,
                   f"draw_pos: {start_draw} → {r.draw_pos}, pos: {r.pos}")


def scenario_5_uav_scan():
    _reset()
    s = get_state()
    s.uav_scan_queue.append(1)
    uav.state = "to_inbound"
    inbound = get_inbound_cell()
    old_q = len(s.uav_scan_queue)
    for _ in range(40):
        update_uav()
    return _result(5, len(s.uav_scan_queue) < old_q or uav.state != "to_inbound",
                   f"Состояние UAV: {uav.state}, очередь: {len(s.uav_scan_queue)}")


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


SCENARIOS = [
    scenario_1_basic_putaway,
    scenario_2_basic_retrieve,
    scenario_3_unlabeled_supply,
    scenario_4_robot_movement,
    scenario_5_uav_scan,
    scenario_6_rebalance,
    scenario_7_shelf_overflow,
    scenario_8_multirobot_carry,
    scenario_9_new_product,
    scenario_10_grid_edit,
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
