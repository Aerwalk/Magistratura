"""Robot entity module."""

from typing import Optional

from src.config import ROBOT_CONFIG, AGENT_SPEED


class Robot:
    """Ground robot (РТС) for material transport."""
    
    def __init__(self, idx: int, config: dict):
        home = config["home"]
        self.id = idx
        self.product = config["product"]
        self.color = config["color"]
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

    def is_moving(self) -> bool:
        """Check if robot is currently moving."""
        return self.current_target is not None

    def is_active(self) -> bool:
        """Check if robot has active task or movement."""
        return self.current_target is not None or self.wait_ticks > 0 or self.route

    def check_stuck(self) -> bool:
        """Check if robot is stuck (not moving for too long)."""
        if self.pos == self.last_pos and self.is_active():
            self.stuck_ticks += 1
            if self.stuck_ticks > 100:
                return True
        else:
            self.stuck_ticks = 0
            self.last_pos = self.pos
        return False

    def reset(self) -> None:
        """Reset robot to home position."""
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


# Global robots list
robots = [Robot(idx, cfg) for idx, cfg in enumerate(ROBOT_CONFIG)]
