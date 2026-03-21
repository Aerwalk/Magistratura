import sys
import random
import heapq
from collections import deque, defaultdict

import numpy as np
from PyQt5 import QtWidgets, QtCore, QtGui
import pyqtgraph.opengl as gl


GRID_W = 14
GRID_H = 10

EXIT_CELL = (0, GRID_H // 2)
INBOUND_CELL = (1, 1)
INBOUND_PICK_CELL = (2, 1)
UAV_HOME = (GRID_W // 2, GRID_H // 2, 4.5)

TICK_MS = 35
SHELF_CAPACITY = 3
AGENT_SPEED = 0.10

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

ROBOT_CONFIG = [
    {"product": "metal", "color": (1.0, 0.1, 0.1, 1.0), "home": (13, 1)},
    {"product": "plastic", "color": (0.1, 0.4, 1.0, 1.0), "home": (13, 2)},
    {"product": "electronics", "color": (1.0, 0.5, 0.1, 1.0), "home": (13, 3)},
    {"product": "wood", "color": (0.1, 0.8, 0.3, 1.0), "home": (13, 7)},
    {"product": "glass", "color": (0.8, 0.2, 0.8, 1.0), "home": (13, 8)},
]

SHELF_X = {4, 6, 8, 10, 12}
AISLE_CELLS = set()

for x in range(GRID_W):
    for y in range(GRID_H):
        if x not in SHELF_X:
            AISLE_CELLS.add((x, y))

AISLE_CELLS.add(EXIT_CELL)
AISLE_CELLS.add(INBOUND_CELL)
AISLE_CELLS.add(INBOUND_PICK_CELL)


def is_shelf_cell(x, y):
    return x in SHELF_X and 0 <= y < GRID_H


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


def move_agent_towards_2d(pos, target, speed):
    vec = np.array(target, dtype=float) - np.array(pos, dtype=float)
    dist = np.linalg.norm(vec)
    if dist <= speed or dist == 0:
        return [float(target[0]), float(target[1])]
    vec = vec / dist
    return [pos[0] + vec[0] * speed, pos[1] + vec[1] * speed]


def close2(a, b, eps=0.03):
    return abs(a[0] - b[0]) < eps and abs(a[1] - b[1]) < eps


robots = []
for idx, cfg in enumerate(ROBOT_CONFIG):
    home = cfg["home"]
    robots.append({
        "id": idx,
        "product": cfg["product"],
        "color": cfg["color"],
        "home": home,
        "pos": home,
        "draw_pos": [float(home[0]), float(home[1])],
        "route": [],
        "current_target": None,
        "task": None,
        "carry": None,
        "phase": "idle",
        "next_route_after_phase": [],
        "final_route_after_exit": [],
        "target_shelf": None,
        "speed": AGENT_SPEED,
    })


def robot_is_moving(robot):
    return robot["current_target"] is not None


def start_robot_next_segment(robot):
    if robot["current_target"] is None and robot["route"]:
        robot["current_target"] = robot["route"].pop(0)


def update_single_robot_motion(robot):
    if robot["current_target"] is None:
        start_robot_next_segment(robot)
        return

    tx, ty = robot["current_target"]
    robot["draw_pos"] = move_agent_towards_2d(robot["draw_pos"], (tx, ty), robot["speed"])

    if close2(robot["draw_pos"], (tx, ty)):
        robot["draw_pos"] = [float(tx), float(ty)]
        robot["pos"] = (tx, ty)
        robot["current_target"] = None
        start_robot_next_segment(robot)


def move_robots_one_step():
    for robot in robots:
        update_single_robot_motion(robot)


uav = {
    "pos": [float(UAV_HOME[0]), float(UAV_HOME[1]), float(UAV_HOME[2])],
    "state": "idle",
    "scan_ticks": 0,
}


def supply_labeled(product, qty):
    if qty <= 0:
        return
    for _ in range(qty):
        stock_total[product] += 1
        robot_task_queues[product].append({"type": "putaway", "product": product})
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
        if robot["task"] is not None:
            continue
        if robot_is_moving(robot):
            continue
        if robot["route"]:
            continue

        queue = robot_task_queues[robot["product"]]

        if not queue:
            if robot["pos"] != robot["home"]:
                blocked = {r["pos"] for r in robots if r["id"] != robot["id"]}
                route = astar(robot["pos"], robot["home"], blocked=blocked)
                if route:
                    robot["route"] = route
                    robot["phase"] = "to_home"
            continue

        task = queue[0]
        blocked = {r["pos"] for r in robots if r["id"] != robot["id"]}

        if task["type"] == "putaway":
            route = astar(robot["pos"], INBOUND_PICK_CELL, blocked=blocked)
            robot["task"] = queue.popleft()
            robot["phase"] = "to_pickup_zone"
            robot["route"] = route
            robot["carry"] = None
            robot["target_shelf"] = None

        elif task["type"] == "retrieve":
            shelf = choose_best_pick_shelf(robot["product"])
            if shelf is None:
                queue.popleft()
                log(f"Не найдена полка для выдачи {robot['product']}")
                continue

            accesses = shelf_access_cells(shelf)
            if not accesses:
                queue.popleft()
                log(f"Нет прохода к полке {shelf}")
                continue

            reserved_pick_shelves.add(shelf)
            access = min(accesses, key=lambda c: manhattan(robot["pos"], c))
            route1 = astar(robot["pos"], access, blocked=blocked)
            route2 = astar(access, EXIT_CELL, blocked=blocked)
            route3 = astar(EXIT_CELL, robot["home"], blocked=blocked)

            robot["task"] = queue.popleft()
            robot["task"]["shelf"] = shelf
            robot["phase"] = "to_shelf_for_pick"
            robot["route"] = route1
            robot["next_route_after_phase"] = route2
            robot["final_route_after_exit"] = route3
            robot["carry"] = None
            robot["target_shelf"] = shelf


def advance_robot_phases():
    for r in robots:
        if robot_is_moving(r):
            continue
        if r["route"]:
            continue

        if r["task"] is None:
            if r["phase"] in ("to_home", "return_home"):
                r["phase"] = "idle"
            continue

        task = r["task"]

        if task["type"] == "putaway":
            if r["phase"] == "to_pickup_zone":
                r["carry"] = task["product"]

                shelf = choose_best_put_shelf(r["carry"])
                if shelf is None:
                    r["carry"] = None
                    robot_task_queues[r["product"]].appendleft({"type": "putaway", "product": r["product"]})
                    r["task"] = None
                    r["phase"] = "idle"
                    log(f"Нет свободной полки для {r['product']}, задача возвращена в очередь")
                    continue

                accesses = shelf_access_cells(shelf)
                if not accesses:
                    r["carry"] = None
                    robot_task_queues[r["product"]].appendleft({"type": "putaway", "product": r["product"]})
                    r["task"] = None
                    r["phase"] = "idle"
                    log(f"Нет прохода к полке {shelf} для {r['product']}")
                    continue

                reserved_put_shelves.add(shelf)
                blocked = {rb["pos"] for rb in robots if rb["id"] != r["id"]}
                access = min(accesses, key=lambda c: manhattan(r["pos"], c))
                r["route"] = astar(r["pos"], access, blocked=blocked)
                r["target_shelf"] = shelf
                r["phase"] = "to_shelf_for_put"

            elif r["phase"] == "to_shelf_for_put":
                shelf = r["target_shelf"]
                info = shelf_state[shelf]

                if shelf_can_store_product(shelf, r["carry"]):
                    if info["count"] == 0:
                        info["product"] = r["carry"]
                    info["count"] += 1
                    log(f"РТС-{r['id']} ({r['product']}) разместил {r['carry']} на полке {shelf} [{info['count']}/{SHELF_CAPACITY}]")
                else:
                    robot_task_queues[r["product"]].appendleft({"type": "putaway", "product": r["product"]})
                    log(f"Полка {shelf} недоступна для {r['product']}, задача возвращена в очередь")

                reserved_put_shelves.discard(shelf)
                blocked = {rb["pos"] for rb in robots if rb["id"] != r["id"]}
                r["route"] = astar(r["pos"], r["home"], blocked=blocked)
                r["carry"] = None
                r["task"] = None
                r["phase"] = "return_home"
                r["target_shelf"] = None

        elif task["type"] == "retrieve":
            if r["phase"] == "to_shelf_for_pick":
                shelf = task["shelf"]
                info = shelf_state[shelf]

                if info["product"] == task["product"] and info["count"] > 0:
                    info["count"] -= 1
                    r["carry"] = task["product"]
                    stock_total[task["product"]] -= 1

                    if info["count"] == 0:
                        info["product"] = None

                    log(f"РТС-{r['id']} ({r['product']}) забрал {task['product']} с полки {shelf}")
                else:
                    log(f"РТС-{r['id']} не нашёл {task['product']} на полке {shelf}")

                reserved_pick_shelves.discard(shelf)
                blocked = {rb["pos"] for rb in robots if rb["id"] != r["id"]}
                r["route"] = astar(r["pos"], EXIT_CELL, blocked=blocked)
                r["final_route_after_exit"] = astar(EXIT_CELL, r["home"], blocked=blocked)
                r["phase"] = "to_exit"

            elif r["phase"] == "to_exit":
                if r["carry"] is not None:
                    log(f"РТС-{r['id']} ({r['product']}) доставил {r['carry']} к выходу")

                r["carry"] = None
                r["phase"] = "return_home"
                r["route"] = list(r["final_route_after_exit"])
                r["task"] = None
                r["target_shelf"] = None


def move_uav_towards(target, speed=AGENT_SPEED):
    vec = np.array(target, dtype=float) - np.array(uav["pos"], dtype=float)
    dist = np.linalg.norm(vec)
    if dist <= speed or dist == 0:
        uav["pos"][0], uav["pos"][1], uav["pos"][2] = target
    else:
        vec = vec / dist
        uav["pos"][0] += vec[0] * speed
        uav["pos"][1] += vec[1] * speed
        uav["pos"][2] += vec[2] * speed


def close3(a, b, eps=0.15):
    return abs(a[0] - b[0]) < eps and abs(a[1] - b[1]) < eps and abs(a[2] - b[2]) < eps


def update_uav():
    if uav["state"] == "idle":
        if uav_scan_queue:
            uav["state"] = "to_inbound"

    elif uav["state"] == "to_inbound":
        target = (INBOUND_CELL[0], INBOUND_CELL[1], 3.2)
        move_uav_towards(target)
        if close3(uav["pos"], target):
            uav["state"] = "scanning"
            uav["scan_ticks"] = 22

    elif uav["state"] == "scanning":
        uav["scan_ticks"] -= 1
        if uav["scan_ticks"] <= 0 and uav_scan_queue:
            qty = uav_scan_queue.popleft()
            product = detect_product_ai()
            log(f"БВС распознал товар без метки как {product}, количество {qty}")

            for _ in range(qty):
                stock_total[product] += 1
                robot_task_queues[product].append({"type": "putaway", "product": product})

            uav["state"] = "to_home"

    elif uav["state"] == "to_home":
        move_uav_towards(UAV_HOME)
        if close3(uav["pos"], UAV_HOME):
            uav["state"] = "idle"


class Warehouse3D(gl.GLViewWidget):
    def __init__(self):
        super().__init__()
        self.setBackgroundColor((28, 28, 34))
        self.setCameraPosition(distance=28, elevation=28, azimuth=38)
        self.opts["center"] = QtGui.QVector3D(GRID_W / 2, GRID_H / 2, 1.4)

        self.grid_item = gl.GLGridItem()
        self.grid_item.setSize(GRID_W + 2, GRID_H + 2)
        self.grid_item.setSpacing(1, 1)
        self.grid_item.translate(GRID_W / 2 - 0.5, GRID_H / 2 - 0.5, 0)
        self.addItem(self.grid_item)

        self.floor_item = gl.GLScatterPlotItem(pxMode=True)
        self.addItem(self.floor_item)

        self.shelf_item = gl.GLScatterPlotItem(pxMode=True)
        self.addItem(self.shelf_item)

        self.robot_body_item = gl.GLScatterPlotItem(pxMode=True)
        self.addItem(self.robot_body_item)

        self.robot_top_item = gl.GLScatterPlotItem(pxMode=True)
        self.addItem(self.robot_top_item)

        self.robot_cargo_item = gl.GLScatterPlotItem(pxMode=True)
        self.addItem(self.robot_cargo_item)

        self.uav_item = gl.GLScatterPlotItem(pxMode=True)
        self.addItem(self.uav_item)

        self.uav_beam = gl.GLLinePlotItem(width=2, antialias=True)
        self.addItem(self.uav_beam)

    def update_scene(self):
        floor_pts = np.array([
            [INBOUND_CELL[0], INBOUND_CELL[1], 0.05],
            [INBOUND_PICK_CELL[0], INBOUND_PICK_CELL[1], 0.05],
            [EXIT_CELL[0], EXIT_CELL[1], 0.05],
        ], dtype=float)
        floor_cols = np.array([
            [0.2, 1.0, 0.2, 1.0],
            [0.2, 0.85, 0.85, 1.0],
            [1.0, 1.0, 0.2, 1.0],
        ], dtype=float)
        self.floor_item.setData(pos=floor_pts, color=floor_cols, size=18)

        shelf_pts = []
        shelf_cols = []
        shelf_sizes = []
        for (x, y), info in shelf_state.items():
            for level in range(SHELF_CAPACITY):
                z = 0.18 + level * 0.32
                if level < info["count"] and info["product"] is not None:
                    color = PRODUCT_COLORS[info["product"]]
                    size = 28
                else:
                    color = (0.40, 0.40, 0.45, 0.85)
                    size = 16
                shelf_pts.append([x, y, z])
                shelf_cols.append(color)
                shelf_sizes.append(size)
        self.shelf_item.setData(
            pos=np.array(shelf_pts, dtype=float),
            color=np.array(shelf_cols, dtype=float),
            size=np.array(shelf_sizes, dtype=float)
        )

        body_pts, body_cols, body_sizes = [], [], []
        top_pts, top_cols, top_sizes = [], [], []
        cargo_pts, cargo_cols, cargo_sizes = [], [], []

        for r in robots:
            x, y = r["draw_pos"]
            body_pts.append([x, y, 0.20])
            body_cols.append(r["color"])
            body_sizes.append(24)

            top_pts.append([x, y, 0.40])
            top_cols.append([1.0, 1.0, 1.0, 1.0])
            top_sizes.append(10)

            if r["carry"] is not None:
                cargo_pts.append([x, y, 0.68])
                cargo_cols.append(PRODUCT_COLORS[r["carry"]])
                cargo_sizes.append(18)

        self.robot_body_item.setData(
            pos=np.array(body_pts, dtype=float),
            color=np.array(body_cols, dtype=float),
            size=np.array(body_sizes, dtype=float)
        )
        self.robot_top_item.setData(
            pos=np.array(top_pts, dtype=float),
            color=np.array(top_cols, dtype=float),
            size=np.array(top_sizes, dtype=float)
        )

        if cargo_pts:
            self.robot_cargo_item.setData(
                pos=np.array(cargo_pts, dtype=float),
                color=np.array(cargo_cols, dtype=float),
                size=np.array(cargo_sizes, dtype=float)
            )
        else:
            self.robot_cargo_item.setData(
                pos=np.empty((0, 3), dtype=float),
                color=np.empty((0, 4), dtype=float),
                size=np.empty((0,), dtype=float)
            )

        ux, uy, uz = uav["pos"]
        self.uav_item.setData(
            pos=np.array([[ux, uy, uz]], dtype=float),
            color=np.array([[1.0, 1.0, 0.1, 1.0]], dtype=float),
            size=30
        )
        self.uav_beam.setData(
            pos=np.array([[ux, uy, uz], [ux, uy, 0.0]], dtype=float),
            color=(1.0, 1.0, 0.2, 0.6)
        )


class WarehouseApp(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Склад: БВС + РТС")
        self.resize(1550, 920)

        central = QtWidgets.QWidget()
        self.setCentralWidget(central)

        root = QtWidgets.QHBoxLayout(central)

        self.view3d = Warehouse3D()
        root.addWidget(self.view3d, 3)

        right = QtWidgets.QVBoxLayout()
        root.addLayout(right, 2)

        controls = QtWidgets.QGroupBox("Управление")
        controls_layout = QtWidgets.QGridLayout(controls)
        right.addWidget(controls)

        self.cb_supply = QtWidgets.QComboBox()
        self.cb_supply.addItems(PRODUCTS)

        self.sb_supply_qty = QtWidgets.QSpinBox()
        self.sb_supply_qty.setRange(1, 200)
        self.sb_supply_qty.setValue(3)

        self.sb_unlabeled_qty = QtWidgets.QSpinBox()
        self.sb_unlabeled_qty.setRange(1, 200)
        self.sb_unlabeled_qty.setValue(2)

        self.cb_request = QtWidgets.QComboBox()
        self.sb_request_qty = QtWidgets.QSpinBox()
        self.sb_request_qty.setRange(1, 1)
        self.sb_request_qty.setValue(1)

        self.cb_request.currentIndexChanged.connect(self.on_request_product_changed)
        self.refresh_request_products()

        btn_supply = QtWidgets.QPushButton("Поставка с меткой")
        btn_supply.clicked.connect(self.on_supply_labeled)

        btn_unlabeled = QtWidgets.QPushButton("Поставка без метки")
        btn_unlabeled.clicked.connect(self.on_supply_unlabeled)

        btn_request = QtWidgets.QPushButton("Запрос товара")
        btn_request.clicked.connect(self.on_request)

        btn_demo = QtWidgets.QPushButton("Демо-заполнение")
        btn_demo.clicked.connect(self.on_demo_fill)

        controls_layout.addWidget(QtWidgets.QLabel("Товар:"), 0, 0)
        controls_layout.addWidget(self.cb_supply, 0, 1)
        controls_layout.addWidget(QtWidgets.QLabel("Кол-во:"), 0, 2)
        controls_layout.addWidget(self.sb_supply_qty, 0, 3)
        controls_layout.addWidget(btn_supply, 0, 4)

        controls_layout.addWidget(QtWidgets.QLabel("Без метки, кол-во:"), 1, 0, 1, 2)
        controls_layout.addWidget(self.sb_unlabeled_qty, 1, 2)
        controls_layout.addWidget(btn_unlabeled, 1, 3, 1, 2)

        controls_layout.addWidget(QtWidgets.QLabel("Запрос товара:"), 2, 0)
        controls_layout.addWidget(self.cb_request, 2, 1)
        controls_layout.addWidget(QtWidgets.QLabel("Кол-во:"), 2, 2)
        controls_layout.addWidget(self.sb_request_qty, 2, 3)
        controls_layout.addWidget(btn_request, 2, 4)

        controls_layout.addWidget(btn_demo, 3, 0, 1, 5)

        stats_group = QtWidgets.QGroupBox("Статистика")
        stats_layout = QtWidgets.QVBoxLayout(stats_group)
        right.addWidget(stats_group, 2)

        self.stats_table = QtWidgets.QTableWidget(0, 4)
        self.stats_table.setHorizontalHeaderLabels(["Товар", "Всего", "На полках", "Спрос"])
        self.stats_table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Stretch)
        stats_layout.addWidget(self.stats_table)

        map_group = QtWidgets.QGroupBox("Карта полок (клик по клетке)")
        map_layout = QtWidgets.QVBoxLayout(map_group)
        right.addWidget(map_group, 3)

        self.map_table = QtWidgets.QTableWidget(GRID_H, GRID_W)
        self.map_table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Stretch)
        self.map_table.verticalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Stretch)
        self.map_table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.map_table.cellClicked.connect(self.on_map_click)
        map_layout.addWidget(self.map_table)

        log_group = QtWidgets.QGroupBox("Лог")
        log_layout = QtWidgets.QVBoxLayout(log_group)
        right.addWidget(log_group, 2)

        self.log_text = QtWidgets.QPlainTextEdit()
        self.log_text.setReadOnly(True)
        log_layout.addWidget(self.log_text)

        self.info_label = QtWidgets.QLabel("Выберите операцию")
        right.addWidget(self.info_label)

        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(TICK_MS)

        self.refresh_all()

    def on_demo_fill(self):
        for p in PRODUCTS:
            supply_labeled(p, random.randint(2, 4))
        supply_unlabeled(3)
        self.refresh_all()

    def on_supply_labeled(self):
        supply_labeled(self.cb_supply.currentText(), self.sb_supply_qty.value())
        self.refresh_all()

    def on_supply_unlabeled(self):
        supply_unlabeled(self.sb_unlabeled_qty.value())
        self.refresh_all()

    def on_request_product_changed(self):
        product = self.cb_request.currentText()
        if not product:
            self.sb_request_qty.setRange(1, 1)
            self.sb_request_qty.setValue(1)
            return

        max_qty = max(1, count_on_shelves(product))
        self.sb_request_qty.setRange(1, max_qty)
        if self.sb_request_qty.value() > max_qty:
            self.sb_request_qty.setValue(max_qty)

    def on_request(self):
        product = self.cb_request.currentText()
        if not product:
            QtWidgets.QMessageBox.information(self, "Запрос", "На складе нет материалов на полках.")
            return

        max_qty = count_on_shelves(product)
        qty = min(self.sb_request_qty.value(), max_qty)
        if qty <= 0:
            QtWidgets.QMessageBox.information(self, "Запрос", "Этот материал сейчас недоступен на полках.")
            return

        request_product(product, qty)
        self.refresh_all()

    def on_map_click(self, row, col):
        x = col
        y = row

        if not is_shelf_cell(x, y):
            self.info_label.setText(f"Клетка ({x}, {y}) — проход/служебная зона")
            return

        info = shelf_state[(x, y)]
        if info["count"] == 0:
            self.info_label.setText(f"Полка ({x}, {y}) пустая")
        else:
            self.info_label.setText(
                f"Полка ({x}, {y}) | материал={info['product']} | "
                f"количество={info['count']}/{SHELF_CAPACITY} | "
                f"спрос={demand.get(info['product'], 0)} | "
                f"на полках={count_on_shelves(info['product'])} | "
                f"всего={stock_total.get(info['product'], 0)}"
            )

    def tick(self):
        update_uav()
        assign_tasks()
        move_robots_one_step()
        advance_robot_phases()
        self.refresh_all()

    def refresh_request_products(self):
        current = self.cb_request.currentText()
        items = distinct_products_on_shelves()

        self.cb_request.blockSignals(True)
        self.cb_request.clear()
        self.cb_request.addItems(items)
        if current in items:
            self.cb_request.setCurrentText(current)
        self.cb_request.blockSignals(False)

        has_items = len(items) > 0
        self.cb_request.setEnabled(has_items)
        self.sb_request_qty.setEnabled(has_items)

        if has_items:
            self.on_request_product_changed()
        else:
            self.sb_request_qty.setRange(1, 1)
            self.sb_request_qty.setValue(1)

    def refresh_stats(self):
        all_products = sorted(set(PRODUCTS) | set(stock_total.keys()) | set(demand.keys()))
        self.stats_table.setRowCount(len(all_products))

        for row, p in enumerate(all_products):
            vals = [
                p,
                str(stock_total.get(p, 0)),
                str(count_on_shelves(p)),
                str(demand.get(p, 0)),
            ]
            for col, val in enumerate(vals):
                item = QtWidgets.QTableWidgetItem(val)
                if col == 0 and p in PRODUCT_QCOLORS:
                    item.setBackground(PRODUCT_QCOLORS[p])
                self.stats_table.setItem(row, col, item)

    def refresh_map(self):
        for y in range(GRID_H):
            for x in range(GRID_W):
                item = QtWidgets.QTableWidgetItem("")

                if (x, y) == EXIT_CELL:
                    item.setText("OUT")
                    item.setBackground(QtGui.QColor(235, 235, 120))

                elif (x, y) == INBOUND_CELL:
                    item.setText("IN")
                    item.setBackground(QtGui.QColor(120, 235, 120))

                elif (x, y) == INBOUND_PICK_CELL:
                    item.setText("PICK")
                    item.setBackground(QtGui.QColor(120, 220, 220))

                elif is_shelf_cell(x, y):
                    info = shelf_state[(x, y)]
                    if info["count"] == 0:
                        item.setText("0/3")
                        item.setBackground(QtGui.QColor(95, 95, 100))
                    else:
                        item.setText(f"{info['product'][:3]}:{info['count']}/3")
                        item.setBackground(PRODUCT_QCOLORS[info["product"]])

                else:
                    item.setText("")
                    item.setBackground(QtGui.QColor(45, 45, 45))

                self.map_table.setItem(y, x, item)

    def refresh_log(self):
        self.log_text.setPlainText("\n".join(event_log))

    def refresh_all(self):
        self.refresh_request_products()
        self.refresh_stats()
        self.refresh_map()
        self.refresh_log()
        self.view3d.update_scene()


def preload():
    supply_labeled("metal", 3)
    supply_labeled("plastic", 3)
    supply_labeled("electronics", 3)
    supply_labeled("wood", 3)
    supply_labeled("glass", 3)
    log("Система запущена")


if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    preload()
    win = WarehouseApp()
    win.show()
    sys.exit(app.exec_())