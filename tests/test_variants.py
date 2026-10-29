# SPDX-FileCopyrightText: 2026 Yann Bernard <yannbernard13@gmail.com>
# SPDX-License-Identifier: CECILL-2.1

from fixtures import make_package

from crappy.animations import parse_slide_animation
from crappy.odf import NS, q
from crappy.variants import StepHider, set_page_backdrops, strip_to_background


def _text_props(pkg, name):
    style, _ = pkg.find_style("style:style", name)
    return style.find("style:text-properties", NS)


def test_set_page_backdrops():
    pkg = make_package()
    set_page_backdrops(pkg, {0: "#0000ff", 1: "#ffff00"})
    dark, steps = pkg.pages()
    for page, color in ((dark, "#0000ff"), (steps, "#ffff00")):
        style, _ = pkg.find_style("style:style", page.get(q("draw:style-name")))
        props = style.find("style:drawing-page-properties", NS)
        assert (props.get(q("draw:fill")), props.get(q("draw:fill-color"))) == ("solid", color)
    # the transition settings travel with the copied page style
    style, _ = pkg.find_style("style:style", steps.get(q("draw:style-name")))
    assert style[0].get(q("smil:type")) == "fade"
    # original styles and the master are left alone
    assert pkg.find_style("style:style", "dp_dark")[0][0].get(q("draw:fill-color")) == "#000000"
    assert pkg.find_style("style:style", "Mdp1")[0][0].get(q("draw:fill")) == "none"


def test_strip_to_background():
    pkg = make_package()
    strip_to_background(pkg)
    assert all(len(page) == 0 for page in pkg.pages())
    assert all(p.get(q("presentation:background-objects-visible")) == "false"
               for p in pkg.content.iter(q("style:drawing-page-properties")))


def test_hider_step0_removes_shape_and_hides_paragraph():
    pkg = make_package()
    page = pkg.pages()[1]
    hider = StepHider(pkg)
    hider.apply(page, parse_slide_animation(page), 0)
    assert not hider.warnings

    assert page.find(".//draw:rect", NS) is None
    p3 = page.xpath(".//*[@xml:id='p3']", namespaces=NS)[0]
    para_style = p3.get(q("text:style-name"))
    assert para_style.startswith("crappy_hidden_")
    props = _text_props(pkg, para_style)
    assert props.get(q("loext:opacity")) == "0%"
    # character transparency is ignored on the Automatic colour: the hidden text needs a real one
    assert props.get(q("style:use-window-font-color")) == "false" and props.get(q("fo:color"))
    span_style = p3.find("text:span", NS).get(q("text:style-name"))
    assert _text_props(pkg, span_style).get(q("loext:opacity")) == "0%"
    # the original styles, used by visible paragraphs, are untouched
    assert _text_props(pkg, "P1").get(q("loext:opacity")) is None
    # bullet blanked through a list style override keeping the label width
    item = p3.getparent()
    override, _ = pkg.find_style("text:list-style", item.get(q("text:style-override")))
    level = override.find("text:list-level-style-bullet", NS)
    assert level.get(q("text:bullet-char")) == " "
    assert level.find("style:list-level-properties", NS).get(q("text:min-label-width")) == "1cm"
    # other bullets keep the original list style
    assert page.findall(".//text:list-item", NS)[0].get(q("text:style-override")) is None


def test_hider_last_step_changes_nothing():
    pkg = make_package()
    page = pkg.pages()[1]
    StepHider(pkg).apply(page, parse_slide_animation(page), 2)
    assert page.find(".//draw:rect", NS) is not None
    p3 = page.xpath(".//*[@xml:id='p3']", namespaces=NS)[0]
    assert p3.get(q("text:style-name")) == "P1"


def test_hider_blanks_numbered_lists():
    pkg = make_package()
    lst, _ = pkg.find_style("text:list-style", "L1")
    lst.remove(lst[0])
    lst.append(pkg.content.makeelement(q("text:list-level-style-number"), {
        q("text:level"): "1", q("style:num-format"): "1", q("style:num-suffix"): "."}))
    page = pkg.pages()[1]
    StepHider(pkg).apply(page, parse_slide_animation(page), 0)
    p3 = page.xpath(".//*[@xml:id='p3']", namespaces=NS)[0]
    override, _ = pkg.find_style("text:list-style", p3.getparent().get(q("text:style-override")))
    level = override.find("text:list-level-style-number", NS)
    assert level.get(q("style:num-format")) == "" and level.get(q("style:num-suffix")) is None


def test_missing_target_is_reported():
    from crappy.animations import Effect, SlideAnimation
    pkg = make_package()
    hider = StepHider(pkg)
    hider.apply(pkg.pages()[1], SlideAnimation(groups=[[], [Effect("ghost", None, "entrance", "x", 0)]]), 0)
    assert "ghost" in hider.warnings[0]


def test_save_roundtrip(tmp_path):
    from crappy.odf import OdfPackage
    pkg = make_package()
    pkg.save(tmp_path / "a.odp")
    again = OdfPackage.load(tmp_path / "a.odp")
    assert [p.get(q("draw:name")) for p in again.pages()] == ["dark", "steps"]
    import zipfile
    with zipfile.ZipFile(tmp_path / "a.odp") as z:
        first = z.infolist()[0]
        assert first.filename == "mimetype" and first.compress_type == zipfile.ZIP_STORED
