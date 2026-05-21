"""UAV entity module."""

from src.config import UAV_HOME_POS


class UAV:
    """Unmanned Aerial Vehicle (БВС) for scanning unlabeled deliveries."""
    
    def __init__(self):
        self.pos = [
            float(UAV_HOME_POS[0]),
            float(UAV_HOME_POS[1]),
            float(UAV_HOME_POS[2])
        ]
        self.state = "idle"
        self.scan_ticks = 0


# Global UAV instance
uav = UAV()
