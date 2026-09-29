"""PNG frames -> one GIF. The second half of ``record-demo.mjs``.

Playwright's ffmpeg is built with almost every filter and muxer switched off, so it can
take a video apart but not put a GIF together. Pillow does that part, and does it better:
one adaptive palette for the whole animation rather than one per frame, which is what
keeps a dark interface from banding and flickering between frames.

    uv run --with pillow python scripts/frames-to-gif.py <frames dir> <out.gif> [fps]
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image

#: A GIF may have 256 colours; half of that is plenty for flat dark panels and a few
#: accents, and every colour dropped comes off every pixel. The palette has to be chosen
#: across the whole animation at once, or the frames flicker against each other.
COLOURS = 128

#: The longest any one frame stays up. A page waiting for somebody does not move for
#: twenty seconds at a stretch, and a loop that holds its last frame that long reads as
#: broken rather than finished.
LONGEST_HOLD = 1600

#: Mean difference per channel, out of 255, below which two frames are the same picture.
#: Video noise sits around one; a cursor moving or a badge changing colour is far above it.
NOISE = 1.2


def _blank(frame: Image.Image) -> bool:
    """A window with nothing drawn in it yet: one flat colour, whatever that colour is."""
    small = frame.convert("RGB").resize((32, 20), Image.Resampling.BILINEAR)
    lo, hi = min(small.tobytes()), max(small.tobytes())
    return hi - lo < 12


def _same(a: Image.Image, b: Image.Image) -> bool:
    """Whether two frames show the same thing.

    Not whether they are the same bytes: the video they came out of is lossy, so a page
    that has not moved still decodes a little differently each frame and an exact
    comparison collapses nothing. A thumbnail comparison asks the question that was meant
    -- has anything on the screen changed -- and ignores the noise underneath it.
    """
    small_a = a.resize((64, 40), Image.Resampling.BILINEAR).tobytes()
    small_b = b.resize((64, 40), Image.Resampling.BILINEAR).tobytes()
    apart = sum(abs(x - y) for x, y in zip(small_a, small_b, strict=True))
    return apart / len(small_a) < NOISE


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print(__doc__)
        return 2
    frames_dir, out = Path(argv[1]), Path(argv[2])
    fps = int(argv[3]) if len(argv) > 3 else 12

    shots = sorted(frames_dir.glob("*.png"))
    if not shots:
        print(f"no frames in {frames_dir}", file=sys.stderr)
        return 1
    # recording starts before the page does, so the take opens on an empty window. A GIF
    # that loops has no patience for it: the first thing a reader sees is the first frame.
    while len(shots) > 1 and _blank(Image.open(shots[0])):
        shots.pop(0)

    # one palette for the whole thing, taken from a frame in the middle: the first frames
    # are often a page still loading, and their colours are not the ones that matter
    middle = Image.open(shots[len(shots) // 2]).convert("RGB")
    palette = middle.quantize(colors=COLOURS, method=Image.Quantize.MEDIANCUT)

    # A page waiting for somebody is the same picture for seconds at a time, and writing
    # that picture forty times is most of the file. Runs of identical frames become one
    # frame that stays on screen longer, which looks the same and costs a fortieth.
    tick = round(1000 / fps)
    frames: list[Image.Image] = []
    holds: list[int] = []
    previous: Image.Image | None = None
    for shot in shots:
        original = Image.open(shot).convert("RGB")
        if previous is not None and _same(original, previous):
            holds[-1] = min(holds[-1] + tick, LONGEST_HOLD)
            continue
        frames.append(original.quantize(palette=palette))
        holds.append(tick)
        previous = original

    out.parent.mkdir(parents=True, exist_ok=True)
    frames[0].save(
        out,
        save_all=True,
        append_images=frames[1:],
        duration=holds,
        loop=0,
        optimize=True,
        # 1 leaves each frame on the screen for the next one to draw over. The interface
        # barely moves between frames -- a card changes colour, a number ticks -- so the
        # difference between this and a full redraw (2) is several times the file size.
        disposal=1,
    )
    size_mb = out.stat().st_size / 1_000_000
    print(f"  {len(shots)} frames -> {len(frames)} kept, {size_mb:.1f} MB -> {out}")
    if size_mb > 10:
        print("  (over 10 MB; GitHub will still show it, but consider a shorter take)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
