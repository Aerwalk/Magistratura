"""State module - warehouse state management."""

from collections import deque, defaultdict
from typing import Optional

from src.config import PRODUCTS, SHELF_CAPACITY
from src.core.grid import all_shelves, get_grid_w, get_grid_h


class WarehouseState:
    """Singleton warehouse state manager."""
    
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
        self.event_log = deque(maxlen=500)
        self.uav_scan_queue = deque()
        self.robot_task_queues = {p: deque() for p in PRODUCTS}
        self.reserved_put_shelves = set()
        self.reserved_pick_shelves = set()
        self.rebalance_active = False
        self.rebalance_moves_remaining = 0
    
    def reset(self):
        """Reset warehouse state to initial values."""
        self.__init__()


# Global state instance
_state = WarehouseState()


def get_state() -> WarehouseState:
    """Get the global warehouse state instance."""
    return _state


# Convenience accessors
def count_on_shelves(product: str) -> int:
    """Count items of a product currently on shelves."""
    return sum(
        info["count"] 
        for info in _state.shelf_state.values() 
        if info["product"] == product
    )


def distinct_products_on_shelves() -> list:
    """Get list of products currently stored on shelves."""
    return [p for p in PRODUCTS if count_on_shelves(p) > 0]


def shelf_can_store_product(shelf: tuple, product: str) -> bool:
    """Check if a shelf can store a given product."""
    info = _state.shelf_state[shelf]
    if info["count"] == 0:
        return True
    return info["product"] == product and info["count"] < SHELF_CAPACITY


def product_hotness(product: str) -> int:
    """Calculate product demand hotness for shelf placement."""
    return 1 + _state.demand.get(product, 0)


def log(message: str) -> None:
    """Add message to event log."""
    _state.event_log.appendleft(message)
