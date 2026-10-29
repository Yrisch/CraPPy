# SPDX-FileCopyrightText: 2026 Yann Bernard <yannbernard13@gmail.com>
# SPDX-License-Identifier: CECILL-2.1

"""Minimal access to OpenDocument presentation packages (.odp).

Only content.xml and styles.xml are parsed; every other member of the zip
(pictures, embedded objects, manifest...) is carried over byte for byte.
"""

from __future__ import annotations

import copy
import zipfile
from pathlib import Path

from lxml import etree

NS = {
    "office": "urn:oasis:names:tc:opendocument:xmlns:office:1.0",
    "style": "urn:oasis:names:tc:opendocument:xmlns:style:1.0",
    "text": "urn:oasis:names:tc:opendocument:xmlns:text:1.0",
    "draw": "urn:oasis:names:tc:opendocument:xmlns:drawing:1.0",
    "fo": "urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0",
    "svg": "urn:oasis:names:tc:opendocument:xmlns:svg-compatible:1.0",
    "presentation": "urn:oasis:names:tc:opendocument:xmlns:presentation:1.0",
    "anim": "urn:oasis:names:tc:opendocument:xmlns:animation:1.0",
    "smil": "urn:oasis:names:tc:opendocument:xmlns:smil-compatible:1.0",
    "xlink": "http://www.w3.org/1999/xlink",
    "loext": "urn:org:documentfoundation:names:experimental:office:xmlns:loext:1.0",
    "xml": "http://www.w3.org/XML/1998/namespace",
}

_PARSER = etree.XMLParser(huge_tree=True)


def q(name: str) -> str:
    """'draw:page' -> '{urn:...drawing:1.0}page' (Clark notation for lxml)."""
    prefix, local = name.split(":")
    return f"{{{NS[prefix]}}}{local}"


class OdfPackage:
    """An .odp loaded in memory: parsed content/styles trees plus raw members."""

    def __init__(self, files: dict[str, bytes], content: etree._Element, styles: etree._Element):
        self.files = files
        self.content = content
        self.styles = styles

    @classmethod
    def load(cls, path: str | Path) -> OdfPackage:
        with zipfile.ZipFile(path) as z:
            # Read by name: never reuse these ZipInfo objects for writing, writestr() mutates them.
            files = {i.filename: z.read(i.filename) for i in z.infolist() if not i.is_dir()}
        content = etree.fromstring(files["content.xml"], _PARSER)
        styles = etree.fromstring(files["styles.xml"], _PARSER)
        return cls(files, content, styles)

    def copy(self) -> OdfPackage:
        return OdfPackage(self.files, copy.deepcopy(self.content), copy.deepcopy(self.styles))

    def save(self, path: str | Path) -> None:
        members = dict(self.files)
        members["content.xml"] = etree.tostring(self.content, xml_declaration=True, encoding="UTF-8")
        members["styles.xml"] = etree.tostring(self.styles, xml_declaration=True, encoding="UTF-8")
        with zipfile.ZipFile(path, "w") as z:
            # ODF requires 'mimetype' first and uncompressed
            z.writestr("mimetype", members.pop("mimetype", b"application/vnd.oasis.opendocument.presentation"),
                       compress_type=zipfile.ZIP_STORED)
            for name, data in members.items():
                z.writestr(name, data, compress_type=zipfile.ZIP_DEFLATED)

    # --- navigation -------------------------------------------------------

    def pages(self) -> list[etree._Element]:
        return self.content.findall("office:body/office:presentation/draw:page", NS)

    def roots(self) -> tuple[etree._Element, etree._Element]:
        return self.content, self.styles

    @property
    def content_automatic_styles(self) -> etree._Element:
        auto = self.content.find("office:automatic-styles", NS)
        if auto is None:
            auto = etree.Element(q("office:automatic-styles"))
            self.content.insert(0, auto)
        return auto

    def find_style(self, tag: str, name: str) -> tuple[etree._Element | None, str]:
        """Find a style element by tag ('style:style', 'text:list-style') and name.

        Returns (element, location) with location one of 'content-auto',
        'common' (styles.xml office:styles) or 'styles-auto'.
        """
        where = [
            (self.content.find("office:automatic-styles", NS), "content-auto"),
            (self.styles.find("office:styles", NS), "common"),
            (self.styles.find("office:automatic-styles", NS), "styles-auto"),
        ]
        for container, loc in where:
            if container is None:
                continue
            for el in container.iterfind(tag, NS):
                if el.get(q("style:name")) == name:
                    return el, loc
        return None, ""


def attr(el: etree._Element, name: str, default: str | None = None) -> str | None:
    return el.get(q(name), default)


def plain_text(el: etree._Element) -> str:
    """Text of an element, one line per paragraph."""
    return "\n".join("".join(p.itertext()) for p in el.iter(q("text:p"), q("text:h"))).strip()
