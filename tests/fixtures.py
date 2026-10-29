# SPDX-FileCopyrightText: 2026 Yann Bernard <yannbernard13@gmail.com>
# SPDX-License-Identifier: CECILL-2.1

"""A small hand-written presentation covering what the build has to handle.

Slide 1 "dark":  solid black background, text in Automatic colour (-> white).
Slide 2 "steps": default (white) background, fade transition of 1 s,
                 a 3-item bullet list and a red rectangle;
                 click 1: rectangle appears, click 2: bullet 3 appears (fade 0.5 s).
"""

from __future__ import annotations

from lxml import etree

from crappy.odf import OdfPackage

_NS = (
    'xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
    'xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0" '
    'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" '
    'xmlns:draw="urn:oasis:names:tc:opendocument:xmlns:drawing:1.0" '
    'xmlns:fo="urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0" '
    'xmlns:svg="urn:oasis:names:tc:opendocument:xmlns:svg-compatible:1.0" '
    'xmlns:presentation="urn:oasis:names:tc:opendocument:xmlns:presentation:1.0" '
    'xmlns:anim="urn:oasis:names:tc:opendocument:xmlns:animation:1.0" '
    'xmlns:smil="urn:oasis:names:tc:opendocument:xmlns:smil-compatible:1.0" '
    'xmlns:loext="urn:org:documentfoundation:names:experimental:office:xmlns:loext:1.0" '
    'xmlns:xlink="http://www.w3.org/1999/xlink" office:version="1.3"'
)

STYLES = f"""<?xml version="1.0" encoding="UTF-8"?>
<office:document-styles {_NS}>
 <office:styles>
  <style:style style:name="standard" style:family="graphic">
   <style:graphic-properties draw:fill="none" draw:stroke="none"/>
   <style:text-properties style:use-window-font-color="true" fo:font-size="24pt"/>
  </style:style>
 </office:styles>
 <office:automatic-styles>
  <style:page-layout style:name="PM1">
   <style:page-layout-properties fo:margin-top="0cm" fo:margin-bottom="0cm" fo:margin-left="0cm"
     fo:margin-right="0cm" fo:page-width="28cm" fo:page-height="15.75cm" style:print-orientation="landscape"/>
  </style:page-layout>
  <style:style style:name="Mdp1" style:family="drawing-page">
   <style:drawing-page-properties draw:fill="none"/>
  </style:style>
 </office:automatic-styles>
 <office:master-styles>
  <style:master-page style:name="Default" style:page-layout-name="PM1" draw:style-name="Mdp1"/>
 </office:master-styles>
</office:document-styles>
"""

CONTENT = f"""<?xml version="1.0" encoding="UTF-8"?>
<office:document-content {_NS}>
 <office:automatic-styles>
  <style:style style:name="dp_dark" style:family="drawing-page">
   <style:drawing-page-properties draw:fill="solid" draw:fill-color="#000000"
     presentation:background-visible="true" presentation:background-objects-visible="true"/>
  </style:style>
  <style:style style:name="dp_steps" style:family="drawing-page">
   <style:drawing-page-properties presentation:background-visible="true"
     presentation:background-objects-visible="true" smil:type="fade" smil:subtype="crossfade"
     presentation:transition-speed="medium"/>
  </style:style>
  <style:style style:name="gr_text" style:family="graphic" style:parent-style-name="standard">
   <style:graphic-properties draw:fill="none" draw:stroke="none" draw:textarea-vertical-align="top"/>
  </style:style>
  <style:style style:name="gr_rect" style:family="graphic" style:parent-style-name="standard">
   <style:graphic-properties draw:fill="solid" draw:fill-color="#ff0000" draw:stroke="none"/>
  </style:style>
  <style:style style:name="P1" style:family="paragraph">
   <style:text-properties fo:font-size="28pt"/>
  </style:style>
  <style:style style:name="T1" style:family="text">
   <style:text-properties fo:font-weight="bold" style:use-window-font-color="true" loext:opacity="0%"/>
  </style:style>
  <text:list-style style:name="L1">
   <text:list-level-style-bullet text:level="1" text:bullet-char="●">
    <style:list-level-properties text:min-label-width="1cm"/>
    <style:text-properties fo:font-family="OpenSymbol" style:use-window-font-color="true" fo:font-size="45%"/>
   </text:list-level-style-bullet>
  </text:list-style>
 </office:automatic-styles>
 <office:body>
  <office:presentation>
   <draw:page draw:name="dark" draw:style-name="dp_dark" draw:master-page-name="Default">
    <draw:frame draw:style-name="gr_text" svg:x="2cm" svg:y="2cm" svg:width="24cm" svg:height="3cm">
     <draw:text-box><text:p text:style-name="P1">Automatic colour on black</text:p></draw:text-box>
    </draw:frame>
   </draw:page>
   <draw:page draw:name="steps" draw:style-name="dp_steps" draw:master-page-name="Default"
     xml:id="pg2" draw:id="pg2">
    <draw:frame draw:style-name="gr_text" svg:x="2cm" svg:y="2cm" svg:width="14cm" svg:height="10cm">
     <draw:text-box>
      <text:list text:style-name="L1">
       <text:list-item><text:p text:style-name="P1">First <text:span text:style-name="T1">bullet</text:span></text:p></text:list-item>
       <text:list-item><text:p text:style-name="P1">Second bullet</text:p></text:list-item>
       <text:list-item><text:p xml:id="p3" text:id="p3" text:style-name="P1">Third <text:span text:style-name="T1">bullet</text:span></text:p></text:list-item>
      </text:list>
     </draw:text-box>
    </draw:frame>
    <draw:rect draw:style-name="gr_rect" xml:id="r1" draw:id="r1"
      svg:x="18cm" svg:y="4cm" svg:width="8cm" svg:height="6cm"/>
    <anim:par presentation:node-type="timing-root">
     <anim:par smil:begin="pg2.begin">
      <anim:transitionFilter smil:dur="1s" smil:type="fade" smil:subtype="crossfade"/>
     </anim:par>
     <anim:seq presentation:node-type="main-sequence">
      <anim:par smil:begin="next"><anim:par smil:begin="0s">
       <anim:par smil:begin="0s" smil:fill="hold" presentation:node-type="on-click"
         presentation:preset-class="entrance" presentation:preset-id="ooo-entrance-appear">
        <anim:set smil:begin="0s" smil:dur="0.001s" smil:fill="hold" smil:targetElement="r1"
          smil:attributeName="visibility" smil:to="visible"/>
       </anim:par>
      </anim:par></anim:par>
      <anim:par smil:begin="next"><anim:par smil:begin="0s">
       <anim:par smil:begin="0s" smil:fill="hold" presentation:node-type="on-click"
         presentation:preset-class="entrance" presentation:preset-id="ooo-entrance-fade-in">
        <anim:set smil:begin="0s" smil:dur="0.001s" smil:fill="hold" smil:targetElement="p3"
          anim:sub-item="text" smil:attributeName="visibility" smil:to="visible"/>
        <anim:transitionFilter smil:dur="0.5s" smil:targetElement="p3" anim:sub-item="text"
          smil:type="fade" smil:subtype="crossfade" smil:mode="in"/>
       </anim:par>
      </anim:par></anim:par>
     </anim:seq>
    </anim:par>
   </draw:page>
  </office:presentation>
 </office:body>
</office:document-content>
"""

MANIFEST = """<?xml version="1.0" encoding="UTF-8"?>
<manifest:manifest xmlns:manifest="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0" manifest:version="1.3">
 <manifest:file-entry manifest:full-path="/" manifest:media-type="application/vnd.oasis.opendocument.presentation"/>
 <manifest:file-entry manifest:full-path="content.xml" manifest:media-type="text/xml"/>
 <manifest:file-entry manifest:full-path="styles.xml" manifest:media-type="text/xml"/>
</manifest:manifest>
"""

# geometry on a 28 x 15.75 cm page, as fractions of the page (x0, y0, x1, y1)
LIST_BOX = (2 / 28, 2 / 15.75, 16 / 28, 12 / 15.75)
RECT_BOX = (18 / 28, 4 / 15.75, 26 / 28, 10 / 15.75)


def make_package() -> OdfPackage:
    files = {
        "mimetype": b"application/vnd.oasis.opendocument.presentation",
        "content.xml": CONTENT.encode(),
        "styles.xml": STYLES.encode(),
        "META-INF/manifest.xml": MANIFEST.encode(),
    }
    return OdfPackage(files, etree.fromstring(files["content.xml"]), etree.fromstring(files["styles.xml"]))


# --- a talk on a movie ----------------------------------------------------------

MOVIE_SIZE = (640, 360)


def make_frames(folder, n: int = 5):
    """Synthetic rendered frames frame_00000.png ... : distinct colours + a gradient."""
    import numpy as np
    from PIL import Image
    folder.mkdir(parents=True, exist_ok=True)
    w, h = MOVIE_SIZE
    ramp = np.linspace(0, 60, w)[None, :, None]
    paths = []
    for k in range(n):
        rgb = np.broadcast_to(np.array([30 + 40 * k, 60, 200 - 35 * k], float), (h, w, 3)) + ramp
        path = folder / f"frame_{k:05d}.png"
        Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8)).save(path)
        paths.append(path)
    return paths


def make_movie_package(frames, backgrounds=(0, 4, 1)) -> OdfPackage:
    """One slide per entry of `backgrounds`: a stretched picture background that is
    that frame (inserted from its file, so named after it) and a line of text."""
    fill_images, page_styles, pages, files = [], [], [], {}
    for i, k in enumerate(backgrounds):
        stem = frames[k].stem
        member = f"Pictures/{stem}.png"
        files[member] = frames[k].read_bytes()
        fill_images.append(f'<draw:fill-image draw:name="{stem.replace("_", "_5f_")}" draw:display-name="{stem}" '
                           f'xlink:href="{member}" xlink:type="simple" xlink:show="embed" xlink:actuate="onLoad"/>')
        page_styles.append(f'<style:style style:name="dp{i}" style:family="drawing-page"><style:drawing-page-properties '
                           f'presentation:background-visible="true" presentation:background-objects-visible="true" '
                           f'draw:fill="bitmap" draw:fill-image-name="{stem.replace("_", "_5f_")}" style:repeat="stretch"/>'
                           f'</style:style>')
        pages.append(f'<draw:page draw:name="s{i + 1}" draw:style-name="dp{i}" draw:master-page-name="Default">'
                     f'<draw:frame draw:style-name="gr_text" svg:x="2cm" svg:y="2cm" svg:width="20cm" svg:height="3cm">'
                     f'<draw:text-box><text:p text:style-name="P1">Slide {i + 1}</text:p></draw:text-box></draw:frame>'
                     f'</draw:page>')
    styles = STYLES.replace("<office:styles>", "<office:styles>" + "".join(fill_images))
    content = CONTENT[:CONTENT.index("<office:body>")].replace(
        "<office:automatic-styles>", "<office:automatic-styles>" + "".join(page_styles))
    content += "<office:body><office:presentation>" + "".join(pages) + \
        "</office:presentation></office:body></office:document-content>"
    # LibreOffice treats an undeclared member as a damaged package
    entries = "".join(f'<manifest:file-entry manifest:full-path="{m}" manifest:media-type="image/png"/>' for m in files)
    files |= {
        "mimetype": b"application/vnd.oasis.opendocument.presentation",
        "content.xml": content.encode(), "styles.xml": styles.encode(),
        "META-INF/manifest.xml": MANIFEST.replace("</manifest:manifest>", entries + "</manifest:manifest>").encode(),
    }
    return OdfPackage(files, etree.fromstring(files["content.xml"]), etree.fromstring(files["styles.xml"]))
