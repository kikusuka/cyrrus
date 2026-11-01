r"""Dev tool: convert the cyrrus logo PNG into terminal art constants.

This tool is DEVELOPMENT ONLY. It lives in ``devtools/``, is never packaged and
is never imported by the ``cyrrus`` package (which is standard library only).
It requires Pillow, installed into the scratch venv under
``C:\Users\DELL\cyrrus_scratch\venv``.

It reads ``assets/cyrrus-logo.png`` (relative to the git root), verifies that
the bottom-right corner (x > 84% and y > 84%) contains nothing but the small
generator watermark star plus pure black, blanks that corner to pure black,
then renders several tiers of terminal art and writes them to
``cyrrus/cyrrus/ui/art.py`` as generated constants.

The conversion is deterministic: fixed thresholds, no randomness, no network.
Re-run this tool whenever the logo changes:

    C:\Users\DELL\cyrrus_scratch\venv\Scripts\python.exe tools\make_terminal_art.py
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import List, Tuple

from PIL import Image

# ---------------------------------------------------------------------------
# Paths (relative to the git root, i.e. the parent of the devtools/ folder)
# ---------------------------------------------------------------------------
GIT_ROOT = Path(__file__).resolve().parent.parent.parent
LOGO_PATH = GIT_ROOT / "assets" / "cyrrus-logo.png"
OUT_PATH = GIT_ROOT / "cyrrus" / "cyrrus" / "ui" / "art.py"

# ---------------------------------------------------------------------------
# Palette (sampled from the logo gradient: cyan top -> blue bottom)
# ---------------------------------------------------------------------------
CYAN: Tuple[int, int, int] = (90, 200, 220)
BLUE: Tuple[int, int, int] = (60, 150, 210)

# Corner watermark region: x > 84% and y > 84% of the image.
CORNER_X_FRAC = 0.84
CORNER_Y_FRAC = 0.84

# A pixel counts as "ink" (non-black artwork) when its brightest channel
# exceeds this. The watermark star is dark gray (~33-78), so this must be
# low enough to catch it but high enough to ignore near-black noise.
INK_THRESHOLD = 30

# Braille dot luminance threshold: a dot is "on" when the brightest pixel in
# its sub-bin exceeds this. Background is near-black (0-2), logo ink is bright.
BRAILLE_THRESHOLD = 60

# ---------------------------------------------------------------------------
# Braille dot bit layout (U+2800 base).
#   row\col: col0 col1
#   row0:    dot1   dot4      -> bits 0x01, 0x40
#   row1:    dot2   dot5      -> bits 0x02, 0x10
#   row2:    dot3   dot6      -> bits 0x04, 0x20
#   row3:    dot7   dot8      -> bits 0x80, 0x100
# ---------------------------------------------------------------------------
BRAILLE_DOTS = [
    [(0, 0, 0x01), (1, 0, 0x40)],
    [(0, 1, 0x02), (1, 1, 0x10)],
    [(0, 2, 0x04), (1, 2, 0x20)],
    [(0, 3, 0x80), (1, 3, 0x100)],
]


def _luminance(r: int, g: int, b: int) -> int:
    return int(0.299 * r + 0.587 * g + 0.114 * b)


def _ink_pixel(pixel: Tuple[int, int, int]) -> bool:
    return max(pixel) > INK_THRESHOLD


def verify_corner(im: Image.Image) -> Tuple[bool, str]:
    """Return (ok, reason) for the bottom-right watermark corner.

    Only the small gray watermark star plus pure/near-black may be present.
    Any other (especially coloured) artwork here means we must NOT blank it,
    because the artwork extends into the corner.
    """
    w, h = im.size
    x0 = int(CORNER_X_FRAC * w)
    y0 = int(CORNER_Y_FRAC * h)
    bright: List[Tuple[int, int, int, int, int]] = []
    for y in range(y0, h):
        for x in range(x0, w):
            r, g, b = im.getpixel((x, y))
            if max(r, g, b) > INK_THRESHOLD:
                bright.append((x, y, r, g, b))
    if not bright:
        return True, "corner is entirely black"
    # Every non-black pixel must be gray (r == g == b) - no coloured artwork.
    for (_x, _y, r, g, b) in bright:
        if not (r == g == b):
            return False, f"coloured artwork at ({_x},{_y}): {(r, g, b)}"
    # All ink must be confined to a compact region (the small star).
    xs = [p[0] for p in bright]
    ys = [p[1] for p in bright]
    if (max(xs) - min(xs)) > 80 or (max(ys) - min(ys)) > 80:
        return False, f"watermark ink too spread: x {min(xs)}-{max(xs)}, y {min(ys)}-{max(ys)}"
    return True, f"compact gray watermark star ({len(bright)} pixels)"


def blank_corner(im: Image.Image) -> None:
    """Set every pixel with x > 84% and y > 84% to pure black."""
    w, h = im.size
    x0 = int(CORNER_X_FRAC * w)
    y0 = int(CORNER_Y_FRAC * h)
    for y in range(y0, h):
        for x in range(x0, w):
            im.putpixel((x, y), (0, 0, 0))


def _sample_luminance(im: Image.Image, x0: int, y0: int, x1: int, y1: int) -> int:
    """Maximum luminance in a rectangular region (captures thin ink)."""
    best = 0
    w, h = im.size
    x1 = min(x1, w)
    y1 = min(y1, h)
    for y in range(y0, y1):
        for x in range(x0, x1):
            r, g, b = im.getpixel((x, y))
            lum = _luminance(r, g, b)
            if lum > best:
                best = lum
    return best


def render_braille(
    im: Image.Image, cols: int, rows: int, threshold: int = BRAILLE_THRESHOLD
) -> List[str]:
    """Render a Braille (2x4 dots per cell) art grid."""
    w, h = im.size
    cell_w = w / cols
    cell_h = h / rows
    out: List[str] = []
    for r in range(rows):
        line_chars = []
        y0 = int(r * cell_h)
        y1 = int((r + 1) * cell_h)
        for c in range(cols):
            x0 = int(c * cell_w)
            x1 = int((c + 1) * cell_w)
            # Split the cell into 2 columns x 4 rows of dot sub-bins.
            dot_w = max(1, (x1 - x0) // 2)
            dot_h = max(1, (y1 - y0) // 4)
            bits = 0
            for dot_row in BRAILLE_DOTS:
                for (dc, dr, bit) in dot_row:
                    bx0 = x0 + dc * dot_w
                bx1 = x0 + (dc + 1) * dot_w
                by0 = y0 + dr * dot_h
                by1 = y0 + (dr + 1) * dot_h
                if _sample_luminance(im, bx0, by0, bx1, by1) > threshold:
                    bits |= bit
            line_chars.append(chr(0x2800 + bits))
        out.append("".join(line_chars))
    return out


def render_half_block(im: Image.Image, cols: int, rows: int) -> List[str]:
    """Render a half-block (▄/▀/█/ ) art grid.

    Each character cell covers one column-width and two row-heights of source;
    the top half maps to ▄, the bottom half to ▀, both to █.
    """
    w, h = im.size
    cell_w = w / cols
    cell_h = (h / rows) * 2  # two source rows per output char
    out: List[str] = []
    for r in range(rows):
        line_chars = []
        y_top0 = int(r * cell_h)
        y_top1 = int(r * cell_h + cell_h / 2)
        y_bot0 = int(r * cell_h + cell_h / 2)
        y_bot1 = int((r + 1) * cell_h)
        for c in range(cols):
            x0 = int(c * cell_w)
            x1 = int((c + 1) * cell_w)
            top = _sample_luminance(im, x0, y_top0, x1, y_top1)
            bot = _sample_luminance(im, x0, y_bot0, x1, y_bot1)
            if top > BRAILLE_THRESHOLD and bot > BRAILLE_THRESHOLD:
                line_chars.append("\u2588")  # █ full
            elif top > BRAILLE_THRESHOLD:
                line_chars.append("\u2584")  # ▄ lower half (top half lit)
            elif bot > BRAILLE_THRESHOLD:
                line_chars.append("\u2580")  # ▀ upper half (bottom half lit)
            else:
                line_chars.append(" ")
        out.append("".join(line_chars))
    return out


def render_ascii(
    im: Image.Image, cols: int, rows: int
) -> List[str]:
    """Render a plain ASCII art grid (all ord < 128)."""
    chars = " .:-=+*#%@"
    w, h = im.size
    cell_w = w / cols
    cell_h = h / rows
    out: List[str] = []
    for r in range(rows):
        line_chars = []
        y0 = int(r * cell_h)
        y1 = int((r + 1) * cell_h)
        for c in range(cols):
            x0 = int(c * cell_w)
            x1 = int((c + 1) * cell_w)
            lum = _sample_luminance(im, x0, y0, x1, y1)
            idx = min(len(chars) - 1, lum * len(chars) // 256)
            line_chars.append(chars[idx])
        out.append("".join(line_chars))
    return out


def _interpolate(
    start: Tuple[int, int, int], end: Tuple[int, int, int], t: float
) -> Tuple[int, int, int]:
    return (
        int(start[0] + (end[0] - start[0]) * t),
        int(start[1] + (end[1] - start[1]) * t),
        int(start[2] + (end[2] - start[2]) * t),
    )


def gradient_colours(rows: int) -> List[Tuple[int, int, int]]:
    """One RGB colour per row, interpolating cyan (top) -> blue (bottom)."""
    return [_interpolate(CYAN, BLUE, r / max(rows - 1, 1)) for r in range(rows)]


# ---------------------------------------------------------------------------
# Designed in code (no image): 5-row block-letter wordmark "cyrrus".
# Each letter is 5x5; letters separated by one blank column.
# ---------------------------------------------------------------------------
_LETTERS = {
    "c": [
        " .##. ",
        " #   #",
        " #    ",
        " #   #",
        " .##. ",
    ],
    "y": [
        "#   #",
        " # # ",
        "  #  ",
        "  #  ",
        "  #  ",
    ],
    "r": [
        "###  ",
        "# #  ",
        "###  ",
        "# #  ",
        "# #  ",
    ],
    "u": [
        "#   #",
        "#   #",
        "#   #",
        "#   #",
        " .##. ",
    ],
    "s": [
        " .##. ",
        " #    ",
        " .##  ",
        "    # ",
        " .##. ",
    ],
}

WORDMARK_LETTERS = ["c", "y", "r", "r", "u", "s"]


def render_wordmark() -> List[str]:
    """5-row block-letter wordmark "cyrrus" (all ASCII)."""
    letter_rows = [_LETTERS[ch] for ch in WORDMARK_LETTERS]
    height = len(letter_rows[0])
    out: List[str] = []
    for ri in range(height):
        out.append(" ".join(letters[ri] for letters in letter_rows))
    return out


# ---------------------------------------------------------------------------
# Designed in code (no image): wisp frames for the intro animation.
# Each frame is a list of equal-length strings using '.' (faint) and '*' (ink).
# ---------------------------------------------------------------------------
WISP_FRAMES: List[List[str]] = [
    # Frame 1: wisp entering from the left.
    [
        "          ....          ",
        "         ...  ...       ",
        "        ...      ...    ",
        "         ...  ...       ",
        "          ....          ",
    ],
    # Frame 2: wisp moves toward the centre.
    [
        "                 ....   ",
        "                ...  ...",
        "               ...      ",
        "                ...  ...",
        "                 ....   ",
    ],
    # Frame 3: wisp at the centre, brightest.
    [
        "          ....          ",
        "         ...**...       ",
        "        ...****...      ",
        "         ...**...       ",
        "          ....          ",
    ],
    # Frame 4: wisp dissolves toward the right.
    [
        "   ....                 ",
        "  ...  ...              ",
        "       ...              ",
        "  ...  ...              ",
        "   ....                 ",
    ],
]


def _normalize_wisp(frame: List[str], width: int) -> List[str]:
    """Pad/truncate every line of a wisp frame to ``width``."""
    out = []
    for line in frame:
        line = line[:width].ljust(width)
        out.append(line.rstrip())
    return out


def wisp_frames(width: int) -> List[List[str]]:
    """Return the wisp frames normalised to ``width`` columns."""
    return [_normalize_wisp(f, width) for f in WISP_FRAMES]


# ---------------------------------------------------------------------------
# Assemble art.py
# ---------------------------------------------------------------------------
def build_art_module() -> str:
    im = Image.open(LOGO_PATH).convert("RGB")

    ok, reason = verify_corner(im)
    if not ok:
        raise SystemExit(
            f"refusing to convert logo: corner check failed - {reason}\n"
            "The artwork appears to extend into the bottom-right 84% corner. "
            "Do not blank it."
        )
    print(f"corner check ok: {reason}")

    blank_corner(im)

    large_braille = render_braille(im, 40, 20)
    small_braille = render_braille(im, 14, 7)
    half_block = render_half_block(im, 40, 12)
    ascii_art = render_ascii(im, 60, 20)
    wordmark = render_wordmark()

    large_colours = gradient_colours(len(large_braille))

    lines: List[str] = []
    lines.append('"""Generated terminal art for the cyrrus logo. STANDARD LIBRARY ONLY.' + "\n")
    lines.append("DO NOT EDIT BY HAND. Regenerate with:" + "\n")
    lines.append("    C:/Users/DELL/cyrrus_scratch/venv/Scripts/python.exe devtools/make_terminal_art.py" + "\n")
    lines.append("Requires Pillow (dev only, scratch venv). This module imports nothing third-party." + "\n")
    lines.append("Tiers: LARGE_BRAILLE (40x20, per-row cyan->blue colours), SMALL_BRAILLE (14x7)," + "\n")
    lines.append("HALF_BLOCK (40x12), ASCII_ART (60x20), WORDMARK (5 rows, 'cyrrus'), WISP_FRAMES." + "\n")
    lines.append('"""' + "\n\n")
    lines.append("from __future__ import annotations\n\n")
    lines.append("from typing import List, Tuple\n\n")
    lines.append("CYAN: Tuple[int, int, int] = (90, 200, 220)\n")
    lines.append("BLUE: Tuple[int, int, int] = (60, 150, 210)\n\n")
    lines.append("LARGE_BRAILLE_ROWS: int = 20\n")
    lines.append("LARGE_BRAILLE_COLS: int = 40\n")
    lines.append("SMALL_BRAILLE_ROWS: int = 7\n")
    lines.append("SMALL_BRAILLE_COLS: int = 14\n")
    lines.append("HALF_BLOCK_ROWS: int = 12\n")
    lines.append("HALF_BLOCK_COLS: int = 40\n")
    lines.append("ASCII_ART_ROWS: int = 20\n")
    lines.append("ASCII_ART_COLS: int = 60\n\n")

    def _write_list(name: str, value: List[str]) -> None:
        lines.append(f"{name}: List[str] = [")
        for line in value:
            lines.append(f"    {line!r},")
        lines.append("]\n")

    def _write_colours(name: str, value: List[Tuple[int, int, int]]) -> None:
        lines.append(f"{name}: List[Tuple[int, int, int]] = [")
        for rgb in value:
            lines.append(f"    {rgb},")
        lines.append("]\n")

    def _write_wisps(name: str, value: List[List[str]]) -> None:
        lines.append(f"{name}: List[List[str]] = [")
        for frame in value:
            lines.append("    [")
            for line in frame:
                lines.append(f"        {line!r},")
            lines.append("    ],")
        lines.append("]\n")

    _write_list("LARGE_BRAILLE", large_braille)
    _write_colours("LARGE_BRAILLE_COLOURS", large_colours)
    _write_list("SMALL_BRAILLE", small_braille)
    _write_list("HALF_BLOCK", half_block)
    _write_list("ASCII_ART", ascii_art)
    _write_list("WORDMARK", wordmark)
    _write_wisps("WISP_FRAMES", wisp_frames(max(len(max(wordmark, key=len)), 40)))

    return "".join(lines)


def main() -> None:
    if not LOGO_PATH.exists():
        raise SystemExit(f"logo not found: {LOGO_PATH}")
    content = build_art_module()
    OUT_PATH.write_text(content, encoding="utf-8")
    print(f"wrote {OUT_PATH}")


if __name__ == "__main__":
    main()
