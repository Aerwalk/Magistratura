import numpy as np


def move_agent_towards_2d(pos: list, target: tuple, speed: float) -> list:
    vec = np.array(target, dtype=float) - np.array(pos, dtype=float)
    dist = np.linalg.norm(vec)
    if dist <= speed or dist == 0:
        return [float(target[0]), float(target[1])]
    vec = vec / dist
    return [pos[0] + vec[0] * speed, pos[1] + vec[1] * speed]


def close2(a: list, b: tuple, eps: float = 0.05) -> bool:
    return abs(a[0] - b[0]) < eps and abs(a[1] - b[1]) < eps


def close3(a: list, b: tuple, eps: float = 0.15) -> bool:
    return abs(a[0] - b[0]) < eps and abs(a[1] - b[1]) < eps and abs(a[2] - b[2]) < eps
