"""Object animations of a slide -> discrete click steps.

Impress stores a slide's main sequence as nested <anim:par>; every effect
carries presentation:node-type (on-click / with-previous / after-previous)
and presentation:preset-class (entrance / exit / emphasis / motion-path...).
Each on-click starts a new step; with/after-previous effects join the
current one. Effects before the first click run at slide start (step 0).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from lxml import etree

from crappy.odf import NS, attr, q

# presets reproduced exactly; any other entrance/exit preset is approximated by a fade
_CUT_PRESETS = {"ooo-entrance-appear", "ooo-exit-disappear"}
_FADE_PRESETS = {"ooo-entrance-fade-in", "ooo-exit-fade-out"}
_SUPPORTED_CLASSES = {"entrance", "exit"}


@dataclass(frozen=True)
class Effect:
    target: str              # xml:id of a shape or of a paragraph
    sub_item: str | None     # "text" when only the text of the shape is animated
    preset_class: str        # entrance / exit
    preset_id: str
    duration: float          # seconds


@dataclass
class StepEffect:
    """How the slide content changes when entering a step."""
    kind: str = "cut"        # cut | fade
    duration: float = 0.0


@dataclass
class SlideAnimation:
    groups: list[list[Effect]] = field(default_factory=lambda: [[]])
    warnings: list[str] = field(default_factory=list)

    @property
    def n_steps(self) -> int:
        return len(self.groups)

    @property
    def has_exit(self) -> bool:
        return any(e.preset_class == "exit" for g in self.groups for e in g)

    def hidden_at(self, step: int) -> set[tuple[str, str | None]]:
        """(target, sub_item) pairs that must be invisible at the given step."""
        hidden = set()
        for i, group in enumerate(self.groups):
            for e in group:
                if (e.preset_class == "entrance" and i > step) or (e.preset_class == "exit" and i <= step):
                    hidden.add((e.target, e.sub_item))
        return hidden

    def step_effect(self, step: int) -> StepEffect:
        group = self.groups[step] if step < len(self.groups) else []
        if step == 0 or not group or all(e.preset_id in _CUT_PRESETS for e in group):
            return StepEffect()
        fades = [e.duration for e in group if e.preset_id not in _CUT_PRESETS]
        return StepEffect("fade", max(fades) if fades else 0.0)


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
        if cls not in _SUPPORTED_CLASSES:
            anim.warnings.append(f"{cls} effect '{preset}' ignored (only entrance/exit are supported)")
            continue
        if preset not in _CUT_PRESETS | _FADE_PRESETS:
            anim.warnings.append(f"{cls} effect '{preset}' approximated by a fade")
        node = effect_par.find(".//*[@smil:targetElement]", NS)
        if node is None:
            anim.warnings.append(f"{cls} effect '{preset}' has no target, ignored")
            continue
        anim.groups[-1].append(Effect(
            target=node.get(q("smil:targetElement")),
            sub_item=node.get(q("anim:sub-item")),
            preset_class=cls,
            preset_id=preset,
            duration=_effect_duration(effect_par),
        ))
    return anim
