"""TimescaleDB integration: telemetry/log ingest, queries, battery forecasts,
plus a best-effort Loki sink for Grafana Logs Drilldown.

The stores are optional: if TimescaleDB or Loki are unreachable the
simulation keeps running and data is simply dropped.
"""

import asyncio
import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

DSN = os.getenv("DATABASE_URL", "postgresql://magsim:magsim@timescale:5432/magsim")
LOKI_URL = os.getenv("LOKI_URL", "http://loki:3100")
LOKI_SERVICE = os.getenv("LOKI_SERVICE_NAME", "magsim-backend")
FLUSH_INTERVAL = float(os.getenv("TELEMETRY_FLUSH_SECONDS", "5"))
LOKI_FLUSH_INTERVAL = float(os.getenv("LOKI_FLUSH_SECONDS", "2"))
MAX_BATCH = 5000

_pool = None
_enabled = False

_telemetry_queue = asyncio.Queue(maxsize=100000)
_log_queue = asyncio.Queue(maxsize=100000)
_charge_queue = asyncio.Queue(maxsize=100000)
_loki_queue = asyncio.Queue(maxsize=100000)

_TELEMETRY_COLUMNS = [
    "time", "robot_id", "x", "y", "phase",
    "battery", "battery_max", "charging", "speed", "task_type",
]

_INSERT_LOG = """
    INSERT INTO robot_logs (time, robot_id, level, event, payload)
    VALUES ($1, $2, $3, $4, $5::jsonb)
"""

_INSERT_CHARGE = """
    INSERT INTO robot_charge_sessions
        (robot_id, start_ts, end_ts, duration_sec, battery_from, battery_to, battery_max_after)
    VALUES ($1, $2, $3, $4, $5, $6, $7)
"""

_SCHEMA_PATH = Path(__file__).parent / "schema.sql"
_BUCKET_RE = re.compile(r"^\d+ (second|minute|hour|day)s?$")


def is_enabled() -> bool:
    return _enabled


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def init(forever: bool = False):
    global _pool, _enabled
    import asyncpg
    while True:
        try:
            pool = await asyncpg.create_pool(DSN, min_size=1, max_size=4, timeout=10)
            await _apply_schema(pool)
            _pool = pool
            _enabled = True
            print("[db] TimescaleDB connected")
            return
        except Exception as exc:
            _pool = None
            _enabled = False
            print(f"[db] TimescaleDB unavailable: {exc}")
            if not forever:
                return
            await asyncio.sleep(10)


async def close():
    global _pool, _enabled
    if _pool is not None:
        try:
            await _pool.close()
        except Exception:
            pass
    _pool = None
    _enabled = False


async def _apply_schema(pool):
    sql = _SCHEMA_PATH.read_text(encoding="utf-8")
    statements = [s.strip() for s in sql.split(";") if s.strip()]
    async with pool.acquire() as conn:
        for stmt in statements:
            await conn.execute(stmt)
        is_ht = await conn.fetchval(
            "SELECT count(*) FROM timescaledb_information.hypertables "
            "WHERE hypertable_name = 'robot_telemetry'"
        )
        if not is_ht:
            await conn.execute("SELECT create_hypertable('robot_telemetry', 'time')")
        exists = await conn.fetchval("SELECT to_regclass('telemetry_hourly')")
        if exists is None:
            try:
                await conn.execute(
                    """
                    CREATE MATERIALIZED VIEW telemetry_hourly
                    WITH (timescaledb.continuous) AS
                    SELECT time_bucket('5 minutes', time) AS bucket, robot_id,
                           avg(battery) AS battery_avg,
                           min(battery) AS battery_min,
                           avg(battery_max) AS battery_max_avg
                    FROM robot_telemetry
                    GROUP BY bucket, robot_id
                    """
                )
            except Exception as exc:
                print(f"[db] continuous aggregate skipped: {exc}")


async def writer_loop():
    while True:
        await asyncio.sleep(FLUSH_INTERVAL)
        try:
            await flush_once()
        except Exception as exc:
            print(f"[db] flush error: {exc}")


async def loki_writer_loop():
    while True:
        await asyncio.sleep(LOKI_FLUSH_INTERVAL)
        try:
            await loki_flush_once()
        except Exception as exc:
            print(f"[loki] flush error: {exc}")


async def flush_once():
    if not _enabled or _pool is None:
        _discard(_telemetry_queue)
        _discard(_log_queue)
        _discard(_charge_queue)
        return
    telemetry = _drain(_telemetry_queue, MAX_BATCH)
    logs = _drain(_log_queue, MAX_BATCH)
    charges = _drain(_charge_queue, MAX_BATCH)
    if not telemetry and not logs and not charges:
        return
    try:
        async with _pool.acquire() as conn:
            if telemetry:
                await conn.copy_records_to_table(
                    "robot_telemetry", records=telemetry, columns=_TELEMETRY_COLUMNS
                )
            if logs:
                await conn.executemany(_INSERT_LOG, logs)
            if charges:
                await conn.executemany(_INSERT_CHARGE, charges)
    except Exception as exc:
        print(f"[db] flush failed, requeueing: {exc}")
        for item in telemetry:
            _put(_telemetry_queue, item)
        for item in logs:
            _put(_log_queue, item)
        for item in charges:
            _put(_charge_queue, item)


async def loki_flush_once():
    items = _drain(_loki_queue, MAX_BATCH)
    if not items:
        return
    try:
        async with _http_client() as client:
            resp = await client.post(
                f"{LOKI_URL}/loki/api/v1/push",
                json=_loki_streams(items),
                timeout=3,
                headers={"Content-Type": "application/json"},
            )
            if resp.status_code >= 400:
                print(f"[loki] push HTTP {resp.status_code}: {resp.text[:200]}")
    except Exception as exc:
        print(f"[loki] push failed: {exc}")


def _http_client():
    import httpx
    return httpx.AsyncClient()


def _loki_streams(items):
    groups = {}
    for ts, robot_id, level, text in items:
        key = (level, robot_id if robot_id is not None else "-")
        groups.setdefault(key, []).append([_ns(ts), text])
    streams = [
        {
            "stream": {
                "service_name": LOKI_SERVICE,
                "level": level,
                "robot_id": str(robot_id),
            },
            "values": values,
        }
        for (level, robot_id), values in groups.items()
    ]
    return {"streams": streams}


def _ns(dt) -> str:
    return str(int(dt.timestamp() * 1_000_000_000))


# ─── Producers (callable from sync code) ───────────────────────────────

def push_telemetry(ts, robot_id, x, y, phase, battery, battery_max, charging, speed, task_type):
    if not _enabled:
        return
    _put(_telemetry_queue, (ts, robot_id, x, y, phase, battery, battery_max,
                            bool(charging), speed, task_type))


def push_log(robot_id, level, event, payload=None):
    if payload is not None and isinstance(payload, dict) and "trace_id" not in payload:
        try:
            from obs import current_trace_id
            tid = current_trace_id()
        except Exception:
            tid = None
        if tid:
            payload = dict(payload)
            payload["trace_id"] = tid
    payload_json = json.dumps(payload, ensure_ascii=False) if payload is not None else None
    ts = _now()
    if payload_json and len(payload_json) <= 4000:
        event = f"{event} {payload_json}"
    _put(_loki_queue, (ts, robot_id, level, event))
    if _enabled:
        _put(_log_queue, (ts, robot_id, level, event, payload_json))


def push_charge_session(robot_id, start_ts, end_ts, duration_sec,
                        battery_from, battery_to, battery_max_after):
    if not _enabled:
        return
    _put(_charge_queue, (robot_id, start_ts, end_ts, duration_sec,
                         battery_from, battery_to, battery_max_after))


# ─── Queries ───────────────────────────────────────────────────────────

async def get_telemetry(robot_id, from_ts=None, to_ts=None, bucket="5 minutes", limit=2000):
    if not _enabled:
        return []
    if not _BUCKET_RE.match(bucket or ""):
        bucket = "5 minutes"
    sql = f"""
        SELECT time_bucket('{bucket}', time) AS bucket,
               avg(battery) AS battery,
               avg(battery_max) AS battery_max,
               bool_or(charging) AS charging,
               avg(speed) AS speed,
               max(x) AS x,
               max(y) AS y
        FROM robot_telemetry
        WHERE robot_id = $1
          AND ($2::timestamptz IS NULL OR time >= $2)
          AND ($3::timestamptz IS NULL OR time <= $3)
        GROUP BY bucket
        ORDER BY bucket DESC
        LIMIT $4
    """
    async with _pool.acquire() as conn:
        rows = await conn.fetch(sql, robot_id, from_ts, to_ts, limit)
    return [dict(r) for r in rows]


async def get_battery_history(hours=3, bucket="1 minute"):
    """Downsampled battery/battery_max history for the frontend dashboard."""
    if not _enabled:
        return []

    width = _bucket_to_timedelta(bucket)
    sql = """
        SELECT robot_id,
               time_bucket($2::interval, time) AS bucket,
               avg(battery) AS battery,
               avg(battery_max) AS battery_max
        FROM robot_telemetry
        WHERE time >= now() - make_interval(hours => $1::int)
        GROUP BY robot_id, bucket
        ORDER BY bucket, robot_id
    """
    async with _pool.acquire() as conn:
        rows = await conn.fetch(sql, int(hours), width)
    return [
        {
            "robot_id": r["robot_id"],
            "time": r["bucket"].isoformat(),
            "battery": round(r["battery"] or 0, 1),
            "battery_max": round(r["battery_max"] or 0, 1),
        }
        for r in rows
    ]


def _bucket_to_timedelta(bucket):
    """'1 minute' -> timedelta(minutes=1); falls back to 5 minutes."""
    m = _BUCKET_RE.match(bucket or "")
    if not m:
        bucket = "5 minutes"
    n, unit = bucket.split()
    return timedelta(**{unit + "s": int(n)})


async def count_battery_replacements():
    """Number of 'battery_replaced' log events per robot (persisted)."""
    if not _enabled:
        return {}
    sql = """
        SELECT robot_id, count(*) AS n
        FROM robot_logs
        WHERE event = 'battery_replaced'
        GROUP BY robot_id
    """
    async with _pool.acquire() as conn:
        rows = await conn.fetch(sql)
    return {r["robot_id"]: r["n"] for r in rows}


def _linreg_slope(xs, ys):
    n = len(xs)
    if n < 2:
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    den = sum((x - mx) ** 2 for x in xs)
    if den == 0:
        return None
    return num / den


async def get_predictions(window_hours=1):
    """Estimate discharge rate + battery_max degradation per robot."""
    if not _enabled:
        return []
    from config.constants import BATTERY_LOW, BATTERY_FAIL_MAX

    sql_tele = """
        SELECT robot_id,
               time_bucket('1 minute', time) AS bucket,
               avg(battery) AS battery,
               max(battery_max) AS battery_max
        FROM robot_telemetry
        WHERE time >= now() - make_interval(hours => $1)
        GROUP BY robot_id, bucket
        ORDER BY robot_id, bucket
    """
    sql_sessions = """
        SELECT robot_id, start_ts, duration_sec, battery_from, battery_to, battery_max_after
        FROM robot_charge_sessions
        ORDER BY robot_id, start_ts
    """
    async with _pool.acquire() as conn:
        tele_rows = await conn.fetch(sql_tele, int(window_hours))
        session_rows = await conn.fetch(sql_sessions)

    tele_by_robot = {}
    for row in tele_rows:
        tele_by_robot.setdefault(row["robot_id"], []).append(
            (row["bucket"].timestamp() / 60.0, row["battery"], row["battery_max"])
        )

    sessions_by_robot = {}
    for row in session_rows:
        sessions_by_robot.setdefault(row["robot_id"], []).append(row)

    results = []
    for robot_id, series in sorted(tele_by_robot.items()):
        series.sort(key=lambda s: s[0])
        times = [s[0] for s in series]
        batteries = [s[1] for s in series]
        battery_now = batteries[-1]
        battery_max = max(s[2] for s in series if s[2] is not None) if any(s[2] is not None for s in series) else None

        slope_min = _linreg_slope(times, batteries)  # % per minute
        discharge_rate = round(-slope_min * 60.0, 3) if slope_min is not None else None  # %/hour
        eta_hours = None
        if slope_min is not None and slope_min < 0:
            eta_hours = round((battery_now - BATTERY_LOW) / (-slope_min * 60.0), 2)

        sessions = sessions_by_robot.get(robot_id, [])
        sessions_sorted = sorted(sessions, key=lambda s: s["start_ts"])
        cycles_to_fail = None
        deg_per_session = None
        if len(sessions_sorted) >= 2:
            idxs = list(range(len(sessions_sorted)))
            maxes = [s["battery_max_after"] for s in sessions_sorted]
            deg_per_session = _linreg_slope(idxs, maxes)
            if deg_per_session is not None and deg_per_session < 0:
                last_max = maxes[-1]
                if last_max <= BATTERY_FAIL_MAX:
                    cycles_to_fail = 0
                else:
                    cycles_to_fail = int((last_max - BATTERY_FAIL_MAX) / (-deg_per_session))

        health = _classify_health(battery_now, battery_max, eta_hours, cycles_to_fail)
        results.append({
            "robot_id": robot_id,
            "battery_now": round(battery_now, 1),
            "battery_max": round(battery_max, 1) if battery_max is not None else None,
            "discharge_rate_per_hour": discharge_rate,
            "eta_hours": eta_hours,
            "charge_sessions": len(sessions_sorted),
            "degradation_per_session": round(deg_per_session, 3) if deg_per_session is not None else None,
            "cycles_to_fail": cycles_to_fail,
            "health": health,
        })

    severity = {"critical": 0, "warning": 1, "ok": 2}
    results.sort(key=lambda r: severity.get(r["health"], 2))
    return results


def _classify_health(battery_now, battery_max, eta_hours, cycles_to_fail):
    from config.constants import BATTERY_LOW, BATTERY_FAIL_MAX
    if battery_now <= BATTERY_LOW:
        return "critical"
    if battery_max is not None and battery_max <= BATTERY_FAIL_MAX:
        return "critical"
    if cycles_to_fail is not None and cycles_to_fail <= 20:
        return "critical"
    if eta_hours is not None and eta_hours <= 2:
        return "warning"
    if cycles_to_fail is not None and cycles_to_fail <= 50:
        return "warning"
    return "ok"


# ─── Queue helpers ─────────────────────────────────────────────────────

def _put(q, item):
    try:
        q.put_nowait(item)
    except asyncio.QueueFull:
        try:
            q.get_nowait()
            q.put_nowait(item)
        except Exception:
            pass


def _drain(q, limit):
    items = []
    while not q.empty() and len(items) < limit:
        try:
            items.append(q.get_nowait())
        except asyncio.QueueEmpty:
            break
    return items


def _discard(q):
    while not q.empty():
        try:
            q.get_nowait()
        except asyncio.QueueEmpty:
            break
