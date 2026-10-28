"""Splitting slides into layers, in stacking order.

A slide becomes:
  base     the master elements (slide number, footer, logos...) and the
           non-animated objects below the first animated one
  unit     one layer per animated object (a shape, a paragraph, or the
           text of a shape), so the player can show, fade and move it
  static   the non-animated objects between two animated ones

The base layer is rendered in place, in a copy of the talk where every slide
keeps only its base objects (so slide numbers and other master fields stay
right). Every other layer is rendered from an extra slide appended to one
more copy of the talk, holding just that layer, master elements hidden:
two documents (each over two backdrops) whatever the number of animations.
"""

from __future__ import annotations

import copy
import itertools
from dataclasses import dataclass, field

from lxml import etree

from crappy.animations import SlideAnimation
from crappy.odf import NS, OdfPackage, attr, q
from crappy.variants import StepHider

_NOT_SHAPES = {q("presentation:notes"), q("office:forms"), q("anim:par"), q("anim:seq")}
_IDS = (q("xml:id"), q("draw:id"), q("text:id"))
_counter = itertools.count()


@dataclass
class Unit:
    uid: str
    target: str
    sub_item: str | None
    top: int                                 # index of the top-level shape it belongs to
    element: etree._Element                  # the animated element (shape, nested shape or paragraph)
    paragraphs: list[etree._Element] | None  # set when only text is animated


@dataclass
class Layer:
    kind: str                                # base | static | unit
    unit: str | None = None
    shapes: list[int] = field(default_factory=list)   # top-level shape indices (static/base)


@dataclass
class SlidePlan:
    units: list[Unit]
    layers: list[Layer]
    warnings: list[str] = field(default_factory=list)

    @property
    def animated(self) -> bool:
        return bool(self.units)


def _shapes(page: etree._Element) -> list[etree._Element]:
    return [el for el in page if el.tag not in _NOT_SHAPES]


def _top_index(shapes: list[etree._Element], el: etree._Element) -> int | None:
    node = el
    while node is not None:
        if node in shapes:
            return shapes.index(node)
        node = node.getparent()
    return None


def plan_slide(page: etree._Element, anim: SlideAnimation, number: int) -> SlidePlan:
    shapes = _shapes(page)
    units, warnings = [], []
    for i, (target, sub_item) in enumerate(anim.units):
        found = page.xpath(".//*[@xml:id=$t or @draw:id=$t]", t=target, namespaces=NS)
        if not found:
            warnings.append(f"animation target {target!r} not found")
            continue
        el = found[0]
        top = _top_index(shapes, el)
        if top is None:
            warnings.append(f"animation target {target!r} is not on the slide")
            continue
        if el.tag in (q("text:p"), q("text:h")):
            paragraphs = [el]
        elif sub_item == "text":
            paragraphs = list(el.iter(q("text:p"), q("text:h")))
        else:
            paragraphs = None
        units.append(Unit(f"s{number}u{i}", target, sub_item, top, el, paragraphs))

    # stacking order: each top-level shape (what is static in it), then the units it holds
    layers: list[Layer] = [Layer("base")]
    by_top: dict[int, list[Unit]] = {}
    for u in units:
        by_top.setdefault(u.top, []).append(u)
    for index, shape in enumerate(shapes):
        whole = any(u.element is shape and u.paragraphs is None for u in by_top.get(index, []))
        if not whole:
            if layers[-1].kind not in ("base", "static"):
                layers.append(Layer("static"))
            layers[-1].shapes.append(index)
        for u in by_top.get(index, []):
            layers.append(Layer("unit", unit=u.uid))
    return SlidePlan(units, layers, warnings)


# --- document surgery -----------------------------------------------------------------


def _strip_decoration(pkg: OdfPackage, shape: etree._Element) -> None:
    """No fill, line or shadow: what is left of a text box is its text."""
    for attribute, family in (("draw:style-name", "graphic"), ("presentation:style-name", "presentation")):
        name = shape.get(q(attribute))
        if not name:
            continue
        src, loc = pkg.find_style("style:style", name)
        new_name = f"crappy_bare_{next(_counter)}"
        if src is not None and loc != "common":
            style = copy.deepcopy(src)
            style.set(q("style:name"), new_name)
        else:
            style = etree.Element(q("style:style"), {q("style:name"): new_name, q("style:family"): family})
            if src is not None:
                style.set(q("style:parent-style-name"), name)
        props = style.find("style:graphic-properties", NS)
        if props is None:
            props = etree.SubElement(style, q("style:graphic-properties"))
        props.set(q("draw:fill"), "none")
        props.set(q("draw:stroke"), "none")
        props.set(q("draw:shadow"), "hidden")
        pkg.content_automatic_styles.append(style)
        shape.set(q(attribute), new_name)


def _locate(page: etree._Element, unit: Unit) -> etree._Element | None:
    found = page.xpath(".//*[@xml:id=$t or @draw:id=$t]", t=unit.target, namespaces=NS)
    return found[0] if found else None


def _remove_units(pkg: OdfPackage, hider: StepHider, page: etree._Element, units: list[Unit]) -> None:
    """In a (copied) page: make the given units disappear, keeping the layout."""
    for u in units:
        el = _locate(page, u)
        if el is None:
            continue
        if u.paragraphs is None:
            el.getparent().remove(el)
        elif el.tag in (q("text:p"), q("text:h")):
            hider.hide_paragraph(el)
        else:
            for p in el.iter(q("text:p"), q("text:h")):
                hider.hide_paragraph(p)


def _keep_only(page: etree._Element, indices: set[int]) -> None:
    for i, shape in enumerate(_shapes(page)):
        if i not in indices:
            page.remove(shape)
    for el in list(page):
        if el.tag in _NOT_SHAPES:
            page.remove(el)


def _isolate_unit(pkg: OdfPackage, hider: StepHider, page: etree._Element, plan: SlidePlan, unit: Unit) -> None:
    """In a (copied) page: keep only `unit`, every other unit and static object removed."""
    _keep_only(page, {unit.top})
    el = _locate(page, unit)
    if el is None:
        return
    shape = _shapes(page)[0]
    # nested target: drop the siblings along the way down from the top-level shape
    node = el
    while node is not shape and node.getparent() is not None:
        parent = node.getparent()
        if parent.tag == q("draw:g"):
            for sibling in list(parent):
                if sibling is not node and sibling.tag != q("svg:title"):
                    parent.remove(sibling)
        node = parent
    if unit.paragraphs is not None:
        keep = {id(p) for p in (el.iter(q("text:p"), q("text:h")) if el.tag not in (q("text:p"), q("text:h")) else [el])}
        for p in shape.iter(q("text:p"), q("text:h")):
            if id(p) not in keep:
                hider.hide_paragraph(p)
        _strip_decoration(pkg, shape)
    else:
        # other units inside the same shape (its paragraphs animated separately) stay out
        _remove_units(pkg, hider, page, [u for u in plan.units if u is not unit and u.top == unit.top
                                          and u.paragraphs is not None])


def _strip_ids(page: etree._Element) -> None:
    for node in page.iter():
        for a in _IDS:
            node.attrib.pop(a, None)


def make_base(pkg: OdfPackage, plans: dict[int, SlidePlan]) -> OdfPackage:
    """Every slide restricted to its base layer (master elements included)."""
    v = pkg.copy()
    hider = StepHider(v)
    pages = v.pages()
    for number, plan in plans.items():
        page = pages[number - 1]
        if not plan.animated:
            continue
        base = plan.layers[0]
        units_in_base = [u for u in plan.units if u.top in base.shapes]
        _remove_units(v, hider, page, units_in_base)
        _keep_only(page, set(base.shapes))
    return v


def make_extra(pkg: OdfPackage, plans: dict[int, SlidePlan]) -> tuple[OdfPackage, list[tuple[int, int]]]:
    """A copy with one extra slide per non-base layer, appended after the talk.

    Returns the package and, for each extra slide in order, (slide number, layer index).
    """
    v = pkg.copy()
    hider = StepHider(v)
    pages = v.pages()
    body = pages[0].getparent()
    insert_at = body.index(pages[-1]) + 1
    extra: list[tuple[int, int]] = []
    for number, plan in plans.items():
        source = pages[number - 1]
        style = _no_master_style(v, source)
        for index, layer in enumerate(plan.layers):
            if layer.kind == "base":
                continue
            page = copy.deepcopy(source)
            if layer.kind == "unit":
                unit = next(u for u in plan.units if u.uid == layer.unit)
                _isolate_unit(v, hider, page, plan, unit)
            else:
                held = [u for u in plan.units if u.top in layer.shapes]
                _remove_units(v, hider, page, held)
                _keep_only(page, set(layer.shapes))
            _strip_ids(page)
            page.set(q("draw:name"), f"crappy layer {number}.{index}")
            page.set(q("draw:style-name"), style)
            body.insert(insert_at, page)
            insert_at += 1
            extra.append((number, index))
    return v, extra


def _no_master_style(pkg: OdfPackage, page: etree._Element) -> str:
    """A copy of the page's style with the master elements hidden."""
    name = page.get(q("draw:style-name"))
    src, _ = pkg.find_style("style:style", name) if name else (None, "")
    style = copy.deepcopy(src) if src is not None else etree.Element(
        q("style:style"), {q("style:family"): "drawing-page"})
    new_name = f"crappy_nomaster_{next(_counter)}"
    style.set(q("style:name"), new_name)
    props = style.find("style:drawing-page-properties", NS)
    if props is None:
        props = etree.SubElement(style, q("style:drawing-page-properties"))
    props.set(q("presentation:background-objects-visible"), "false")
    for a in ("presentation:display-page-number", "presentation:display-footer",
              "presentation:display-date-time", "presentation:display-header"):
        props.set(q(a), "false")
    pkg.content_automatic_styles.append(style)
    return new_name


def page_size_cm(pkg: OdfPackage) -> tuple[float, float]:
    """Slide size from the first master's page layout."""
    master = pkg.styles.find("office:master-styles/style:master-page", NS)
    layout_name = attr(master, "style:page-layout-name") if master is not None else None
    for layout in pkg.styles.iter(q("style:page-layout")):
        if attr(layout, "style:name") == layout_name or layout_name is None:
            props = layout.find("style:page-layout-properties", NS)
            if props is not None:
                def cm(v):
                    v = v or "28cm"
                    return float(v[:-2]) * (2.54 if v.endswith("in") else 0.1 if v.endswith("mm") else 1.0)
                return cm(props.get(q("fo:page-width"))), cm(props.get(q("fo:page-height")))
    return 28.0, 15.75
