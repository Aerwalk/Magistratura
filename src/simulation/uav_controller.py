"""UAV controller module."""

import random
import numpy as np

from src.config import AGENT_SPEED, UAV_HOME_POS, PRODUCTS
from src.core.state import get_state
from src.core.grid import get_inbound_cell
from src.entities import uav
from src.entities.base import close3


def update_uav() -> None:
    """Update UAV state and position."""
    state = get_state()
    
    if uav.state == "idle":
        if state.uav_scan_queue:
            uav.state = "to_inbound"

    elif uav.state == "to_inbound":
        inbound = get_inbound_cell()
        target = (inbound[0], inbound[1], 3.2)
        _move_uav_towards(target)
        if close3(uav.pos, target):
            uav.state = "scanning"
            uav.scan_ticks = 30

    elif uav.state == "scanning":
        uav.scan_ticks -= 1
        if uav.scan_ticks <= 0 and state.uav_scan_queue:
            qty = state.uav_scan_queue.popleft()
            product = random.choice(PRODUCTS)
            state.event_log.appendleft(
                f"БВС распознал товар без метки как {product}, количество {qty}"
            )

            from src.entities import robots
            has_robot = any(product in r.products for r in robots)
            if not has_robot:
                state.event_log.appendleft(f"⚠ ВНИМАНИЕ: нет РТС, способного возить {product}!")
            
            for _ in range(qty):
                state.stock_total[product] += 1
                state.robot_task_queues[product].append(
                    {"type": "putaway", "product": product, "source": "unlabeled"}
                )

            uav.state = "to_home"
            if state.uav_scan_queue:
                uav.state = "to_inbound"

    elif uav.state == "to_home":
        if state.uav_scan_queue:
            uav.state = "to_inbound"
        else:
            _move_uav_towards(UAV_HOME_POS)
            if close3(uav.pos, UAV_HOME_POS):
                uav.state = "idle"


def _move_uav_towards(target) -> None:
    """Move UAV towards target position."""
    vec = np.array(target, dtype=float) - np.array(uav.pos, dtype=float)
    dist = np.linalg.norm(vec)
    if dist <= AGENT_SPEED or dist == 0:
        uav.pos[0], uav.pos[1], uav.pos[2] = target
    else:
        vec = vec / dist
        uav.pos[0] += vec[0] * AGENT_SPEED
        uav.pos[1] += vec[1] * AGENT_SPEED
        uav.pos[2] += vec[2] * AGENT_SPEED
