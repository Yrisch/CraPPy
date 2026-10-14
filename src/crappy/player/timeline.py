"""Where the talk is, and what is on screen at a given time. No Qt in here.

A position is (slide index, click step). Moving between two neighbouring
positions plays an animation from A to B with a progress p in [0, 1]:
forward navigation runs p from 0 to 1, backward navigation runs the very
same animation from 1 to 0, so going back replays transitions in reverse.

While an animation runs, a key in the same direction finishes it at once
(skip), a key in the opposite direction turns it around from where it is.
"""

from __future__ import annotations

from dataclasses import dataclass

from crappy.player.deck import Deck, Effect


@dataclass(frozen=True, order=True)
class Pos:
    slide: int      # index in deck.slides
    step: int


@dataclass(frozen=True)
class Still:
    pos: Pos


@dataclass(frozen=True)
class Blend:
    a: Pos
    b: Pos
    effect: Effect
    progress: float     # 0 shows a, 1 shows b


@dataclass
class _Animation:
    a: Pos
    b: Pos
    effect: Effect
    p0: float
    t0: float
    direction: int      # +1 towards b, -1 towards a

    def progress(self, now: float) -> float:
        p = self.p0 + self.direction * (now - self.t0) / self.effect.duration
        return min(1.0, max(0.0, p))

    @property
    def target(self) -> Pos:
        return self.b if self.direction > 0 else self.a


class Timeline:
    def __init__(self, deck: Deck, start: Pos | None = None):
        self.deck = deck
        visible = self._visible()
        if not visible:
            raise ValueError("the talk has no visible slide")
        self.pos = start or Pos(visible[0], 0)
        self._anim: _Animation | None = None

    # --- queries -------------------------------------------------------------

    def _visible(self) -> list[int]:
        return [i for i, s in enumerate(self.deck.slides) if not s.hidden]

    def _next_slide(self, i: int) -> int | None:
        return next((j for j in self._visible() if j > i), None)

    def _prev_slide(self, i: int) -> int | None:
        return next((j for j in reversed(self._visible()) if j < i), None)

    def last_step(self, slide: int) -> Pos:
        return Pos(slide, self.deck.slides[slide].n_steps - 1)

    def animating(self, now: float) -> bool:
        self.scene(now)
        return self._anim is not None

    def scene(self, now: float) -> Still | Blend:
        a = self._anim
        if a is None:
            return Still(self.pos)
        p = a.progress(now)
        if (a.direction > 0 and p >= 1) or (a.direction < 0 and p <= 0):
            self.pos, self._anim = a.target, None
            return Still(self.pos)
        return Blend(a.a, a.b, a.effect, p)

    def neighbours(self) -> list[Pos]:
        """Positions that the next key presses may show: worth preloading."""
        out = []
        for s in (self.pos.slide, self._next_slide(self.pos.slide), self._prev_slide(self.pos.slide)):
            if s is not None:
                out += [Pos(s, k) for k in range(self.deck.slides[s].n_steps)]
        return out

    # --- navigation ----------------------------------------------------------

    def _forward_from(self, pos: Pos) -> tuple[Pos, Effect] | None:
        slide = self.deck.slides[pos.slide]
        if pos.step + 1 < slide.n_steps:
            return Pos(pos.slide, pos.step + 1), slide.step_effects[pos.step + 1]
        nxt = self._next_slide(pos.slide)
        if nxt is None:
            return None
        return Pos(nxt, 0), self.deck.slides[nxt].transition

    def _backward_from(self, pos: Pos) -> tuple[Pos, Effect] | None:
        """(previous position, effect of the move previous -> pos)."""
        slide = self.deck.slides[pos.slide]
        if pos.step > 0:
            return Pos(pos.slide, pos.step - 1), slide.step_effects[pos.step]
        prv = self._prev_slide(pos.slide)
        if prv is None:
            return None
        return self.last_step(prv), slide.transition

    def next(self, now: float) -> None:
        self.scene(now)
        a = self._anim
        if a is not None:
            if a.direction > 0:
                self.pos, self._anim = a.b, None
            else:
                self._turn(a, now)
            return
        move = self._forward_from(self.pos)
        if move is not None:
            target, effect = move
            self._start(self.pos, target, effect, 0.0, +1, now)

    def prev(self, now: float) -> None:
        self.scene(now)
        a = self._anim
        if a is not None:
            if a.direction < 0:
                self.pos, self._anim = a.a, None
            else:
                self._turn(a, now)
            return
        move = self._backward_from(self.pos)
        if move is not None:
            source, effect = move
            self._start(source, self.pos, effect, 1.0, -1, now)

    def goto(self, slide: int, now: float, step: int = 0) -> None:
        self._anim = None
        self.pos = Pos(slide, max(0, min(step, self.deck.slides[slide].n_steps - 1)))

    def first(self, now: float) -> None:
        self.goto(self._visible()[0], now)

    def last(self, now: float) -> None:
        self.goto(self._visible()[-1], now)

    def _start(self, a: Pos, b: Pos, effect: Effect, p0: float, direction: int, now: float) -> None:
        if effect.instant:
            self.pos, self._anim = (b if direction > 0 else a), None
        else:
            self._anim = _Animation(a, b, effect, p0, now, direction)

    def _turn(self, a: _Animation, now: float) -> None:
        a.p0, a.t0, a.direction = a.progress(now), now, -a.direction
