"""Screenshots -> one GIF. The second half of ``record-demo.mjs``.

The recorder leaves a folder of numbered PNGs and a ``holds.json`` beside them: how long
each one stays on screen, in milliseconds. A take is mostly pauses of different lengths --
a gate held long enough to read, a keystroke gone in a tenth of a second -- so the timing
belongs to each frame rather than to a frame rate.

    uv run --with pillow python scripts/frames-to-gif.py <frames dir> <out.gif>
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from PIL import Image

#: A GIF may have 256 colours, and a dark interface with a few accents fits in them
#: comfortably. The palette has to be chosen across the whole animation at once, or the
#: same panel comes out a slightly different grey from one frame to the next and flickers.
COLOURS = 256

#: How many frames the shared palette is sampled from. Every page the take visits should
#: be in it; a palette from one page draws the others in its colours.
SAMPLES = 12


def _palette(shots: list[Path]) -> Image.Image:
    """One palette for the whole take: the sampled frames side by side, quantised once."""
    step = max(1, len(shots) // SAMPLES)
    picked = [Image.open(p).convert("RGB") for p in shots[::step]]
    # a thumbnail of each is enough to find the colours, and quantising a wall of full-size
    # frames would take longer than the rest of the conversion
    small = [p.resize((p.width // 2, p.height // 2), Image.Resampling.NEAREST) for p in picked]
    wall = Image.new("RGB", (small[0].width, small[0].height * len(small)))
    for i, frame in enumerate(small):
        wall.paste(frame, (0, frame.height * i))
    return wall.quantize(colors=COLOURS, method=Image.Quantize.MEDIANCUT)


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print(__doc__)
        return 2
    frames_dir, out = Path(argv[1]), Path(argv[2])

    shots = sorted(frames_dir.glob("*.png"))
    if not shots:
        print(f"no frames in {frames_dir}", file=sys.stderr)
        return 1
    holds_file = frames_dir / "holds.json"
    holds_in: list[int] = (
        json.loads(holds_file.read_text("utf-8")) if holds_file.exists() else [100] * len(shots)
    )
    palette = _palette(shots)

    # A screenshot of a page that has not moved is the same bytes as the last one. Writing
    # it again costs a frame for nothing, so it becomes the previous frame held longer.
    frames: list[Image.Image] = []
    holds: list[int] = []
    previous: bytes | None = None
    for shot, hold in zip(shots, holds_in, strict=True):
        original = Image.open(shot).convert("RGB")
        raw = original.tobytes()
        if raw == previous:
            holds[-1] += hold
            continue
        # no dithering: it speckles flat panels, and every speckle is a pixel that differs
        # from the frame before and has to be written again
        frames.append(original.quantize(palette=palette, dither=Image.Dither.NONE))
        holds.append(hold)
        previous = raw

    out.parent.mkdir(parents=True, exist_ok=True)
    frames[0].save(
        out,
        save_all=True,
        append_images=frames[1:],
        duration=holds,
        loop=0,
        optimize=True,
        # 1 leaves each frame on the screen for the next one to draw over, so a frame
        # carries only the part of the page that changed -- a pointer moving across a
        # still page is a few hundred pixels, not a million
        disposal=1,
    )
    size_mb = out.stat().st_size / 1_000_000
    seconds = sum(holds) / 1000
    print(f"  {len(shots)} shots -> {len(frames)} frames, {seconds:.0f}s, {size_mb:.1f} MB")
    print(f"  -> {out}")
    if size_mb > 10:
        print("  (over 10 MB; GitHub will still show it, but consider a shorter take)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
