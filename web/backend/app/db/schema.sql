CREATE EXTENSION IF NOT EXISTS timescaledb;

CREATE TABLE IF NOT EXISTS robot_telemetry (
    time TIMESTAMPTZ NOT NULL,
    robot_id INT NOT NULL,
    x FLOAT NOT NULL DEFAULT 0,
    y FLOAT NOT NULL DEFAULT 0,
    phase TEXT,
    battery FLOAT,
    battery_max FLOAT,
    charging BOOLEAN DEFAULT FALSE,
    speed FLOAT DEFAULT 0,
    task_type TEXT
);

CREATE TABLE IF NOT EXISTS robot_logs (
    time TIMESTAMPTZ NOT NULL,
    robot_id INT,
    level TEXT,
    event TEXT,
    payload JSONB
);

CREATE TABLE IF NOT EXISTS robot_charge_sessions (
    id BIGSERIAL PRIMARY KEY,
    robot_id INT NOT NULL,
    start_ts TIMESTAMPTZ,
    end_ts TIMESTAMPTZ,
    duration_sec DOUBLE PRECISION,
    battery_from FLOAT,
    battery_to FLOAT,
    battery_max_after FLOAT
);

CREATE INDEX IF NOT EXISTS idx_telemetry_robot_time ON robot_telemetry (robot_id, time DESC);
CREATE INDEX IF NOT EXISTS idx_telemetry_time ON robot_telemetry (time DESC);
CREATE INDEX IF NOT EXISTS idx_logs_robot_time ON robot_logs (robot_id, time DESC);
CREATE INDEX IF NOT EXISTS idx_logs_time ON robot_logs (time DESC);
CREATE INDEX IF NOT EXISTS idx_charge_robot ON robot_charge_sessions (robot_id, start_ts);
