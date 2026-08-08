from config import UAV_HOME_POS


class UAV:
    def __init__(self):
        self.pos = [
            float(UAV_HOME_POS[0]),
            float(UAV_HOME_POS[1]),
            float(UAV_HOME_POS[2])
        ]
        self.state = "idle"
        self.scan_ticks = 0
        self.uav_color = None  # custom color override; None/white = material color

    def reset(self):
        self.__init__()


uav = UAV()
