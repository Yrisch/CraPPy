"""Object animations of a slide: click groups of timed effects.

Impress stores a slide's main sequence as nested <anim:par>:

    main-sequence
      par (one per click group)
        par smil:begin="0.102s"        a time slot inside the group
          par (effect) presentation:node-type="after-previous" smil:begin="0.1s" (the Delay)
            anim:set / anim:animate / anim:animateMotion / anim:transitionFilter ...

Each on-click effect starts a new group; with-previous / after-previous
effects join the current one. Impress writes the slot offsets already
resolved (an after-previous slot begins when the previous one ends), so an
effect starts at slot begin + its own begin (the Delay). Effects before the
first click form group 0, which plays by itself when the slide appears.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from lxml import etree

from crappy.odf import NS, attr, q

_SHOW_PRESETS = {"ooo-entrance-appear"}
_HIDE_PRESETS = {"ooo-exit-disappear"}
_FADE_PRESETS = {"ooo-entrance-fade-in", "ooo-exit-fade-out"}


@dataclass(frozen=True)
class Effect:
    target: str              # xml:id of a shape or of a paragraph
    sub_item: str | None     # "text" when only the text of the shape is animated
    preset_class: str        # entrance / exit / motion-path
    preset_id: str
    duration: float          # seconds
    kind: str = "show"       # show | hide | fade_in | fade_out | motion
    start: float = 0.0       # seconds after the click (or after the slide appeared, group 0)
    path: str | None = None  # motion: SVG path, in fractions of the slide size, relative to the object
    accelerate: float = 0.0
    decelerate: float = 0.0

    @property
    def unit(self) -> tuple[str, str | None]:
        """What gets animated: a shape, a paragraph, or the text of a shape."""
        return self.target, self.sub_item

    @property
    def end(self) -> float:
        return self.start + self.duration


@dataclass
class SlideAnimation:
    groups: list[list[Effect]] = field(default_factory=lambda: [[]])
    warnings: list[str] = field(default_factory=list)

    @property
    def n_steps(self) -> int:
        return len(self.groups)

    @property
    def auto_start(self) -> bool:
        """Effects play by themselves when the slide appears (before the first click)."""
        return bool(self.groups[0])

    @property
    def units(self) -> list[tuple[str, str | None]]:
        """Animated things, in order of first appearance in the sequence."""
        return list(dict.fromkeys(e.unit for g in self.groups for e in g))

    def initially_visible(self, unit) -> bool:
        """Visible before any effect has played: unless its first effect is an entrance."""
        for g in self.groups:
            for e in g:
                if e.unit == unit and e.kind in ("show", "fade_in", "hide", "fade_out"):
                    return e.kind in ("hide", "fade_out")
        return True

    def hidden_at(self, step: int) -> set[tuple[str, str | None]]:
        """(target, sub_item) pairs invisible once the effects of groups 0..step have played."""
        hidden = set()
        for unit in self.units:
            visible = self.initially_visible(unit)
            for g in self.groups[:step + 1]:
                for e in sorted(g, key=lambda e: e.start):
                    if e.unit == unit and e.kind != "motion":
                        visible = e.kind in ("show", "fade_in")
            if not visible:
                hidden.add(unit)
        return hidden

    def group_duration(self, step: int) -> float:
        return max((e.end for e in self.groups[step]), default=0.0)


def parse_duration(value: str | None) -> float:
    """SMIL clock values as written by LibreOffice: '0.5s', '0.5', '500ms', 'indefinite'."""
    if not value:
        return 0.0
    m = re.fullmatch(r"\s*([0-9.]+)\s*(ms|s|min|h)?\s*", value)
    if not m:
        return 0.0
    scale = {"ms": 1e-3, "s": 1.0, "min": 60.0, "h": 3600.0, None: 1.0}[m.group(2)]
    return float(m.group(1)) * scale


def _effect_duration(effect_par: etree._Element) -> float:
    longest = 0.0
    for node in effect_par.iter():
        if node is effect_par:
            continue
        dur = node.get(q("smil:dur"))
        if dur is not None:
            longest = max(longest, parse_duration(node.get(q("smil:begin"))) + parse_duration(dur))
    return longest


def _float(value: str | None) -> float:
    try:
        return float(value) if value else 0.0
    except ValueError:
        return 0.0


def parse_slide_animation(page: etree._Element) -> SlideAnimation:
    anim = SlideAnimation()
    root = page.find("anim:par[@presentation:node-type='timing-root']", NS)
    if root is None:
        return anim
    if root.find("anim:seq[@presentation:node-type='interactive-sequence']", NS) is not None:
        anim.warnings.append("interactive (trigger) animations are ignored")
    seq = root.find("anim:seq[@presentation:node-type='main-sequence']", NS)
    if seq is None:
        return anim

    for effect_par in seq.iterfind(".//anim:par[@presentation:preset-class]", NS):
        if attr(effect_par, "presentation:node-type") == "on-click":
            anim.groups.append([])
        cls = attr(effect_par, "presentation:preset-class")
        preset = attr(effect_par, "presentation:preset-id", "")
        node = effect_par.find(".//*[@smil:targetElement]", NS)
        if node is None:
            anim.warnings.append(f"{cls} effect '{preset}' has no target, ignored")
            continue
        slot = effect_par.getparent()
        start = parse_duration(slot.get(q("smil:begin"))) + parse_duration(effect_par.get(q("smil:begin")))
        common = dict(target=node.get(q("smil:targetElement")), sub_item=node.get(q("anim:sub-item")),
                      preset_class=cls, preset_id=preset, duration=_effect_duration(effect_par), start=start)
        if cls == "motion-path":
            motion = effect_par.find(".//anim:animateMotion", NS)
            if motion is None or not motion.get(q("svg:path")):
                anim.warnings.append(f"motion path '{preset}' without a path, ignored")
                continue
            accel = effect_par.get(q("smil:accelerate")) or motion.get(q("smil:accelerate"))
            decel = effect_par.get(q("smil:decelerate")) or motion.get(q("smil:decelerate"))
            anim.groups[-1].append(Effect(**common, kind="motion", path=motion.get(q("svg:path")),
                                          accelerate=_float(accel), decelerate=_float(decel)))
        elif cls in ("entrance", "exit"):
            if preset in _SHOW_PRESETS or preset in _HIDE_PRESETS:
                kind = "show" if cls == "entrance" else "hide"
            else:
                kind = "fade_in" if cls == "entrance" else "fade_out"
                if preset not in _FADE_PRESETS:
                    anim.warnings.append(f"{cls} effect '{preset}' approximated by a fade")
            anim.groups[-1].append(Effect(**common, kind=kind))
        else:
            anim.warnings.append(f"{cls} effect '{preset}' ignored (entrance, exit and motion paths are supported)")
    return anim
