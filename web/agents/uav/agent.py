import asyncio
import json
import os
import random

import websockets

import observe

observe.init()

PLANNER_WS = os.getenv("PLANNER_WS", "ws://backend:8000/agent/ws/uav")
TICK = 0.05
AGENT_SPEED = 0.25
UAV_HOME_POS = [7.0, 5.0, 4.5]
UAV_SCAN_ALTITUDE = 3.2
SCAN_DURATION_TICKS = 30
PRODUCTS = ["metal", "plastic", "electronics", "wood", "glass"]


def _move_towards3(pos, target, speed):
    dx = target[0] - pos[0]
    dy = target[1] - pos[1]
    dz = target[2] - pos[2]
    dist = (dx * dx + dy * dy + dz * dz) ** 0.5
    if dist <= speed or dist == 0:
        return [float(target[0]), float(target[1]), float(target[2])]
    k = speed / dist
    return [pos[0] + dx * k, pos[1] + dy * k, pos[2] + dz * k]


def _close3(a, b, eps=0.15):
    return (abs(a[0] - b[0]) < eps and abs(a[1] - b[1]) < eps
            and abs(a[2] - b[2]) < eps)


class UAVAgent:
    def __init__(self):
        self.pos = list(UAV_HOME_POS)
        self.state = "idle"
        self.scan_ticks = 0
        self.target = None
        self.scan_qty = 0
        self.pending_scan_done = None

    def handle(self, msg):
        cmd = msg.get("cmd")
        if cmd == "scan":
            self.scan_qty = int(msg.get("qty", 0))
            inbound = msg.get("inbound", [1, 1])
            self.target = (float(inbound[0]), float(inbound[1]), UAV_SCAN_ALTITUDE)
            if self.state == "idle":
                self.state = "to_inbound"

    def step(self):
        if self.state == "to_inbound":
            if self.target is None:
                self.state = "idle"
                return
            self.pos = _move_towards3(self.pos, self.target, AGENT_SPEED)
            if _close3(self.pos, self.target):
                self.state = "scanning"
                self.scan_ticks = SCAN_DURATION_TICKS
        elif self.state == "scanning":
            self.scan_ticks -= 1
            if self.scan_ticks <= 0:
                self.pending_scan_done = {
                    "type": "scan_done",
                    "qty": self.scan_qty,
                    "product": random.choice(PRODUCTS),
                }
                self.scan_qty = 0
                self.target = None
                self.state = "to_home"
        elif self.state == "to_home":
            self.pos = _move_towards3(self.pos, UAV_HOME_POS, AGENT_SPEED)
            if _close3(self.pos, UAV_HOME_POS):
                self.pos = list(UAV_HOME_POS)
                self.state = "idle"

    def pending_messages(self):
        out = []
        if self.pending_scan_done:
            out.append(self.pending_scan_done)
            self.pending_scan_done = None
        out.append({
            "type": "telemetry",
            "pos": [round(x, 3) for x in self.pos],
            "state": self.state,
            "scan_ticks": self.scan_ticks,
        })
        return out


async def run():
    while True:
        agent = UAVAgent()
        incoming = asyncio.Queue()

        async def reader(ws):
            async for raw in ws:
                incoming.put_nowait(json.loads(raw))

        try:
            async with websockets.connect(PLANNER_WS, ping_interval=20, ping_timeout=20) as ws:
                reader_task = asyncio.create_task(reader(ws))
                while True:
                    if reader_task.done() and reader_task.exception() is not None:
                        raise reader_task.exception()
                    while not incoming.empty():
                        m = incoming.get_nowait()
                        cmd = m.get("cmd")
                        if cmd:
                            with observe.span(f"uav.cmd.{cmd}",
                                              parent_ctx=observe.extract_traceparent(m)):
                                agent.handle(m)
                        else:
                            agent.handle(m)
                    agent.step()
                    for m in agent.pending_messages():
                        mtype = m.get("type")
                        if mtype != "telemetry":
                            with observe.span(f"uav.send.{mtype}"):
                                tp = observe.w3c_traceparent()
                                if tp:
                                    m["traceparent"] = tp
                        await ws.send(json.dumps(m, ensure_ascii=False))
                    await asyncio.sleep(TICK)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            print(f"[uav-agent] connection error: {exc}")
            await asyncio.sleep(2.0)


if __name__ == "__main__":
    asyncio.run(run())
