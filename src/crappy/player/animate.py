# SPDX-FileCopyrightText: 2026 Yann Bernard <yannbernard13@gmail.com>
# SPDX-License-Identifier: CECILL-2.1

"""State of every animated object at a moment of a slide. No Qt in here.

The state of a unit is (opacity, dx, dy): dx, dy its offset in canvas pixels
from where it sits on the slide. Steps before the current one have fully
played; in the current one, effects have played up to time t.
"""

from __future__ import annotations

from crappy.motion import along, ease
from crappy.player.deck import DeckSlide, Event

State = tuple[float, float, float]


def _apply(state: list[float], e: Event, t: float) -> None:
    if t < e.start:
        return
    f = 1.0 if e.duration <= 0 else min(1.0, (t - e.start) / e.duration)
    if e.kind == "show":
        state[0] = 1.0
    elif e.kind == "hide":
        state[0] = 0.0
    elif e.kind == "fade_in":
        state[0] = f
    elif e.kind == "fade_out":
        state[0] = 1.0 - f
    elif e.kind == "motion" and e.points:
        state[1], state[2] = along(e.points, ease(f, e.accelerate, e.decelerate))


def unit_states(slide: DeckSlide, step: int, t: float | None = None) -> dict[str, State]:
    """t: seconds into `step`; None for the end of it."""
    state = {u: [1.0 if visible else 0.0, 0.0, 0.0] for u, visible in slide.units_visible.items()}
    for k in range(step + 1):
        now = float("inf") if (k < step or t is None) else t
        for e in sorted(slide.steps[k].events, key=lambda e: e.start):
            if e.unit in state:
                _apply(state[e.unit], e, now)
    return {u: (o, dx, dy) for u, (o, dx, dy) in state.items()}


def layer_states(slide: DeckSlide, step: int, t: float | None = None) -> list[State]:
    """(opacity, dx, dy) for each layer of the slide, in stacking order."""
    units = unit_states(slide, step, t)
    return [units.get(layer.unit, (1.0, 0.0, 0.0)) if layer.unit else (1.0, 0.0, 0.0) for layer in slide.layers]
