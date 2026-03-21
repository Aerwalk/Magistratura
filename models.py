import random
from collections import deque, defaultdict
from PyQt5 import QtGui
import numpy as np
import heapq

PRODUCTS = ["metal", "plastic", "electronics", "wood", "glass"]

PRODUCT_COLORS = {
    "metal": (0.78, 0.78, 0.82, 1.0),
    "plastic": (0.10, 0.55, 0.95, 1.0),
    "electronics": (1.00, 0.55, 0.10, 1.0),
    "wood": (0.55, 0.32, 0.12, 1.0),
    "glass": (0.20, 0.90, 0.90, 1.0),
}

PRODUCT_QCOLORS = {
    "metal": QtGui.QColor(191, 191, 205),
    "plastic": QtGui.QColor(25, 140, 242),
    "electronics": QtGui.QColor(255, 140, 25),
    "wood": QtGui.QColor(140, 81, 31),
    "glass": QtGui.QColor(51, 230, 230),
}

SHELF_CAPACITY = 5
AGENT_SPEED = 0.25
TICK_MS = 50

EXIT_CELL = (0, 5)
INBOUND_CELL = (1, 1)
INBOUND_PICK_CELL = (2, 1)
UAV_HOME_POS = (7, 5, 4.5)

ROBOT_CONFIG = [
    {"product": "metal", "color": (1.0, 0.1, 0.1, 1.0), "home": (14, 1)},
    {"product": "plastic", "color": (0.1, 0.4, 1.0, 1.0), "home": (14, 3)},
    {"product": "electronics", "color": (1.0, 0.5, 0.1, 1.0), "home": (14, 5)},
    {"product": "wood", "color": (0.1, 0.8, 0.3, 1.0), "home": (14, 7)},
    {"product": "glass", "color": (0.8, 0.2, 0.8, 1.0), "home": (14, 9)},
]

HOME_CELLS = [(14, 1), (14, 2), (14, 3), (14, 4), (14, 5), (14, 6), (14, 7), (14, 8), (14, 9)]
SHELF_X = {2, 4, 6, 8, 10, 12}
GRID_W = 16
GRID_H = 12

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


def is_shelf_cell(x, y):
    return x in SHELF_X and y not in {0, 1, 2, 7, 8, 9} and 0 <= y < GRID_H


def all_shelves():
    for x in range(GRID_W):
        for y in range(GRID_H):
            if is_shelf_cell(x, y):
                yield (x, y)


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
            if nxt in blocked:
                continue

            ng = g + 1
            if ng < g_score.get(nxt, 10**9):
                g_score[nxt] = ng
                came_from[nxt] = current
                f = ng + manhattan(nxt, goal)
                heapq.heappush(open_heap, (f, ng, nxt))

    return []


def move_agent_towards_2d(pos, target, speed):
    vec = np.array(target, dtype=float) - np.array(pos, dtype=float)
    dist = np.linalg.norm(vec)
    if dist <= speed or dist == 0:
        return [float(target[0]), float(target[1])]
    vec = vec / dist
    return [pos[0] + vec[0] * speed, pos[1] + vec[1] * speed]


def close2(a, b, eps=0.05):
    return abs(a[0] - b[0]) < eps and abs(a[1] - b[1]) < eps


def close3(a, b, eps=0.15):
    return abs(a[0] - b[0]) < eps and abs(a[1] - b[1]) < eps and abs(a[2] - b[2]) < eps


shelf_state = {shelf: {"product": None, "count": 0} for shelf in all_shelves()}
stock_total = defaultdict(int)
demand = defaultdict(int)

event_log = deque(maxlen=500)
uav_scan_queue = deque()
robot_task_queues = {p: deque() for p in PRODUCTS}

reserved_put_shelves = set()
reserved_pick_shelves = set()


def log(msg):
    event_log.appendleft(msg)


def count_on_shelves(product):
    return sum(info["count"] for info in shelf_state.values() if info["product"] == product)


def distinct_products_on_shelves():
    return [p for p in PRODUCTS if count_on_shelves(p) > 0]


def shelf_can_store_product(shelf, product):
    info = shelf_state[shelf]
    if info["count"] == 0:
        return True
    return info["product"] == product and info["count"] < SHELF_CAPACITY


def product_hotness(product):
    return 1 + demand.get(product, 0)


def choose_best_put_shelf(product):
    candidates = []
    for shelf, info in shelf_state.items():
        if shelf in reserved_put_shelves:
            continue
        if shelf_can_store_product(shelf, product):
            candidates.append(shelf)

    if not candidates:
        return None

    def score(shelf):
        info = shelf_state[shelf]
        same_partial_bonus = -10 if info["product"] == product and 0 < info["count"] < SHELF_CAPACITY else 0
        return shelf_distance_score(shelf) / product_hotness(product) + same_partial_bonus

    return min(candidates, key=score)


def choose_best_pick_shelf(product):
    candidates = []
    for shelf, info in shelf_state.items():
        if shelf in reserved_pick_shelves:
            continue
        if info["product"] == product and info["count"] > 0:
            candidates.append(shelf)

    if not candidates:
        return None

    return min(candidates, key=shelf_distance_score)


def detect_product_ai():
    return random.choice(PRODUCTS)


def get_blocked_cells(exclude_robot=None):
    blocked = set()
    for r in robots:
        if r != exclude_robot and r.current_target is None:
            blocked.add(r.pos)
    return blocked


class Robot:
    def __init__(self, idx, config):
        home = config["home"]
        self.id = idx
        self.product = config["product"]
        self.color = config["color"]
        self.home = home
        self.pos = home
        self.draw_pos = [float(home[0]), float(home[1])]
        self.route = []
        self.current_target = None
        self.task = None
        self.carry = None
        self.phase = "idle"
        self.next_route_after_phase = []
        self.final_route_after_exit = []
        self.target_shelf = None
        self.speed = AGENT_SPEED
        self.delivery_anim_ticks = 0
        self.carry_bob = 0.0
        self.pickup_anim_ticks = 0
        self.carry_appear_scale = 1.0
        self.wait_ticks = 0

    def is_moving(self):
        return self.current_target is not None
    
    def is_active(self):
        return self.current_target is not None or self.wait_ticks > 0 or self.route


class UAV:
    def __init__(self):
        self.pos = [float(UAV_HOME_POS[0]), float(UAV_HOME_POS[1]), float(UAV_HOME_POS[2])]
        self.state = "idle"
        self.scan_ticks = 0


robots = [Robot(idx, cfg) for idx, cfg in enumerate(ROBOT_CONFIG)]
uav = UAV()


def start_robot_next_segment(robot):
    if robot.current_target is None and robot.route:
        robot.current_target = robot.route.pop(0)


def update_single_robot_motion(robot):
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
        start_robot_next_segment(robot)
        
    if robot.current_target is None:
        return

    tx, ty = robot.current_target
    robot.draw_pos = move_agent_towards_2d(robot.draw_pos, (tx, ty), robot.speed)

    if close2(robot.draw_pos, (tx, ty)):
        robot.draw_pos = [float(tx), float(ty)]
        robot.pos = (tx, ty)
        robot.current_target = None
        robot.wait_ticks = 2
        start_robot_next_segment(robot)


def move_robots_one_step():
    for robot in robots:
        update_single_robot_motion(robot)


def supply_labeled(product, qty):
    if qty <= 0:
        return
    for _ in range(qty):
        stock_total[product] += 1
        robot_task_queues[product].append({"type": "putaway", "product": product, "source": "labeled"})
    log(f"Поставка с меткой: {product}, количество {qty}")


def supply_unlabeled(qty):
    if qty <= 0:
        return
    uav_scan_queue.append(qty)
    log(f"Пришла поставка без метки, количество {qty}. БВС начал распознавание.")


def request_product(product, qty):
    if qty <= 0:
        return

    available = count_on_shelves(product)
    qty = min(qty, available)
    if qty <= 0:
        log(f"Товар {product} недоступен на полках")
        return

    for _ in range(qty):
        robot_task_queues[product].append({"type": "retrieve", "product": product})
    log(f"Запрос: {product}, количество {qty}")


def assign_tasks():
    for robot in robots:
        if robot.task is not None:
            continue
        if robot.is_active():
            continue

        queue = robot_task_queues[robot.product]

        if not queue:
            if robot.pos != robot.home:
                blocked = get_blocked_cells(exclude_robot=robot)
                route = astar(robot.pos, robot.home, blocked=blocked)
                if route:
                    robot.route = route
                    robot.phase = "to_home"
            continue
            
        task = queue[0]
        blocked = get_blocked_cells(exclude_robot=robot)

        if task["type"] == "putaway":
            route = astar(robot.pos, INBOUND_PICK_CELL, blocked=blocked)
            if len(route) == 0:
                continue
            robot.task = queue.popleft()
            robot.phase = "to_pickup_zone"
            robot.route = route
            robot.carry = None
            robot.target_shelf = None

        elif task["type"] == "retrieve":
            shelf = choose_best_pick_shelf(robot.product)
            if shelf is None:
                queue.popleft()
                log(f"Не найдена полка для выдачи {robot.product}")
                continue

            accesses = shelf_access_cells(shelf)
            if not accesses:
                queue.popleft()
                log(f"Нет прохода к полке {shelf}")
                continue

            reserved_pick_shelves.add(shelf)
            access = min(accesses, key=lambda c: manhattan(robot.pos, c))
            blocked_for_route = get_blocked_cells(exclude_robot=robot)
            route1 = astar(robot.pos, access, blocked=blocked_for_route)
            route2 = astar(access, EXIT_CELL, blocked=blocked_for_route)
            route3 = astar(EXIT_CELL, robot.home, blocked=blocked_for_route)
            
            if len(route1) == 0:
                reserved_pick_shelves.discard(shelf)
                continue

            robot.task = queue.popleft()
            robot.task["shelf"] = shelf
            robot.phase = "to_shelf_for_pick"
            robot.route = route1
            robot.next_route_after_phase = route2
            robot.final_route_after_exit = route3
            robot.carry = None
            robot.target_shelf = shelf


def advance_robot_phases():
    for r in robots:
        if r.is_moving():
            continue
        if r.route:
            continue

        if r.task is None:
            if r.phase in ("to_home", "return_home"):
                r.phase = "idle"
            continue

        task = r.task

        if task["type"] == "putaway":
            if r.phase == "to_pickup_zone":
                r.carry = task["product"]
                r.pickup_anim_ticks = 15

                shelf = choose_best_put_shelf(r.carry)
                if shelf is None:
                    r.carry = None
                    robot_task_queues[r.product].appendleft({"type": "putaway", "product": r.product, "source": task.get("source", "labeled")})
                    r.task = None
                    r.phase = "idle"
                    log(f"Нет свободной полки для {r.product}, задача возвращена в очередь")
                    continue

                accesses = shelf_access_cells(shelf)
                if not accesses:
                    r.carry = None
                    robot_task_queues[r.product].appendleft({"type": "putaway", "product": r.product, "source": task.get("source", "labeled")})
                    r.task = None
                    r.phase = "idle"
                    log(f"Нет прохода к полке {shelf} для {r.product}")
                    continue

                reserved_put_shelves.add(shelf)
                blocked = get_blocked_cells(exclude_robot=r)
                access = min(accesses, key=lambda c: manhattan(r.pos, c))
                r.route = astar(r.pos, access, blocked=blocked)
                r.target_shelf = shelf
                r.phase = "to_shelf_for_put"

            elif r.phase == "to_shelf_for_put":
                shelf = r.target_shelf
                info = shelf_state[shelf]

                if shelf_can_store_product(shelf, r.carry):
                    if info["count"] == 0:
                        info["product"] = r.carry
                    info["count"] += 1
                    log(f"РТС-{r.id} ({r.product}) разместил {r.carry} на полке {shelf} [{info['count']}/{SHELF_CAPACITY}]")
                else:
                    robot_task_queues[r.product].appendleft({"type": "putaway", "product": r.product, "source": task.get("source", "labeled")})
                    log(f"Полка {shelf} недоступна для {r.product}, задача возвращена в очередь")

                reserved_put_shelves.discard(shelf)
                r.carry = None
                r.task = None
                r.target_shelf = None
                
                if robot_task_queues[r.product]:
                    blocked = get_blocked_cells(exclude_robot=r)
                    route = astar(r.pos, INBOUND_PICK_CELL, blocked=blocked)
                    if route:
                        r.task = robot_task_queues[r.product].popleft()
                        r.phase = "to_pickup_zone"
                        r.route = route
                    else:
                        r.phase = "idle"
                else:
                    r.phase = "idle"

        elif task["type"] == "retrieve":
            if r.phase == "to_shelf_for_pick":
                shelf = task["shelf"]
                info = shelf_state[shelf]

                if info["product"] == task["product"] and info["count"] > 0:
                    info["count"] -= 1
                    r.carry = task["product"]
                    r.pickup_anim_ticks = 15
                    stock_total[task["product"]] -= 1

                    if info["count"] == 0:
                        info["product"] = None

                    log(f"РТС-{r.id} ({r.product}) забрал {task['product']} с полки {shelf}")
                else:
                    log(f"РТС-{r.id} не нашёл {task['product']} на полке {shelf}")

                reserved_pick_shelves.discard(shelf)
                blocked = get_blocked_cells(exclude_robot=r)
                r.route = astar(r.pos, EXIT_CELL, blocked=blocked)
                r.final_route_after_exit = astar(EXIT_CELL, r.home, blocked=blocked)
                r.phase = "to_exit"

            elif r.phase == "to_exit":
                if r.carry is not None:
                    log(f"РТС-{r.id} ({r.product}) доставил {r.carry} к выходу")
                    r.delivery_anim_ticks = 25

                r.carry = None
                r.task = None
                r.target_shelf = None
                r.final_route_after_exit = []
                
                if robot_task_queues[r.product]:
                    blocked = get_blocked_cells(exclude_robot=r)
                    shelf = choose_best_pick_shelf(r.product)
                    if shelf:
                        accesses = shelf_access_cells(shelf)
                        if accesses:
                            reserved_pick_shelves.add(shelf)
                            access = min(accesses, key=lambda c: manhattan(r.pos, c))
                            route = astar(r.pos, access, blocked=blocked)
                            if route:
                                r.task = robot_task_queues[r.product].popleft()
                                r.task["shelf"] = shelf
                                r.phase = "to_shelf_for_pick"
                                r.route = route
                                r.next_route_after_phase = []
                                r.final_route_after_exit = []
                                r.target_shelf = shelf
                            else:
                                reserved_pick_shelves.discard(shelf)
                                r.phase = "idle"
                                r.route = astar(r.pos, r.home, blocked=blocked)
                        else:
                            reserved_pick_shelves.discard(shelf)
                            r.phase = "idle"
                            r.route = astar(r.pos, r.home, blocked=blocked)
                    else:
                        r.phase = "idle"
                        r.route = astar(r.pos, r.home, blocked=blocked)
                else:
                    r.phase = "idle"
                    blocked = get_blocked_cells(exclude_robot=r)
                    r.route = astar(r.pos, r.home, blocked=blocked)


def move_uav_towards(target, speed=AGENT_SPEED):
    vec = np.array(target, dtype=float) - np.array(uav.pos, dtype=float)
    dist = np.linalg.norm(vec)
    if dist <= speed or dist == 0:
        uav.pos[0], uav.pos[1], uav.pos[2] = target
    else:
        vec = vec / dist
        uav.pos[0] += vec[0] * speed
        uav.pos[1] += vec[1] * speed
        uav.pos[2] += vec[2] * speed


def update_uav():
    if uav.state == "idle":
        if uav_scan_queue:
            uav.state = "to_inbound"

    elif uav.state == "to_inbound":
        target = (INBOUND_CELL[0], INBOUND_CELL[1], 3.2)
        move_uav_towards(target)
        if close3(uav.pos, target):
            uav.state = "scanning"
            uav.scan_ticks = 30

    elif uav.state == "scanning":
        uav.scan_ticks -= 1
        if uav.scan_ticks <= 0 and uav_scan_queue:
            qty = uav_scan_queue.popleft()
            product = detect_product_ai()
            log(f"БВС распознал товар без метки как {product}, количество {qty}")

            for _ in range(qty):
                stock_total[product] += 1
                robot_task_queues[product].append({"type": "putaway", "product": product, "source": "unlabeled"})

            uav.state = "to_home"

    elif uav.state == "to_home":
        move_uav_towards(UAV_HOME_POS)
        if close3(uav.pos, UAV_HOME_POS):
            uav.state = "idle"


def preload():
    supply_labeled("metal", 3)
    supply_labeled("plastic", 3)
    supply_labeled("electronics", 3)
    supply_labeled("wood", 3)
    supply_labeled("glass", 3)
    log("Система запущена")
