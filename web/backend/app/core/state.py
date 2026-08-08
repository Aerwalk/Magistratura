from collections import deque, defaultdict
from typing import Optional

from config import PRODUCTS, SHELF_CAPACITY
from core.grid import all_shelves


class WarehouseState:
    _instance: Optional['WarehouseState'] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self.shelf_state = {shelf: {"product": None, "count": 0} for shelf in all_shelves()}
        self.stock_total = defaultdict(int)
        self.demand = defaultdict(int)
        self.delivered_total = defaultdict(int)
        self.retrieved_total = defaultdict(int)
        self.event_log = deque(maxlen=500)
        self.uav_scan_queue = deque()
        self.robot_task_queues = {p: deque() for p in PRODUCTS}
        self.reserved_put_shelves = set()
        self.reserved_pick_shelves = set()
        self.rebalance_active = False
        self.rebalance_moves_remaining = 0
        self.shelf_capacity_override = {}  # (x,y) -> int
        self.shelf_allowed_products = {}  # (x,y) -> set of allowed products or None for any

    def reset(self):
        self._initialized = False
        self.__init__()


_state = WarehouseState()


def get_state() -> WarehouseState:
    return _state


def count_on_shelves(product: str) -> int:
    return sum(
        info["count"]
        for info in _state.shelf_state.values()
        if info["product"] == product
    )


def distinct_products_on_shelves() -> list:
    return [p for p in PRODUCTS if count_on_shelves(p) > 0]


def get_shelf_max_capacity(shelf: tuple) -> int:
    return _state.shelf_capacity_override.get(shelf, SHELF_CAPACITY)


def get_shelf_allowed_products(shelf: tuple):
    return _state.shelf_allowed_products.get(shelf, None)


def shelf_can_store_product(shelf: tuple, product: str) -> bool:
    info = _state.shelf_state[shelf]
    max_cap = get_shelf_max_capacity(shelf)
    allowed = get_shelf_allowed_products(shelf)
    if allowed is not None and product not in allowed:
        return False
    if info["count"] == 0:
        return True
    return info["product"] == product and info["count"] < max_cap


def product_hotness(product: str) -> int:
    return 1 + _state.demand.get(product, 0)


def log(message: str) -> None:
    _state.event_log.appendleft(message)
