"""Transformations producing the document copies that LibreOffice renders.

* set_page_backdrops: a slide's background becomes one solid colour
  (see crappy.background for how the colours are chosen).
* strip_to_background: keeps only the backgrounds (no objects, no master objects).
* StepHider: hides what is not yet visible (or already gone) at a click step.
  Shapes are removed; paragraphs keep their room but become fully transparent,
  and their bullet/number marker is blanked, so nothing moves between steps.
"""

from __future__ import annotations

import copy
import itertools

from lxml import etree

from crappy.animations import SlideAnimation
from crappy.odf import NS, OdfPackage, q

_counter = itertools.count()


def _ensure_child(el: etree._Element, tag: str) -> etree._Element:
    child = el.find(tag, NS)
    if child is None:
        child = etree.SubElement(el, q(tag))
    return child


def set_page_backdrops(pkg: OdfPackage, colors: dict[int, str]) -> None:
    """Give page i (0-based) a solid background of colors[i].

    Each page gets its own drawing-page style (a copy of its current one, so the
    transition and header/footer settings are kept), overriding the master's fill.
    """
    auto = pkg.content_automatic_styles
    pages = pkg.pages()
    clones: dict[tuple[str | None, str], str] = {}
    for index, color in colors.items():
        page = pages[index]
        name = page.get(q("draw:style-name"))
        if (name, color) not in clones:
            src, _ = pkg.find_style("style:style", name) if name else (None, "")
            style = copy.deepcopy(src) if src is not None else etree.Element(
                q("style:style"), {q("style:family"): "drawing-page"})
            new_name = f"crappy_backdrop_{next(_counter)}"
            style.set(q("style:name"), new_name)
            props = _ensure_child(style, "style:drawing-page-properties")
            props.set(q("draw:fill"), "solid")
            props.set(q("draw:fill-color"), color)
            props.set(q("presentation:background-visible"), "true")
            auto.append(style)
            clones[(name, color)] = new_name
        page.set(q("draw:style-name"), clones[(name, color)])


def _drawing_page_props(pkg: OdfPackage):
    for root in pkg.roots():
        for st in root.iter(q("style:style")):
            if st.get(q("style:family")) == "drawing-page":
                yield _ensure_child(st, "style:drawing-page-properties")


def strip_to_background(pkg: OdfPackage) -> None:
    keep = {q("presentation:notes"), q("office:forms")}
    for page in pkg.pages():
        for child in list(page):
            if child.tag not in keep:
                page.remove(child)
    for props in _drawing_page_props(pkg):
        props.set(q("presentation:background-objects-visible"), "false")


class StepHider:
    """Hides animated objects on one page of a (copied) package."""

    def __init__(self, pkg: OdfPackage):
        self.pkg = pkg
        self.auto = pkg.content_automatic_styles
        self._styles: dict[tuple[str, str | None], str] = {}
        self.warnings: list[str] = []

    def apply(self, page: etree._Element, anim: SlideAnimation, step: int) -> None:
        for target, sub_item in sorted(anim.hidden_at(step), key=str):
            found = page.xpath(".//*[@xml:id=$t or @draw:id=$t]", t=target, namespaces=NS)
            if not found:
                self.warnings.append(f"animation target {target!r} not found")
                continue
            el = found[0]
            if el.tag in (q("text:p"), q("text:h")):
                self.hide_paragraph(el)
            elif sub_item == "text":
                for p in el.iter(q("text:p"), q("text:h")):
                    self.hide_paragraph(p)
            else:
                el.getparent().remove(el)

    # --- text ----------------------------------------------------------------

    def _invisible_style(self, family: str, name: str | None) -> str:
        key = (family, name)
        if key in self._styles:
            return self._styles[key]
        new_name = f"crappy_hidden_{next(_counter)}"
        src, loc = self.pkg.find_style("style:style", name) if name else (None, "")
        if src is not None and loc != "common":
            style = copy.deepcopy(src)
            style.set(q("style:name"), new_name)
        else:
            # automatic styles may only inherit from common (named) styles
            style = etree.Element(q("style:style"), {q("style:name"): new_name, q("style:family"): family})
            if src is not None:
                style.set(q("style:parent-style-name"), name)
        tp = _ensure_child(style, "style:text-properties")
        # LibreOffice ignores character transparency on the "Automatic" colour
        tp.set(q("style:use-window-font-color"), "false")
        tp.set(q("fo:color"), "#808080")
        tp.set(q("loext:opacity"), "0%")
        self.auto.append(style)
        self._styles[key] = new_name
        return new_name

    def hide_paragraph(self, p: etree._Element) -> None:
        p.set(q("text:style-name"), self._invisible_style("paragraph", p.get(q("text:style-name"))))
        for span in p.iter(q("text:span")):
            span.set(q("text:style-name"), self._invisible_style("text", span.get(q("text:style-name"))))
        item = p.getparent()
        if item is not None and item.tag in (q("text:list-item"), q("text:list-header")):
            self._blank_marker(item)

    def _blank_marker(self, item: etree._Element) -> None:
        name = item.get(q("text:style-override"))
        node = item.getparent()
        while name is None and node is not None and node.tag in (q("text:list"), q("text:list-item")):
            name = node.get(q("text:style-name")) or node.get(q("text:style-override"))
            node = node.getparent()
        if name is None:
            self.warnings.append("bullet of a hidden paragraph has no list style: marker may stay visible")
            return
        key = ("list", name)
        if key not in self._styles:
            src, _ = self.pkg.find_style("text:list-style", name)
            if src is None:
                self.warnings.append(f"list style {name!r} not found: marker may stay visible")
                return
            lst = copy.deepcopy(src)
            new_name = f"crappy_hidden_{next(_counter)}"
            lst.set(q("style:name"), new_name)
            # The label width comes from min-label-width, so blanking the marker
            # does not move the text.
            for level in lst:
                if level.tag == q("text:list-level-style-bullet"):
                    level.set(q("text:bullet-char"), " ")
                elif level.tag == q("text:list-level-style-number"):
                    level.set(q("style:num-format"), "")
                    for a in ("style:num-prefix", "style:num-suffix"):
                        level.attrib.pop(q(a), None)
                elif level.tag == q("text:list-level-style-image"):
                    self.warnings.append("image bullets of hidden paragraphs stay visible")
            self.auto.append(lst)
            self._styles[key] = new_name
        item.set(q("text:style-override"), self._styles[key])
