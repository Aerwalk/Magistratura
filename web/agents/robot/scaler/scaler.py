import json
import os
import subprocess
import time
import urllib.request

BACKEND_URL = os.getenv("BACKEND_URL", "http://backend:8000")
POLL_INTERVAL = float(os.getenv("POLL_INTERVAL", "3"))
COMPOSE_FILE = os.getenv("COMPOSE_FILE", "/compose/docker-compose.yml")
COMPOSE_PROJECT = os.getenv("COMPOSE_PROJECT", "")
SERVICE = os.getenv("SERVICE", "robot-agent")
MIN_REPLICAS = int(os.getenv("MIN_REPLICAS", "5"))


def log(msg):
    print(f"[robot-scaler] {msg}", flush=True)


def fetch_debug():
    with urllib.request.urlopen(f"{BACKEND_URL}/api/debug", timeout=5) as r:
        return json.load(r)


def docker(*args, timeout=60):
    return subprocess.run(
        ["docker", *args], capture_output=True, text=True, timeout=timeout
    )


def project_name():
    if COMPOSE_PROJECT:
        return COMPOSE_PROJECT
    res = docker(
        "ps",
        "--filter",
        f"label=com.docker.compose.service={SERVICE}",
        "--format",
        "{{.Label \"com.docker.compose.project\"}}",
    )
    names = {ln.strip() for ln in res.stdout.splitlines() if ln.strip()}
    if len(names) == 1:
        return names.pop()
    return "web"


def running_replicas():
    res = docker(
        "ps",
        "--filter",
        f"label=com.docker.compose.service={SERVICE}",
        "--filter",
        "status=running",
        "--format",
        "{{.ID}}",
    )
    return len([ln for ln in res.stdout.splitlines() if ln.strip()])


def scale_to(n, project):
    log(f"scaling {SERVICE} to {n} (project={project}, compose={COMPOSE_FILE})")
    res = docker(
        "compose",
        "-p",
        project,
        "-f",
        COMPOSE_FILE,
        "up",
        "-d",
        "--no-deps",
        "--scale",
        f"{SERVICE}={n}",
        SERVICE,
        timeout=180,
    )
    if res.returncode != 0:
        log(f"scale failed: {(res.stderr or res.stdout).strip()}")
        return False
    log("scale ok")
    return True


def main():
    log(f"polling {BACKEND_URL}/api/debug every {POLL_INTERVAL}s, service={SERVICE}")
    last_report = None
    while True:
        try:
            data = fetch_debug()
            robots = data.get("robots", [])
            n_robots = max(MIN_REPLICAS, len(robots))
            running = running_replicas()
            if running < n_robots:
                log(f"robots={len(robots)} running={running} -> need scale up")
                scale_to(n_robots, project_name())
            else:
                report = (len(robots), running)
                if report != last_report:
                    log(f"ok: robots={len(robots)} running={running}")
                    last_report = report
        except Exception as e:
            log(f"error: {e}")
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
