"""Configuration constants for MagSim warehouse simulation."""

PRODUCTS = ["metal", "plastic", "electronics", "wood", "glass"]

def hex_to_rgba(hex_color: str) -> tuple:
    h = hex_color.lstrip('#')
    r = int(h[0:2], 16) / 255
    g = int(h[2:4], 16) / 255
    b = int(h[4:6], 16) / 255
    return (r, g, b, 1.0)

def add_product(name: str, color: tuple):
    if name in PRODUCTS:
        return
    PRODUCTS.append(name)
    PRODUCT_COLORS[name] = color
    from core.state import get_state
    from collections import deque
    state = get_state()
    state.robot_task_queues[name] = deque()
    state.event_log.appendleft(f"Добавлен новый материал: {name}")

PRODUCT_COLORS = {
    "metal": (0.78, 0.78, 0.82, 1.0),
    "plastic": (0.10, 0.55, 0.95, 1.0),
    "electronics": (1.00, 0.55, 0.10, 1.0),
    "wood": (0.55, 0.32, 0.12, 1.0),
    "glass": (0.20, 0.90, 0.90, 1.0),
}

SHELF_CAPACITY = 5
AGENT_SPEED = 0.25
TICK_MS = 50

# ─── Battery model ───
BATTERY_DRAIN_MOVING = 0.45       # % per second while moving
BATTERY_DRAIN_IDLE = 0.09         # % per second while idle
BATTERY_CHARGE_RATE = 1.0         # % per second while charging at home
BATTERY_LOW = 20.0                # below this the robot returns home to charge
BATTERY_CHARGE_THRESHOLD = 40.0   # charge at home only when battery is at/below this %; >40% → keep working
BATTERY_FAIL_MAX = 60.0           # battery_max below this => battery is failing
BATTERY_CHARGE_HYSTERESIS = 2.0   # % below battery_max before top-up charging starts
BATTERY_MAX_DEGRADE_PER_FULL_CHARGE = 1.0  # battery_max loss per 100% charged
BATTERY_DEGRADED_WARNING_PCT = 60  # degradation above this % => battery needs replacement
BATTERY_TASK_DRAIN = 15.0         # % battery drain per completed task (putaway/retrieve)

# ─── Stuck detection ───
STUCK_SECONDS = 30                # robot stuck if standing still this many seconds
STUCK_TICKS = int(STUCK_SECONDS / (TICK_MS / 1000.0))  # ticks at 50 ms = 600

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
