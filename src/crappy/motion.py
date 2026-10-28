"""Motion paths: SVG path data -> points at even distances, and SMIL timing.

Impress writes a motion path as SVG path data in fractions of the slide size
(x of the width, y of the height), as an offset from where the object sits on
the slide; an object moved twice gets a second path starting where the first
one ended. The object moves at constant speed along the path (SMIL
calcMode="paced", the default for animateMotion), with the effect's
accelerate / decelerate easing applied to time.
"""

from __future__ import annotations

import math
import re

_TOKEN = re.compile(r"[MmLlHhVvCcSsQqTtZz]|[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")
_ARITY = {"M": 2, "L": 2, "H": 1, "V": 1, "C": 6, "S": 4, "Q": 4, "T": 2, "Z": 0}


class PathError(ValueError):
    pass


def _bezier(p0, p1, p2, p3, n=24):
    for i in range(1, n + 1):
        t = i / n
        u = 1 - t
        yield (u ** 3 * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t ** 3 * p3[0],
               u ** 3 * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t ** 3 * p3[1])


def flatten(d: str) -> list[tuple[float, float]]:
    """SVG path data -> polyline (curves subdivided). Supports M L H V C S Q T Z, absolute and relative."""
    tokens = _TOKEN.findall(d)
    points: list[tuple[float, float]] = []
    pos = start = (0.0, 0.0)
    last_ctrl = None
    cmd = None
    i = 0
    while i < len(tokens):
        if tokens[i].isalpha():
            cmd = tokens[i]
            i += 1
            if cmd in "Zz":
                points.append(start)
                pos, last_ctrl = start, None
                continue
        if cmd is None:
            raise PathError(f"path data must start with a command: {d[:40]!r}")
        n = _ARITY[cmd.upper()]
        try:
            args = [float(t) for t in tokens[i:i + n]]
        except ValueError:
            raise PathError(f"bad path data near {' '.join(tokens[i:i + n])!r}") from None
        if len(args) < n:
            raise PathError(f"truncated path data: {d[-40:]!r}")
        i += n
        rel = cmd.islower()
        ox, oy = pos if rel else (0.0, 0.0)
        c = cmd.upper()
        if c == "M":
            pos = start = (ox + args[0], oy + args[1])
            points.append(pos)
            cmd = "l" if rel else "L"           # further pairs are line-tos
            last_ctrl = None
        elif c in "LHV":
            if c == "L":
                pos = (ox + args[0], oy + args[1])
            elif c == "H":
                pos = ((pos[0] if rel else 0.0) + args[0], pos[1])
            else:
                pos = (pos[0], (pos[1] if rel else 0.0) + args[0])
            points.append(pos)
            last_ctrl = None
        elif c in "CS":
            if c == "C":
                c1 = (ox + args[0], oy + args[1])
                c2, end = (ox + args[2], oy + args[3]), (ox + args[4], oy + args[5])
            else:
                c1 = (2 * pos[0] - last_ctrl[0], 2 * pos[1] - last_ctrl[1]) if last_ctrl else pos
                c2, end = (ox + args[0], oy + args[1]), (ox + args[2], oy + args[3])
            points.extend(_bezier(pos, c1, c2, end))
            pos, last_ctrl = end, c2
        else:                                     # Q, T: quadratic -> cubic
            if c == "Q":
                qc, end = (ox + args[0], oy + args[1]), (ox + args[2], oy + args[3])
            else:
                qc = (2 * pos[0] - last_ctrl[0], 2 * pos[1] - last_ctrl[1]) if last_ctrl else pos
                end = (ox + args[0], oy + args[1])
            c1 = (pos[0] + 2 / 3 * (qc[0] - pos[0]), pos[1] + 2 / 3 * (qc[1] - pos[1]))
            c2 = (end[0] + 2 / 3 * (qc[0] - end[0]), end[1] + 2 / 3 * (qc[1] - end[1]))
            points.extend(_bezier(pos, c1, c2, end))
            pos, last_ctrl = end, qc
    if not points:
        raise PathError("empty path")
    return points


def resample(points: list[tuple[float, float]], scale: tuple[float, float], n: int = 101) -> list[tuple[float, float]]:
    """n points at even distances along the polyline, after scaling it (fractions -> pixels):
    point i is where the object is at a fraction i / (n - 1) of the motion."""
    pts = [(x * scale[0], y * scale[1]) for x, y in points]
    if len(pts) == 1:
        return pts * n
    cumulative = [0.0]
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        cumulative.append(cumulative[-1] + math.hypot(x1 - x0, y1 - y0))
    total = cumulative[-1]
    if total == 0:
        return [pts[0]] * n
    out, j = [], 0
    for i in range(n):
        target = total * i / (n - 1)
        while j < len(pts) - 2 and cumulative[j + 1] < target:
            j += 1
        seg = cumulative[j + 1] - cumulative[j]
        f = 0.0 if seg == 0 else (target - cumulative[j]) / seg
        out.append((pts[j][0] + f * (pts[j + 1][0] - pts[j][0]), pts[j][1] + f * (pts[j + 1][1] - pts[j][1])))
    return out


def ease(t: float, accelerate: float = 0.0, decelerate: float = 0.0) -> float:
    """SMIL accelerate/decelerate: simple time t in [0, 1] -> progress in [0, 1].
    Speed rises linearly during the first `accelerate` fraction, falls during the last
    `decelerate` fraction, and is constant in between."""
    t = min(1.0, max(0.0, t))
    a, d = max(0.0, accelerate), max(0.0, decelerate)
    if a + d > 1:
        a, d = a / (a + d), d / (a + d)
    if a == 0 and d == 0:
        return t
    r = 1 / (1 - a / 2 - d / 2)              # top speed, so that the whole area is 1
    if t < a:
        return r * t * t / (2 * a)
    if t <= 1 - d:
        return r * (t - a / 2)
    u = 1 - t
    return 1 - r * u * u / (2 * d)


def along(points: list[tuple[float, float]], progress: float) -> tuple[float, float]:
    """Position at a progress in [0, 1] on points from resample()."""
    f = min(1.0, max(0.0, progress)) * (len(points) - 1)
    i = min(int(f), len(points) - 2) if len(points) > 1 else 0
    if len(points) == 1:
        return points[0]
    g = f - i
    (x0, y0), (x1, y1) = points[i], points[i + 1]
    return x0 + g * (x1 - x0), y0 + g * (y1 - y0)
