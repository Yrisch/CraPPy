import pytest
from fixtures import make_package

from crappy.animations import parse_duration, parse_slide_animation
from crappy.build import analyse
from crappy.config import Config
from crappy.transitions import parse_transition


def test_parse_duration():
    assert parse_duration("0.5s") == 0.5
    assert parse_duration("2") == 2.0
    assert parse_duration("250ms") == 0.25
    assert parse_duration("indefinite") == 0.0
    assert parse_duration(None) == 0.0


def test_click_groups():
    pkg = make_package()
    dark, steps = pkg.pages()
    assert parse_slide_animation(dark).n_steps == 1

    anim = parse_slide_animation(steps)
    assert anim.n_steps == 3
    assert [[e.target for e in g] for g in anim.groups] == [[], ["r1"], ["p3"]]
    assert anim.groups[2][0].sub_item == "text"
    assert not anim.warnings


def test_hidden_targets_per_step():
    anim = parse_slide_animation(make_package().pages()[1])
    assert anim.hidden_at(0) == {("r1", None), ("p3", "text")}
    assert anim.hidden_at(1) == {("p3", "text")}
    assert anim.hidden_at(2) == set()


def test_effect_kinds_and_timing():
    anim = parse_slide_animation(make_package().pages()[1])
    appear, fade = anim.groups[1][0], anim.groups[2][0]
    assert (appear.kind, appear.start) == ("show", 0.0)
    assert (fade.kind, fade.duration) == ("fade_in", 0.5)
    assert anim.group_duration(2) == 0.5 and not anim.auto_start
    assert anim.units == [("r1", None), ("p3", "text")]
    assert not anim.initially_visible(("r1", None))


def test_exit_effect_hides_from_its_step():
    from crappy.animations import Effect, SlideAnimation
    anim = SlideAnimation(groups=[[], [Effect("a", None, "exit", "ooo-exit-disappear", 0, kind="hide")]])
    assert anim.hidden_at(0) == set()
    assert anim.hidden_at(1) == {("a", None)}
    assert anim.initially_visible(("a", None))


def _effect(node_type, cls, preset, begin, body, slot="0s"):
    return (f'<anim:par smil:begin="{slot}"><anim:par smil:begin="{begin}" smil:fill="hold" '
            f'presentation:node-type="{node_type}" presentation:preset-class="{cls}" '
            f'presentation:preset-id="{preset}" smil:accelerate="0.5" smil:decelerate="0.5">{body}</anim:par></anim:par>')


def test_delays_motion_paths_and_slide_start_effects():
    """Effects before the first click (group 0), after-previous slots with a Delay, motion paths."""
    from lxml import etree

    from crappy.odf import NS
    show = '<anim:set smil:begin="0s" smil:dur="0.001s" smil:targetElement="{t}" smil:attributeName="visibility" smil:to="visible"/>'
    move = '<anim:animateMotion smil:dur="2s" smil:targetElement="b" svg:path="M0 0 L0.5 0"/>'
    xml = (f'<draw:page {" ".join(f"xmlns:{k}={chr(34)}{v}{chr(34)}" for k, v in NS.items() if k != "xml")}>'
           '<draw:rect xml:id="a"/><draw:rect xml:id="b"/>'
           '<anim:par presentation:node-type="timing-root"><anim:seq presentation:node-type="main-sequence">'
           '<anim:par smil:begin="0s">' + _effect("after-previous", "entrance", "ooo-entrance-appear", "0.5s",
                                                 show.format(t="a")) + '</anim:par>'
           '<anim:par smil:begin="next">'
           + _effect("on-click", "motion-path", "libo-motionpath-curve", "0s", move)
           + _effect("after-previous", "entrance", "ooo-entrance-appear", "0.25s", show.format(t="a"), slot="2s")
           + '</anim:par></anim:seq></anim:par></draw:page>')
    anim = parse_slide_animation(etree.fromstring(xml))
    assert anim.auto_start and anim.groups[0][0].start == 0.5
    motion, after = anim.groups[1]
    assert (motion.kind, motion.path, motion.duration, motion.accelerate) == ("motion", "M0 0 L0.5 0", 2.0, 0.5)
    assert after.start == pytest.approx(2.25)                   # slot 2 s (after the motion) + Delay 0.25 s
    assert anim.group_duration(1) == pytest.approx(2.251)


def test_transition_from_page_style_and_timing():
    pkg = make_package()
    t, warnings = parse_transition(pkg, pkg.pages()[1])
    assert (t.kind, t.duration) == ("fade", 1.0)
    assert not warnings
    t, _ = parse_transition(pkg, pkg.pages()[0])
    assert t.kind == "cut"


def test_transition_kinds():
    from crappy.odf import q
    pkg = make_package()
    page = pkg.pages()[1]
    props = pkg.find_style("style:style", "dp_steps")[0][0]
    cases = {
        ("pushWipe", "fromLeft", None): ("push", "left"),
        ("slideWipe", "fromTop", None): ("cover", "top"),
        ("slideWipe", "fromTop", "reverse"): ("uncover", "top"),
        ("barWipe", "leftToRight", None): ("wipe", "left"),
        ("barWipe", "leftToRight", "reverse"): ("wipe", "right"),
        ("fade", "fadeOverColor", None): ("fade_color", None),
    }
    for (typ, sub, direction), (kind, side) in cases.items():
        props.set(q("smil:type"), typ)
        props.set(q("smil:subtype"), sub)
        props.attrib.pop(q("smil:direction"), None)
        if direction:
            props.set(q("smil:direction"), direction)
        t, warnings = parse_transition(pkg, page)
        assert (t.kind, t.side) == (kind, side), (typ, sub, direction)
        assert not warnings

    props.set(q("smil:type"), "irisWipe")
    t, warnings = parse_transition(pkg, page)
    assert t.kind == "fade" and warnings


def test_analyse_applies_config():
    from crappy.config import ClipSpec, TransitionOverride
    cfg = Config(clips={"steps": ClipSpec(fps=24)},
                 overrides={"1": TransitionOverride(kind="push", side="left", duration=0.8)},
                 )
    analysis = analyse(make_package(), cfg)
    slides, warnings = analysis.slides, analysis.warnings
    assert [s.name for s in slides] == ["dark", "steps"]
    assert slides[1].clip is not None and slides[1].clip.fps == 24 and slides[1].clip.source == "config"
    t = slides[0].transition
    assert (t.kind, t.side, t.duration, t.source) == ("push", "left", 0.8, "config")
    assert not warnings

    warnings = analyse(make_package(), Config(overrides={"nope": TransitionOverride(kind="fade")})).warnings
    assert "nope" in warnings[0]
