# SPDX-FileCopyrightText: 2026 Yann Bernard <yannbernard13@gmail.com>
# SPDX-License-Identifier: CECILL-2.1

from fixtures import make_package

from crappy.background import BACKDROPS, DARK_BRIGHTNESS, background_class, brightness, hex_to_rgb
from crappy.odf import NS, q


def test_backdrop_pairs_stay_on_their_side():
    for cls, pair in BACKDROPS.items():
        for color in pair:
            dark = brightness(hex_to_rgb(color)) <= DARK_BRIGHTNESS
            assert dark == (cls == "dark"), color


def test_classes_of_fixture():
    pkg = make_package()
    assert [background_class(pkg, p) for p in pkg.pages()] == ["dark", "light"]


def test_gradient_and_master_fill():
    pkg = make_package()
    common = pkg.styles.find("office:styles", NS)
    common.append(pkg.styles.makeelement(q("draw:gradient"), {
        q("draw:name"): "night", q("draw:start-color"): "#000000", q("draw:end-color"): "#202040"}))
    props = pkg.find_style("style:style", "dp_steps")[0][0]
    props.set(q("draw:fill"), "gradient")
    props.set(q("draw:fill-gradient-name"), "night")
    assert background_class(pkg, pkg.pages()[1]) == "dark"

    # no fill on the slide: the master decides
    del props.attrib[q("draw:fill")]
    master = pkg.find_style("style:style", "Mdp1")[0][0]
    master.set(q("draw:fill"), "solid")
    master.set(q("draw:fill-color"), "#101010")
    assert background_class(pkg, pkg.pages()[1]) == "dark"


def test_threshold_measured_on_libreoffice():
    # (colour, text LibreOffice 26.8 draws on it in Automatic colour)
    measured = [("#9e9e9e", "white"), ("#9f9f9f", "black"), ("#ff0000", "white"), ("#00ff00", "black"),
                ("#0000ff", "white"), ("#ff8000", "black"), ("#808000", "white"), ("#00a800", "white")]
    for color, text in measured:
        dark = brightness(hex_to_rgb(color)) <= DARK_BRIGHTNESS
        assert dark == (text == "white"), color
