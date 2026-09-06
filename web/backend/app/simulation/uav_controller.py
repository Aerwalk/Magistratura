from core.state import get_state
from core.grid import get_inbound_cell
from entities import uav
from agent_registry import agent_registry, fire_and_forget


def update_uav() -> None:
    state = get_state()
    if agent_registry.uav_ws is None:
        return
    if uav.state == "idle" and state.uav_scan_queue:
        qty = state.uav_scan_queue.popleft()
        inbound = get_inbound_cell()
        fire_and_forget(lambda: agent_registry.send_uav({
            "cmd": "scan",
            "qty": qty,
            "inbound": [int(inbound[0]), int(inbound[1])],
        }))
