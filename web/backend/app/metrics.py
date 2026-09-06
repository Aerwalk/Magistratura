"""Prometheus metrics for MagSim warehouse simulation.

Exposes robot state (battery, speed, phase, loading, stuck), fleet behaviour
(visits, tasks, distance), warehouse KPIs (stock, demand, queues) — everything
needed to build Grafana dashboards and alerting.
"""

from prometheus_client import Gauge, Counter, Info, generate_latest, CONTENT_TYPE_LATEST

import time as _time

from entities.robot import robots

# ─── Robot battery ───
battery_gauge = Gauge(
    "magsim_robot_battery_percent",
    "Current battery level of a robot (%)",
    ["robot_id", "name", "product"],
)
battery_max_gauge = Gauge(
    "magsim_robot_battery_max_percent",
    "Maximum (degraded) battery capacity of a robot (%)",
    ["robot_id", "name", "product"],
)
battery_degradation_gauge = Gauge(
    "magsim_robot_battery_degradation_percent",
    "Battery degradation as 100 - battery_max (%)",
    ["robot_id", "name", "product"],
)
charging_gauge = Gauge(
    "magsim_robot_charging",
    "1 if robot is currently charging, else 0",
    ["robot_id"],
)
battery_replaced_counter = Counter(
    "magsim_robot_battery_replaced_total",
    "Battery replacement events per robot",
    ["robot_id"],
)
charge_sessions_counter = Counter(
    "magsim_robot_charge_sessions_total",
    "Completed charge sessions per robot",
    ["robot_id"],
)

# ─── Robot activity ───
robot_speed_gauge = Gauge(
    "magsim_robot_speed",
    "Current speed of the robot (cells/sec); 0 when idle/charging/stuck",
    ["robot_id", "name"],
)
robot_loaded_gauge = Gauge(
    "magsim_robot_loaded",
    "1 if the robot currently carries goods, else 0",
    ["robot_id"],
)
robot_phase_gauge = Gauge(
    "magsim_robot_phase",
    "1 if the robot is in the given phase, else 0",
    ["robot_id", "phase"],
)
robot_info = Info(
    "magsim_robot_info",
    "Static + dynamic attributes of each robot (home, position, phase, task).",
    ["robot_id"],
)

# ─── Fleet behaviour ───
movement_counter = Counter(
    "magsim_robot_cell_visits_total",
    "Number of times a robot arrived at a grid cell (heatmap for bottlenecks)",
    ["robot_id", "cell", "x", "y"],
)
distance_counter = Counter(
    "magsim_robot_distance_moved_total",
    "Distance travelled by a robot in cells",
    ["robot_id"],
)
task_counter = Counter(
    "magsim_robot_tasks_completed_total",
    "Completed putaway/retrieve/rebalance tasks",
    ["robot_id", "task_type"],
)
task_assigned_counter = Counter(
    "magsim_robot_tasks_assigned_total",
    "Tasks bound to a robot",
    ["robot_id", "task_type"],
)

# ─── Stuck detection ───
robot_stuck_gauge = Gauge(
    "magsim_robot_stuck",
    "1 while the robot is stuck (>30s without moving, not at its home station)",
    ["robot_id", "name", "pos"],
)
robot_stuck_events_counter = Counter(
    "magsim_robot_stuck_events_total",
    "Number of times a robot was detected as stuck",
    ["robot_id", "name"],
)

# ─── Warehouse KPIs ───
warehouse_stock_gauge = Gauge(
    "magsim_warehouse_stock_total",
    "Total received stock per product",
    ["product"],
)
warehouse_on_shelves_gauge = Gauge(
    "magsim_warehouse_stock_on_shelves",
    "Units of product currently stored on shelves",
    ["product"],
)
warehouse_delivered_gauge = Gauge(
    "magsim_warehouse_delivered_total",
    "Units delivered to the exit (retrieved & shipped)",
    ["product"],
)
warehouse_retrieved_gauge = Gauge(
    "magsim_warehouse_retrieved_total",
    "Units taken from shelves for retrieval",
    ["product"],
)
warehouse_demand_gauge = Gauge(
    "magsim_warehouse_demand",
    "Accumulated demand per product",
    ["product"],
)
warehouse_queue_gauge = Gauge(
    "magsim_warehouse_task_queue",
    "Pending tasks in queue per product",
    ["product"],
)
rebalance_gauge = Gauge(
    "magsim_warehouse_rebalance_active",
    "1 while a warehouse rebalance is in progress",
    [],
)

# ─── Stack health ───
_START_TIME = _time.time()
health_database_connected = Gauge(
    "magsim_health_database_connected",
    "1 if the timescale database is enabled and connected, else 0",
    [],
)
health_agents_connected = Gauge(
    "magsim_health_agents_connected",
    "Number of robot agents currently connected via WebSocket",
    [],
)
health_robots_ready = Gauge(
    "magsim_health_robots_ready",
    "Number of robots whose agent reported ready",
    [],
)
health_uav_connected = Gauge(
    "magsim_health_uav_connected",
    "1 if the UAV agent is connected, else 0",
    [],
)
health_sim_ticks_total = Counter(
    "magsim_health_sim_ticks_total",
    "Simulation ticks processed since start (rate ~ detects a dead loop)",
    [],
)
health_last_tick_timestamp = Gauge(
    "magsim_health_last_tick_timestamp",
    "Unix time of the most recent simulation tick",
    [],
)
health_uptime_seconds = Gauge(
    "magsim_health_uptime_seconds",
    "Backend process uptime in seconds",
    [],
)

# ─── Automated test results ───
tests_last_result = Gauge(
    "magsim_tests_last_result",
    "Latest outcome per test/scenario name (1 = pass, 0 = fail)",
    ["suite", "name"],
)
tests_runs_total = Counter(
    "magsim_tests_runs_total",
    "Total automated test runs executed",
    ["suite"],
)
tests_failed_total = Counter(
    "magsim_tests_failed_total",
    "Total failed tests/scenarios across runs",
    ["suite"],
)
tests_last_run_timestamp = Gauge(
    "magsim_tests_last_run_timestamp",
    "Unix time of the most recent test run",
    ["suite"],
)


# ─── Recording helpers ───

def record_cell_visit(robot_id: int, cell) -> None:
    movement_counter.labels(
        robot_id=str(robot_id),
        cell="({},{})".format(int(cell[0]), int(cell[1])),
        x=str(int(cell[0])),
        y=str(int(cell[1])),
    ).inc()


def record_distance_moved(robot_id: int, cells: float) -> None:
    if cells > 0:
        distance_counter.labels(robot_id=str(robot_id)).inc(cells)


def record_task_completed(robot_id: int, task_type: str) -> None:
    task_counter.labels(robot_id=str(robot_id), task_type=task_type).inc()


def record_task_assigned(robot_id: int, task_type: str) -> None:
    task_assigned_counter.labels(robot_id=str(robot_id), task_type=task_type).inc()


def record_stuck_event(robot) -> None:
    robot_stuck_events_counter.labels(robot_id=str(robot.id), name=robot.name).inc()


def record_battery_replaced(robot) -> None:
    battery_replaced_counter.labels(robot_id=str(robot.id)).inc()


def record_charge_session(robot) -> None:
    charge_sessions_counter.labels(robot_id=str(robot.id)).inc()


def clear_robot(rid: int) -> None:
    """Drop all label series belonging to a removed robot."""
    rid_s = str(rid)
    metric_objs = [
        battery_gauge, battery_max_gauge, battery_degradation_gauge, charging_gauge,
        battery_replaced_counter, charge_sessions_counter, robot_speed_gauge,
        robot_loaded_gauge, robot_phase_gauge, robot_info, movement_counter,
        distance_counter, task_counter, task_assigned_counter, robot_stuck_gauge,
        robot_stuck_events_counter,
    ]
    for m in metric_objs:
        for label_tuple in list(m._metrics.keys()):
            if label_tuple and label_tuple[0] == rid_s:
                try:
                    m.remove(*label_tuple)
                except KeyError:
                    pass


def record_sim_tick(now: float) -> None:
    health_sim_ticks_total.inc()
    health_last_tick_timestamp.set(now)


def record_health(now: float) -> None:
    try:
        from db import is_enabled
        health_database_connected.set(1.0 if is_enabled() else 0.0)
    except Exception:
        health_database_connected.set(0.0)
    connected = 0
    ready = 0
    for r in robots:
        if getattr(r, "agent_ws", None) is not None:
            connected += 1
        if getattr(r, "agent_ready", False):
            ready += 1
    health_agents_connected.set(connected)
    health_robots_ready.set(ready)
    try:
        from agent_registry import agent_registry
        health_uav_connected.set(1.0 if agent_registry.uav_ws is not None else 0.0)
    except Exception:
        health_uav_connected.set(0.0)
    health_uptime_seconds.set(max(0.0, now - _START_TIME))


def record_test_results(payload: dict) -> None:
    if not isinstance(payload, dict):
        return
    now = _time.time()
    suite_specs = [("unit", payload.get("tests")), ("scenario", payload.get("scenarios"))]
    for suite_label, data in suite_specs:
        if data is None:
            continue
        if suite_label == "unit" and isinstance(data, dict):
            items = data.get("tests") or []
            outcomes = []
            names = []
            for t in items:
                names.append(t.get("name", "?"))
                outcomes.append(1 if t.get("passed") else 0)
        elif isinstance(data, list):
            names = [s.get("name", "?") for s in data]
            outcomes = [1 if s.get("passed") else 0 for s in data]
        else:
            continue
        for n, ok in zip(names, outcomes):
            tests_last_result.labels(suite=suite_label, name=n).set(ok)
        tests_runs_total.labels(suite=suite_label).inc()
        tests_failed_total.labels(suite=suite_label).inc(sum(1 for o in outcomes if o == 0))
        tests_last_run_timestamp.labels(suite=suite_label).set(now)
    if payload.get("error"):
        tests_last_result.labels(suite="runner", name="_error").set(0)
        tests_runs_total.labels(suite="runner").inc()
        tests_failed_total.labels(suite="runner").inc()
        tests_last_run_timestamp.labels(suite="runner").set(now)


# ─── Full-state recording (called on every /metrics scrape) ───

_PHASES = [
    "idle", "charging", "to_home", "to_home_charge", "return_home",
    "to_pickup_zone", "to_shelf_for_put", "to_shelf_for_pick",
    "to_exit", "rebalance_pick", "rebalance_put",
]


def record_robot(r) -> None:
    labels = (str(r.id), str(r.name), str(r.product))
    battery_gauge.labels(*labels).set(r.battery)
    battery_max_gauge.labels(*labels).set(r.battery_max)
    battery_degradation_gauge.labels(*labels).set(max(0.0, 100.0 - r.battery_max))
    charging_gauge.labels(robot_id=str(r.id)).set(1.0 if r.phase == "charging" else 0.0)
    speed = r.speed if (r.is_moving() or r.route or r.phase not in ("idle", "charging")) else 0.0
    robot_speed_gauge.labels(robot_id=str(r.id), name=r.name).set(speed)
    robot_loaded_gauge.labels(robot_id=str(r.id)).set(
        1.0 if (r.carry is not None or (r.carry_qty or 0) > 0) else 0.0
    )
    for ph in _PHASES:
        robot_phase_gauge.labels(robot_id=str(r.id), phase=ph).set(1.0 if r.phase == ph else 0.0)
    robot_info.labels(robot_id=str(r.id)).info({
        "name": r.name,
        "product": str(r.product),
        "home": "({},{})".format(int(r.home[0]), int(r.home[1])),
        "pos": "({},{})".format(int(r.pos[0]), int(r.pos[1])),
        "phase": r.phase,
        "carry": str(r.carry or ""),
        "carry_qty": str(r.carry_qty or 0),
        "capacity": str(r.capacity),
        "charging": str(r.phase == "charging").lower(),
        "stuck": str(getattr(r, "stuck_alert_raised", False)).lower(),
    })
    stuck = bool(getattr(r, "stuck_alert_raised", False))
    robot_stuck_gauge.labels(
        robot_id=str(r.id), name=r.name,
        pos="({},{})".format(int(r.pos[0]), int(r.pos[1])),
    ).set(1.0 if stuck else 0.0)


def record_warehouse(state) -> None:
    on_shelves: dict[str, int] = {}
    for shelf, info in state.shelf_state.items():
        product = info.get("product")
        if product:
            on_shelves[str(product)] = on_shelves.get(str(product), 0) + int(info["count"])
    for p in state.stock_total:
        warehouse_stock_gauge.labels(product=str(p)).set(state.stock_total.get(p, 0))
    for p in on_shelves:
        warehouse_on_shelves_gauge.labels(product=str(p)).set(on_shelves[p])
    for p in state.delivered_total:
        warehouse_delivered_gauge.labels(product=str(p)).set(state.delivered_total.get(p, 0))
    for p in state.retrieved_total:
        warehouse_retrieved_gauge.labels(product=str(p)).set(state.retrieved_total.get(p, 0))
    for p in state.demand:
        warehouse_demand_gauge.labels(product=str(p)).set(state.demand.get(p, 0))
    for p, q in state.robot_task_queues.items():
        warehouse_queue_gauge.labels(product=str(p)).set(len(q))
    rebalance_gauge.set(1.0 if state.rebalance_active else 0.0)


def render_prometheus() -> tuple[str, str]:
    from core.state import get_state
    for r in robots:
        record_robot(r)
    try:
        record_warehouse(get_state())
    except Exception:
        pass
    record_health(_time.time())
    return generate_latest().decode("utf-8"), CONTENT_TYPE_LATEST