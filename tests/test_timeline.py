from pathlib import Path

import pytest

from crappy.player.deck import Deck, DeckSlide, Effect, Step
from crappy.player.timeline import Blend, Pos, Still, Timeline

FADE = Effect("fade", 1.0)
CUT = Effect()
STEP = Effect("timeline", 1.0)       # a click step whose effects last 1 s


def make_deck(*slides) -> Deck:
    """slides: (n_steps, transition, step duration, hidden[, auto steps])"""
    out = []
    for i, (n_steps, transition, step_duration, hidden, *auto) in enumerate(slides):
        auto = auto[0] if auto else set()
        steps = [Step(False, 0.0, ())] + [Step(k in auto, step_duration, ()) for k in range(1, n_steps)]
        out.append(DeckSlide(number=i + 1, name=f"s{i + 1}", hidden=hidden, notes="",
                             background=Path("bg.png"), layers=[], units_visible={}, steps=steps,
                             transition=transition))
    return Deck(Path("."), (1920, 1080), out)


@pytest.fixture
def tl():
    # slide 0: 2 steps (1 s of effects), slide 1: fade in, hidden slide 2, slide 3: cut in
    deck = make_deck((2, CUT, 1.0, False), (1, FADE, 0, False), (1, CUT, 0, True), (1, CUT, 0, False))
    return Timeline(deck)


def test_forward_through_steps_and_slides(tl):
    tl.next(0.0)
    assert tl.scene(0.5) == Blend(Pos(0, 0), Pos(0, 1), STEP, 0.5)
    assert tl.scene(1.0) == Still(Pos(0, 1))
    tl.next(2.0)
    assert tl.scene(2.25) == Blend(Pos(0, 1), Pos(1, 0), FADE, 0.25)
    assert tl.scene(3.5) == Still(Pos(1, 0))
    tl.next(4.0)                                # hidden slide 2 skipped, cut into slide 3
    assert tl.scene(4.0) == Still(Pos(3, 0))
    tl.next(5.0)                                # end of the talk: stays
    assert tl.scene(5.0) == Still(Pos(3, 0))


def test_backward_replays_transition_in_reverse(tl):
    tl.goto(1, 0.0)
    tl.prev(0.0)
    assert tl.scene(0.25) == Blend(Pos(0, 1), Pos(1, 0), FADE, 0.75)
    assert tl.scene(1.0) == Still(Pos(0, 1))    # lands on the last step of the previous slide
    tl.prev(1.0)
    assert tl.scene(1.5) == Blend(Pos(0, 0), Pos(0, 1), STEP, 0.5)
    assert tl.scene(2.0) == Still(Pos(0, 0))
    tl.prev(3.0)                                # start of the talk: stays
    assert tl.scene(3.0) == Still(Pos(0, 0))


def test_same_direction_skips_to_the_end(tl):
    tl.next(0.0)
    tl.next(0.3)
    assert tl.scene(0.3) == Still(Pos(0, 1))
    assert not tl.animating(0.3)


def test_opposite_direction_turns_around(tl):
    tl.next(0.0)
    tl.prev(0.75)                               # at p = 0.75, now heading back
    assert tl.scene(1.0) == Blend(Pos(0, 0), Pos(0, 1), STEP, 0.5)
    assert tl.scene(1.75) == Still(Pos(0, 0))
    # turning around twice
    tl.next(2.0)
    tl.prev(2.5)
    tl.next(2.75)
    assert tl.scene(2.75) == Blend(Pos(0, 0), Pos(0, 1), STEP, 0.25)
    assert tl.scene(3.5) == Still(Pos(0, 1))


def test_backward_animation_skip(tl):
    tl.goto(1, 0.0)
    tl.prev(0.0)
    tl.prev(0.1)                                # same direction: finish going back
    assert tl.scene(0.1) == Still(Pos(0, 1))


def test_goto_first_last(tl):
    tl.goto(3, 0.0)
    assert tl.scene(0.0) == Still(Pos(3, 0))
    tl.first(0.0)
    assert tl.scene(0.0) == Still(Pos(0, 0))
    tl.last(0.0)
    assert tl.scene(0.0) == Still(Pos(3, 0))
    tl.next(0.0)
    tl.goto(0, 0.1)                             # goto cancels a running animation
    assert not tl.animating(0.1)


def test_hidden_first_slide():
    deck = make_deck((1, CUT, 0, True), (1, CUT, 0, False))
    tl = Timeline(deck)
    assert tl.scene(0) == Still(Pos(1, 0))
    tl.prev(0)
    assert tl.scene(0) == Still(Pos(1, 0))


def test_neighbours(tl):
    tl.goto(1, 0.0)
    assert set(tl.neighbours()) == {Pos(1, 0), Pos(3, 0), Pos(0, 0), Pos(0, 1)}


def test_automatic_steps_chain():
    # slide 1 has effects that play by themselves once it appears (step 1, auto), then a click step
    deck = make_deck((1, CUT, 0, False), (3, FADE, 1.0, False, {1}))
    tl = Timeline(deck)
    tl.next(0.0)                                         # fade into slide 1 ...
    assert tl.scene(0.5) == Blend(Pos(0, 0), Pos(1, 0), FADE, 0.5)
    assert tl.scene(1.5) == Blend(Pos(1, 0), Pos(1, 1), STEP, 0.5)   # ... then its effects start alone
    assert tl.scene(2.0) == Still(Pos(1, 1))
    tl.next(3.0)                                         # the click step
    assert tl.scene(4.0) == Still(Pos(1, 2))
    tl.prev(5.0)
    tl.prev(6.0)                                         # back: the automatic effects rewind by themselves ...
    assert tl.scene(6.5) == Blend(Pos(1, 0), Pos(1, 1), STEP, 0.5)
    assert tl.scene(7.5) == Blend(Pos(0, 0), Pos(1, 0), FADE, 0.5)   # ... and the transition follows
    assert tl.scene(8.0) == Still(Pos(0, 0))
    tl.goto(1, 9.0)                                      # a jump lands after the automatic effects
    assert tl.scene(9.0) == Still(Pos(1, 1))
