import asyncio
import json


def fire_and_forget(factory):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return
    asyncio.create_task(factory())


def _with_traceparent(msg: dict) -> dict:
    """Embed the current span's W3C traceparent so the agent side can nest its
    handling span under the backend WS span (distributed trace)."""
    try:
        from obs import w3c_traceparent
        tp = w3c_traceparent()
    except Exception:
        tp = None
    if not tp:
        return msg
    out = dict(msg)
    out.setdefault("traceparent", tp)
    return out


class AgentRegistry:
    def __init__(self):
        self.spare_robot_ws = []
        self.robot_agents = {}
        self.agent_robot = {}
        self.uav_ws = None

    def has_spare(self) -> bool:
        return len(self.spare_robot_ws) > 0

    def pop_spare(self):
        return self.spare_robot_ws.pop(0)

    def add_spare(self, ws):
        if ws not in self.spare_robot_ws:
            self.spare_robot_ws.append(ws)

    def assign(self, robot_id, ws):
        old = self.agent_robot.get(ws)
        if old is not None:
            self.robot_agents.pop(old, None)
        if ws in self.spare_robot_ws:
            self.spare_robot_ws.remove(ws)
        self.robot_agents[robot_id] = ws
        self.agent_robot[ws] = robot_id

    def release_robot(self, robot_id):
        ws = self.robot_agents.pop(robot_id, None)
        if ws is None:
            ws = self.agent_robot.get(robot_id)
        if ws is not None:
            self.agent_robot.pop(ws, None)
            if ws not in self.spare_robot_ws:
                self.spare_robot_ws.append(ws)
        return ws

    def remove_ws(self, ws):
        rid = self.agent_robot.pop(ws, None)
        if rid is not None:
            self.robot_agents.pop(rid, None)
        if ws in self.spare_robot_ws:
            self.spare_robot_ws.remove(ws)
        if self.uav_ws == ws:
            self.uav_ws = None

    async def send_robot(self, robot_id, msg) -> bool:
        ws = self.robot_agents.get(robot_id)
        if ws is None:
            return False
        try:
            await ws.send_text(json.dumps(_with_traceparent(msg), ensure_ascii=False))
            return True
        except Exception:
            self.remove_ws(ws)
            return False

    async def send_uav(self, msg) -> bool:
        ws = self.uav_ws
        if ws is None:
            return False
        try:
            await ws.send_text(json.dumps(_with_traceparent(msg), ensure_ascii=False))
            return True
        except Exception:
            self.uav_ws = None
            return False


agent_registry = AgentRegistry()
