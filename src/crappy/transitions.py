"""Slide transitions as set in Impress' Slide Transition panel.

The transition belongs to the *incoming* slide. Its type is stored on the
page's drawing-page style (smil:type / smil:subtype / smil:direction /
smil:fadeColor); its exact duration on an <anim:transitionFilter> placed in
the page's timing root (timing-root > anim:par > anim:transitionFilter).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from lxml import etree

from crappy.animations import parse_duration
from crappy.odf import NS, OdfPackage, attr, q

# Impress' "speed" attribute, only used when no explicit duration is stored
_SPEED = {"fast": 0.5, "medium": 1.0, "slow": 2.0}
_SIDES = {"fromLeft": "left", "fromRight": "right", "fromTop": "top", "fromBottom": "bottom"}
_OPPOSITE = {"left": "right", "right": "left", "top": "bottom", "bottom": "top"}


@dataclass
class Transition:
    """kind: cut | fade | fade_color | push | cover | uncover | wipe

    side: for push/cover, the side the incoming slide enters from; for
    uncover, the side the outgoing slide leaves towards; for wipe, the side
    the wipe edge starts from.
    """
    kind: str = "cut"
    duration: float = 0.0
    side: str | None = None
    color: str | None = None
    source: str = "libreoffice"     # libreoffice | config | default
    lo_type: str | None = None      # original smil type/subtype, for diagnostics

    def to_json(self) -> dict:
        return {k: v for k, v in asdict(self).items() if v is not None}


def _page_style_props(pkg: OdfPackage, page: etree._Element) -> etree._Element | None:
    name = attr(page, "draw:style-name")
    if not name:
        return None
    style, _ = pkg.find_style("style:style", name)
    return None if style is None else style.find("style:drawing-page-properties", NS)


def _explicit_duration(page: etree._Element) -> float | None:
    filt = page.find("anim:par[@presentation:node-type='timing-root']/anim:par/anim:transitionFilter", NS)
    if filt is None:
        return None
    return parse_duration(filt.get(q("smil:dur")))


def parse_transition(pkg: OdfPackage, page: etree._Element) -> tuple[Transition, list[str]]:
    props = _page_style_props(pkg, page)
    smil_type = None if props is None else props.get(q("smil:type"))
    if not smil_type:
        return Transition(), []

    subtype = props.get(q("smil:subtype"), "")
    reverse = props.get(q("smil:direction")) == "reverse"
    duration = _explicit_duration(page)
    if duration is None:
        duration = _SPEED.get(props.get(q("presentation:transition-speed"), "medium"), 1.0)
    t = Transition(duration=duration, lo_type=f"{smil_type}/{subtype}" + (" reverse" if reverse else ""))
    warnings = []

    if smil_type == "fade" and subtype == "crossfade":
        t.kind = "fade"
    elif smil_type == "fade":
        t.kind, t.color = "fade_color", props.get(q("smil:fadeColor"), "#000000")
    elif smil_type == "pushWipe" and subtype in _SIDES:
        t.kind, t.side = "push", _SIDES[subtype]
    elif smil_type == "slideWipe" and subtype in _SIDES:
        t.kind, t.side = ("uncover" if reverse else "cover"), _SIDES[subtype]
    elif smil_type == "barWipe" and subtype in ("leftToRight", "topToBottom"):
        side = "left" if subtype == "leftToRight" else "top"
        t.kind, t.side = "wipe", (_OPPOSITE[side] if reverse else side)
    else:
        t.kind = "fade"
        warnings.append(f"transition {t.lo_type} not supported, replaced by a fade")
    return t, warnings
