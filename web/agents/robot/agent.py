import asyncio
import json
import os
import time

import websockets

import observe

observe.init()

PLANNER_WS = os.getenv("PLANNER_WS", "ws://backend:8000/agent/ws/robot")
TICK = 0.05
AGENT_SPEED = 0.25
BATTERY_DRAIN_MOVING = 0.45
BATTERY_DRAIN_IDLE = 0.09
BATTERY_CHARGE_RATE = 1.0
BATTERY_FAIL_MAX = 60.0
BATTERY_MAX_DEGRADE_PER_FULL_CHARGE = 1.0


def _move_towards(pos, target, speed):
    dx = target[0] - pos[0]
    dy = target[1] - pos[1]
    dist = (dx * dx + dy * dy) ** 0.5
    if dist <= speed or dist == 0:
        return [float(target[0]), float(target[1])]
    return [pos[0] + dx / dist * speed, pos[1] + dy / dist * speed]


def _close(a, b, eps=0.05):
    return abs(a[0] - b[0]) < eps and abs(a[1] - b[1]) < eps


class RobotAgent:
    def __init__(self):
        self.robot_id = None
        self.home = [0.0, 0.0]
        self.speed = AGENT_SPEED
        self.pos = [0.0, 0.0]
        self.draw_pos = [0.0, 0.0]
        self.route = []
        self.wait_ticks = 0
        self.charging = False
        self.charging_ticks = 0
        self.battery_at_charge_start = 0.0
        self.charging_start_ts = None
        self.battery = 100.0
        self.battery_max = 100.0
        self.ready_pending = False
        self.arrived_pending = False
        self.charge_end_pending = None
        self._progress_pending = False
        self._last_progress_battery = 0
        self._last_route_len = None
        self._last_charging = None
        self._last_ready_at = None

    def handle(self, msg):
        cmd = msg.get("cmd")
        if cmd == "assign":
            self.robot_id = msg["robot_id"]
            self.home = [float(x) for x in msg["home"]]
            self.speed = float(msg.get("speed", AGENT_SPEED))
            self.pos = list(self.home)
            self.draw_pos = list(self.home)
            self.route = []
            self.wait_ticks = 0
            self.charging = False
            self.charging_ticks = 0
            self.battery_at_charge_start = 0.0
            self.charging_start_ts = None
            self.battery = float(msg.get("battery", 100.0))
            self.battery_max = float(msg.get("battery_max", 100.0))
            self.ready_pending = True
            print(f"[robot-agent] info: assigned robot_id={self.robot_id} home={self.home} "
                  f"speed={self.speed} battery={self.battery:.1f} battery_max={self.battery_max:.1f}")
        elif cmd == "route":
            self.route = [[float(x), float(y)] for x, y in msg["route"]]
            self.charging = False
            self.charging_start_ts = None
            self.wait_ticks = 0
            self._last_route_len = len(self.route)
            print(f"[robot-agent] info: route_len={len(self.route)}")
        elif cmd == "start_charging":
            self.charging = True
            self.charging_ticks = 0
            self.battery_at_charge_start = self.battery
            self.charging_start_ts = time.time()
            self.route = []
            self._last_progress_battery = int(self.battery)
            self._progress_pending = False
            print(f"[robot-agent] info: charging_start battery={round(self.battery, 1)}")
        elif cmd == "replace_battery":
            self.battery = 100.0
            self.battery_max = 100.0
            self.charging = False
            self.charging_ticks = 0
            self.charging_start_ts = None
            self._last_progress_battery = 0
            self._progress_pending = False
            print("[robot-agent] info: battery replaced")
        elif cmd == "reset":
            if "home" in msg:
                self.home = [float(x) for x in msg["home"]]
            self.pos = list(self.home)
            self.draw_pos = list(self.home)
            self.route = []
            self.wait_ticks = 0
            self.charging = False
            self.charging_ticks = 0
            self.charging_start_ts = None
            self._last_progress_battery = 0
            self._progress_pending = False
            print("[robot-agent] info: reset")
        elif cmd == "stop":
            self.route = []
            self.wait_ticks = 0
            self.charging = False
            self.charging_ticks = 0
            self.charging_start_ts = None
            self._last_progress_battery = 0
            self._progress_pending = False
            print("[robot-agent] info: stop")
        elif cmd == "set_home":
            self.home = [float(x) for x in msg["home"]]
        elif cmd == "set_speed":
            self.speed = max(0.01, min(1.0, float(msg.get("speed", AGENT_SPEED))))

    def step(self):
        if self.charging:
            self.battery = min(self.battery_max, self.battery + BATTERY_CHARGE_RATE * TICK)
            self.charging_ticks += 1
            if int(self.battery) > self._last_progress_battery:
                self._last_progress_battery = int(self.battery)
                self._progress_pending = True
            if self.battery >= self.battery_max - 1e-6:
                self._finish_charging()
            return
        drain = BATTERY_DRAIN_MOVING if self.route else BATTERY_DRAIN_IDLE
        self.battery = max(0.0, self.battery - drain * TICK)
        if self.wait_ticks > 0:
            self.wait_ticks -= 1
            return
        if not self.route:
            return
        target = self.route[0]
        self.draw_pos = _move_towards(self.draw_pos, target, self.speed)
        if _close(self.draw_pos, target):
            self.draw_pos = [float(target[0]), float(target[1])]
            self.pos = [float(target[0]), float(target[1])]
            self.route.pop(0)
            self.wait_ticks = 2
            if not self.route:
                self.arrived_pending = True

    def _finish_charging(self):
        duration_sec = round(self.charging_ticks * TICK, 1)
        battery_from = round(self.battery_at_charge_start, 1)
        battery_to = round(self.battery, 1)
        depth = max(0.0, (battery_to - battery_from) / 100.0)
        degrade = depth * BATTERY_MAX_DEGRADE_PER_FULL_CHARGE
        new_max = max(BATTERY_FAIL_MAX, self.battery_max - degrade)
        self.charge_end_pending = {
            "duration_sec": duration_sec,
            "battery_from": battery_from,
            "battery_to": battery_to,
            "battery_max_before": round(self.battery_max, 2),
            "battery_max_after": round(new_max, 2),
        }
        self.battery_max = new_max
        self.battery = new_max
        self.charging = False
        self.charging_ticks = 0
        self.charging_start_ts = None

    def telemetry(self):
        return {
            "type": "telemetry",
            "robot_id": self.robot_id,
            "pos": [round(x, 3) for x in self.draw_pos],
            "battery": round(self.battery, 3),
            "battery_max": round(self.battery_max, 3),
            "charging": self.charging,
            "moving": bool(self.route and not self.charging and self.wait_ticks <= 0),
            "speed": round(self.speed, 3),
        }

    def pending_messages(self):
        out = []
        if self.ready_pending:
            self.ready_pending = False
            out.append({"type": "ready", "robot_id": self.robot_id})
            print(f"[robot-agent] info: ready robot_id={self.robot_id}")
        if self.arrived_pending:
            self.arrived_pending = False
            out.append({"type": "arrived", "robot_id": self.robot_id,
                        "pos": [round(x, 3) for x in self.pos]})
            print(f"[robot-agent] info: arrived pos={[round(x, 3) for x in self.pos]}")
        if self._progress_pending:
            self._progress_pending = False
            span = max(1e-9, self.battery_max - self.battery_at_charge_start)
            out.append({"type": "charging_progress", "robot_id": self.robot_id,
                        "payload": {
                            "battery": round(self.battery, 2),
                            "battery_max": round(self.battery_max, 2),
                            "progress_pct": round((self.battery - self.battery_at_charge_start) / span * 100.0, 1),
                            "remaining_sec": round(max(0.0, (self.battery_max - self.battery) / BATTERY_CHARGE_RATE), 1),
                            "elapsed_sec": round(self.charging_ticks * TICK, 1),
                        }})
        if self.charge_end_pending:
            pending = dict(self.charge_end_pending)
            out.append({"type": "charge_end", "robot_id": self.robot_id,
                        "payload": self.charge_end_pending})
            self.charge_end_pending = None
            print(f"[robot-agent] info: charging complete "
                  f"battery_from={pending['battery_from']} "
                  f"battery_to={pending['battery_to']} "
                  f"battery_max_after={pending['battery_max_after']}")
        if self.robot_id is not None:
            out.append(self.telemetry())
        return out

    def log_heartbeat(self):
        state = "charging" if self.charging else ("moving" if self.route else "idle")
        print(f"[robot-agent] info: heartbeat robot_id={self.robot_id} state={state} "
              f"battery={round(self.battery, 1)} "
              f"pos={[round(x, 1) for x in self.pos]} "
              f"route_left={len(self.route)}")


async def run():
    while True:
        agent = RobotAgent()
        incoming = asyncio.Queue()

        async def reader(ws):
            async for raw in ws:
                incoming.put_nowait(json.loads(raw))

        try:
            async with websockets.connect(PLANNER_WS, ping_interval=20, ping_timeout=20) as ws:
                reader_task = asyncio.create_task(reader(ws))
                heartbeat_ticks = 0
                while True:
                    if reader_task.done() and reader_task.exception() is not None:
                        raise reader_task.exception()
                    heartbeat_ticks += 1
                    if heartbeat_ticks >= 600 and agent.robot_id is not None:
                        heartbeat_ticks = 0
                        agent.log_heartbeat()
                    while not incoming.empty():
                        m = incoming.get_nowait()
                        cmd = m.get("cmd")
                        if cmd:
                            with observe.span(f"robot.cmd.{cmd}",
                                              robot_id=agent.robot_id,
                                              parent_ctx=observe.extract_traceparent(m)):
                                agent.handle(m)
                        else:
                            agent.handle(m)
                    agent.step()
                    for m in agent.pending_messages():
                        mtype = m.get("type")
                        if mtype != "telemetry":
                            with observe.span(f"robot.send.{mtype}", robot_id=agent.robot_id):
                                tp = observe.w3c_traceparent()
                                if tp:
                                    m["traceparent"] = tp
                        await ws.send(json.dumps(m, ensure_ascii=False))
                    await asyncio.sleep(TICK)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            print(f"[robot-agent] error: connection error: {exc}")
            await asyncio.sleep(2.0)


if __name__ == "__main__":
    asyncio.run(run())
