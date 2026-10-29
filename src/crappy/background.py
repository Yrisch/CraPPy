# SPDX-FileCopyrightText: 2026 Yann Bernard <yannbernard13@gmail.com>
# SPDX-License-Identifier: CECILL-2.1

"""Is a slide background dark or light, as far as LibreOffice is concerned?

Impress draws text with the "Automatic" font colour in white on a dark
background and in black otherwise. The background colour it judges is a
"draft" colour of the page fill (the colour of a solid fill, the average of a
bitmap or of a gradient's two colours). Measured on LibreOffice 26.8: a colour
is dark when its HSP perceived brightness sqrt(.299 R^2 + .587 G^2 + .114 B^2)
is at most 158 (grey 158 gives white text, grey 159 black text; pure green,
of plain luminance 150, gives black text).

The build keeps automatic colours untouched and renders each slide over two
backdrops on the same side of that threshold, so the text colour does not
flip between the two renders.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from lxml import etree
from PIL import Image

from crappy.odf import NS, OdfPackage, attr, q

DARK_BRIGHTNESS = 158

# backdrop pairs (as #rrggbb) per background class; within a pair the colours differ
# by a full 255 in the blue channel, which perceived brightness weighs the least
BACKDROPS = {
    "dark": ("#000000", "#0000ff"),     # brightness 0 and 86
    "light": ("#ffffff", "#ffff00"),    # brightness 255 and 240
}
WHITE = (255, 255, 255)


def hex_to_rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)


def brightness(rgb: tuple[int, int, int]) -> float:
    """HSP perceived brightness, 0-255."""
    r, g, b = rgb
    return (0.299 * r * r + 0.587 * g * g + 0.114 * b * b) ** 0.5


def _named(pkg: OdfPackage, tag: str, name: str | None) -> etree._Element | None:
    if not name:
        return None
    for el in pkg.styles.iter(q(tag)):
        if attr(el, "draw:name") == name:
            return el
    return None


def _image_mean(pkg: OdfPackage, href: str | None) -> tuple[int, int, int] | None:
    data = _image_bytes(pkg, href)
    if data is None:
        return None
    try:
        img = Image.open(io.BytesIO(data)).convert("RGBA")
    except OSError:
        return None
    img.thumbnail((256, 256))
    rgba = np.asarray(img, np.float32) / 255
    rgb = rgba[..., :3] * rgba[..., 3:] + (1 - rgba[..., 3:])     # transparent parts show white
    return tuple(int(v) for v in (rgb.reshape(-1, 3).mean(0) * 255).round())


def draft_fill_color(pkg: OdfPackage, props: etree._Element) -> tuple[int, int, int] | None:
    """Colour standing for a drawing-page fill, or None when the fill is not set here."""
    fill = props.get(q("draw:fill"))
    if fill is None:
        return None
    if fill == "solid":
        return hex_to_rgb(props.get(q("draw:fill-color"), "#729fcf"))
    if fill == "bitmap":
        image = _named(pkg, "draw:fill-image", props.get(q("draw:fill-image-name")))
        mean = _image_mean(pkg, None if image is None else image.get(q("xlink:href")))
        return mean or WHITE
    if fill == "gradient":
        grad = _named(pkg, "draw:gradient", props.get(q("draw:fill-gradient-name")))
        if grad is not None:
            a = hex_to_rgb(grad.get(q("draw:start-color"), "#000000"))
            b = hex_to_rgb(grad.get(q("draw:end-color"), "#ffffff"))
            return tuple((x + y) // 2 for x, y in zip(a, b))
    if fill == "hatch":
        hatch = _named(pkg, "draw:hatch", props.get(q("draw:fill-hatch-name")))
        if hatch is not None:
            return hex_to_rgb(hatch.get(q("draw:color"), "#000000"))
    return WHITE            # "none": nothing drawn, the page shows white


@dataclass
class BackgroundImage:
    """A slide background that is a picture."""
    name: str                # name shown by Impress: the file name it was inserted from, without extension
    data: bytes | None       # the picture itself (embedded, or a linked file)
    stretched: bool          # fills the slide exactly (as opposed to tiled / placed)


def _image_bytes(pkg: OdfPackage, href: str | None) -> bytes | None:
    if not href:
        return None
    if href in pkg.files:
        return pkg.files[href]
    path = Path(href.removeprefix("file://"))
    return path.read_bytes() if path.exists() else None


def _props(pkg: OdfPackage, style_name: str | None) -> etree._Element | None:
    if not style_name:
        return None
    style, _ = pkg.find_style("style:style", style_name)
    return None if style is None else style.find("style:drawing-page-properties", NS)


def _master_props(pkg: OdfPackage, page: etree._Element) -> etree._Element | None:
    name = attr(page, "draw:master-page-name")
    for mp in pkg.styles.iterfind("office:master-styles/style:master-page", NS):
        if attr(mp, "style:name") == name:
            return _props(pkg, attr(mp, "draw:style-name"))
    return None


def _effective_fill(pkg: OdfPackage, page: etree._Element) -> etree._Element | None:
    """drawing-page-properties that decide the page fill: the page's own, else its master's."""
    props = _props(pkg, attr(page, "draw:style-name"))
    if props is not None and props.get(q("draw:fill")) is not None:
        return props
    if props is not None and props.get(q("presentation:background-visible")) == "false":
        return None
    return _master_props(pkg, page)


def background_image(pkg: OdfPackage, page: etree._Element) -> BackgroundImage | None:
    props = _effective_fill(pkg, page)
    if props is None or props.get(q("draw:fill")) != "bitmap":
        return None
    image = _named(pkg, "draw:fill-image", props.get(q("draw:fill-image-name")))
    if image is None:
        return None
    name = image.get(q("draw:display-name")) or image.get(q("draw:name"))
    # ODF's default is a tiled bitmap; Impress' "stretched" option writes style:repeat="stretch"
    stretched = props.get(q("style:repeat")) == "stretch"
    return BackgroundImage(name, _image_bytes(pkg, image.get(q("xlink:href"))), stretched)


def background_class(pkg: OdfPackage, page: etree._Element) -> str:
    """'dark' or 'light'."""
    color = None
    props = _props(pkg, attr(page, "draw:style-name"))
    if props is not None:
        color = draft_fill_color(pkg, props)
        if color is None and props.get(q("presentation:background-visible")) == "false":
            color = WHITE
    if color is None:
        master = _master_props(pkg, page)
        color = (master is not None and draft_fill_color(pkg, master)) or WHITE
    return "dark" if brightness(color) <= DARK_BRIGHTNESS else "light"


def other_class(cls: str) -> str:
    return "light" if cls == "dark" else "dark"
