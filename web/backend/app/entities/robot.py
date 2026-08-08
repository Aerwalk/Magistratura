from typing import Optional

from config import PRODUCTS, PRODUCT_COLORS, AGENT_SPEED, HOME_CELLS


_ROBOT_INITIAL_CONFIG = [
    {"product": "metal", "color": (1.0, 0.1, 0.1, 1.0), "home": (14, 1)},
    {"product": "plastic", "color": (0.1, 0.4, 1.0, 1.0), "home": (14, 3)},
    {"product": "electronics", "color": (1.0, 0.5, 0.1, 1.0), "home": (14, 5)},
    {"product": "wood", "color": (0.1, 0.8, 0.3, 1.0), "home": (14, 7)},
    {"product": "glass", "color": (0.8, 0.2, 0.8, 1.0), "home": (14, 9)},
]


def _rand_color():
    import random
    import numpy as np
    return (float(random.random()), float(random.random()), float(random.random()), 1.0)


class Robot:
    def __init__(self, idx: int, product: str, color: tuple, home: tuple):
        self.id = idx
        self.name = f"РТС-{idx}"
        self.product = product
        self.products = {product}
        self.color = color
        self.home = home
        self.pos = home
        self.draw_pos = [float(home[0]), float(home[1])]
        self.route = []
        self.current_target: Optional[tuple] = None
        self.task: Optional[dict] = None
        self.carry: Optional[str] = None
        self.phase = "idle"
        self.next_route_after_phase = []
        self.final_route_after_exit = []
        self.target_shelf: Optional[tuple] = None
        self.speed = AGENT_SPEED
        self.delivery_anim_ticks = 0
        self.carry_bob = 0.0
        self.pickup_anim_ticks = 0
        self.carry_appear_scale = 1.0
        self.wait_ticks = 0
        self.stuck_ticks = 0
        self.last_pos = home
        self.capacity = 1
        self.carry_qty = 0

    def is_moving(self) -> bool:
        return self.current_target is not None

    def is_active(self) -> bool:
        return self.current_target is not None or self.wait_ticks > 0 or self.route

    def check_stuck(self) -> bool:
        if self.pos == self.last_pos and self.is_active():
            self.stuck_ticks += 1
            if self.stuck_ticks > 100:
                return True
        else:
            self.stuck_ticks = 0
            self.last_pos = self.pos
        return False

    def reset(self) -> None:
        self.pos = self.home
        self.draw_pos = [float(self.home[0]), float(self.home[1])]
        self.route = []
        self.current_target = None
        self.task = None
        self.carry = None
        self.phase = "idle"
        self.target_shelf = None
        self.stuck_ticks = 0
        self.delivery_anim_ticks = 0
        self.pickup_anim_ticks = 0
        self.carry_appear_scale = 1.0
        self.wait_ticks = 0
        self.carry_qty = 0


robots = [Robot(idx, cfg["product"], cfg["color"], cfg["home"]) for idx, cfg in enumerate(_ROBOT_INITIAL_CONFIG)]


def _next_id() -> int:
    return max(r.id for r in robots) + 1 if robots else 0


def _next_home() -> tuple:
    used_homes = {r.home for r in robots}
    for cell in (14, 0), (14, 2), (14, 4), (14, 6), (14, 8), (14, 10), (14, 11):
        if cell not in used_homes:
            return cell
    return None


def create_robot(product: str) -> Optional[Robot]:
    home = _next_home()
    if home is None:
        return None
    from core.grid import add_home_cell
    add_home_cell(home)
    color = PRODUCT_COLORS.get(product, _rand_color())
    new_id = _next_id()
    robot = Robot(new_id, product, color, home)
    robots.append(robot)
    from core.state import get_state
    state = get_state()
    state.event_log.appendleft(f"{robot.name} создан для продукта {product}, станция {home}")
    return robot
