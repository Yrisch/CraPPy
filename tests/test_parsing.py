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


def test_step_effects():
    anim = parse_slide_animation(make_package().pages()[1])
    assert anim.step_effect(0).kind == "cut"
    assert anim.step_effect(1).kind == "cut"            # appear
    eff = anim.step_effect(2)                            # fade-in, 0.5 s
    assert (eff.kind, eff.duration) == ("fade", 0.5)


def test_exit_effect_hides_from_its_step():
    from crappy.animations import Effect, SlideAnimation
    anim = SlideAnimation(groups=[[], [Effect("a", None, "exit", "ooo-exit-disappear", 0)]])
    assert anim.hidden_at(0) == set()
    assert anim.hidden_at(1) == {("a", None)}
    assert anim.has_exit


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
    slides, warnings = analyse(make_package(), cfg)
    assert [s.name for s in slides] == ["dark", "steps"]
    assert slides[1].clip is not None and slides[1].clip.fps == 24
    t = slides[0].transition
    assert (t.kind, t.side, t.duration, t.source) == ("push", "left", 0.8, "config")
    assert not warnings

    _, warnings = analyse(make_package(), Config(overrides={"nope": TransitionOverride(kind="fade")}))
    assert "nope" in warnings[0]
