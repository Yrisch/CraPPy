# CraPPy

Slides written in LibreOffice Impress, composited live over astrophysical
simulation snapshots, with movie transitions between them.

Each slide becomes two layers:

* **background**: what Impress draws as the slide background (colour, gradient,
  image, or a simulation snapshot); during a snapshot transition it is replaced
  by the frames of a clip;
* **content**: everything else (text, plots, master elements, slide number) as a
  transparent image, one per click step of the slide's object animations.

## Requirements

* LibreOffice (`soffice` in `PATH`)
* ffmpeg (only for movie transitions)
* Python ≥ 3.11

```sh
python -m venv .venv && .venv/bin/pip install -e '.[dev]'
```

## Usage

```sh
crappy info    talk.odp      # slides, click steps, transitions, warnings (fast)
crappy build   talk.odp      # -> talk.crappy/ (manifest.json + PNG layers)
crappy preview talk.odp      # build + talk.crappy/preview/*.png + contact_sheet.png
crappy play    talk.odp      # build if needed, then show it fullscreen
```

The build is cached: it only re-renders when the `.odp` or its side file changes.

## Showing a talk

`crappy play talk.odp` opens fullscreen on an external screen when there is
one (the projector; with several, one that is not the primary), otherwise on
the laptop screen. Options:
`--screen N` (see `--list-screens`), `--windowed`, `--start N` (slide number),
`--software` (no OpenGL).

| Action | Keys / mouse |
|---|---|
| next (click step or slide) | → ↓ Page Down Space N Enter, left click, wheel down |
| previous | ← ↑ Page Up Backspace P, right click, wheel up |
| go to slide | type its number, then Enter |
| first / last slide | Home / End |
| black / white screen | B or `.` / W or `,` (same key to come back) |
| fullscreen on/off | F or F11 |
| move to the next screen | S |
| quit | Esc or Q |

Going back replays transitions in reverse. During a transition, a key in the
same direction finishes it at once; the opposite direction turns it around.
Hidden slides are skipped (but reachable by number). The mouse cursor hides
after 2 s without movement.

## Writing a talk

* Name your slides (right-click in the slide pane → *Rename Slide*): the side
  file refers to slides by name, so reordering does not break anything.
* Snapshot backgrounds: Slide Properties → Background → Image, *stretched*.
* Slide transitions set in Impress are reproduced: cut, fade, fade through a
  colour, push, cover, uncover, wipe. Others fall back to a fade (with a warning).
* Object animations: entrance and exit effects (on click / with previous /
  after previous) become click steps. *Appear* is instant, any other effect is
  shown as a fade. Emphasis and motion paths are ignored (with a warning).
* A darkening layer over a snapshot: draw a semi-transparent black rectangle
  behind the text; its transparency is kept exactly.

## Movie transitions

Render your simulation as a frame sequence (`frame_00000.png`, `frame_00001.png`,
…). In Impress, set some of these frames as slide backgrounds (Slide
Properties → Background → Image, *stretched*). Impress remembers the file name
of a background picture, so CraPPy knows which frame each slide shows. Point the
side file at the sequence:

```toml
[movie]
frames = "../Movie_background/frame_*.png"   # relative to the side file
fps = 30
```

Between two consecutive slides whose backgrounds are frames of the movie, the
transition plays the movie from one frame to the other (backwards if needed):
`frame_00000` → `frame_00030` is a 1 s clip at 30 fps. The outgoing slide's
content fades out at the start, the incoming one fades in at the end. Going back
plays the clip in reverse; keys skip or turn it around like any transition.

`crappy info talk.odp` shows which transitions became clips. The build encodes
only the frames that are used (H.264, every frame a keyframe, full colour
resolution: visually lossless, and any frame decodes in a few ms), once: the
movie is re-encoded only when its frames change. Several sequences: use
`[[movie]]` tables.

## Side file `talk.crappy.toml`

Optional, next to `talk.odp`:

```toml
[defaults]
overlay_out = 0.3          # s, outgoing content fades at clip start
overlay_in  = 0.5          # s, incoming content fades in at clip end

[movie]                    # see "Movie transitions"
frames = "../Movie_background/frame_*.png"
fps = 30

[transition.halo_zoom]     # an explicit clip INTO the slide named "halo_zoom"
frames = "renders/zoom_halo/*.png"   # or: clip = "renders/zoom.mp4"
fps = 30

[transition."Conclusion and Perspectives"]   # override an Impress (or movie) transition
kind = "fade_color"
color = "#000000"
duration = 1.5
```

## How content transparency is obtained

LibreOffice cannot export a slide without its background, so every slide is
rendered twice over two solid backdrops *b1*, *b2*. A pixel of colour *C* and
opacity *a* renders as *R = aC + (1 − a)b*, so *R1 − R2 = (1 − a)(b1 − b2)* gives
*a*, then *C*: exact for anti-aliasing, transparency, gradients and shadows.

Text in Impress' *Automatic* colour turns white on dark backgrounds and black
on light ones, so the two backdrops are picked on the same side as the real
background: black/blue for dark slides, white/yellow for light ones (they
differ by 255 in blue, the channel perceived brightness weighs least).

The untouched talk is rendered as well and every rebuilt slide is compared with
it; a slide that does not match is retried with the other pair of backdrops,
and reported if it still differs.
