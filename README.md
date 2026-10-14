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
* Python ≥ 3.11

```sh
python -m venv .venv && .venv/bin/pip install -e '.[dev]'
```

## Usage

```sh
crappy info    talk.odp      # slides, click steps, transitions, warnings (fast)
crappy build   talk.odp      # -> talk.crappy/ (manifest.json + PNG layers)
crappy preview talk.odp      # build + talk.crappy/preview/*.png + contact_sheet.png
```

The build is cached: it only re-renders when the `.odp` or its side file changes.

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

## Side file `talk.crappy.toml`

Optional, next to `talk.odp`:

```toml
[defaults]
overlay_out = 0.3          # s, outgoing content fades at clip start
overlay_in  = 0.5          # s, incoming content fades in at clip end

[transition.halo_zoom]     # transition INTO the slide named "halo_zoom"
frames = "renders/zoom_halo/*.png"
fps = 30

[transition."Conclusion and Perspectives"]   # override an Impress transition
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
differ by 255 in blue, the channel LibreOffice's luminance weighs least).

The untouched talk is rendered as well and every rebuilt slide is compared with
it; a slide that does not match is retried with the other pair of backdrops,
and reported if it still differs.
