# cyrrus/tools — development utilities

This directory holds development-only helpers. Nothing here is packaged with
`cyrrus`, and the `cyrrus` package never imports from it.

## make_terminal_art.py

Converts `assets/cyrrus-logo.png` into the terminal art constants in
`cyrrus/cyrrus/ui/art.py` (large braille, small braille, half-block, ASCII,
wordmark and wisp frames). The generated `art.py` is standard library only and
imports nothing third-party; this tool itself requires Pillow.

### Regenerating the art

Re-run whenever the logo changes:

    C:\Users\DELL\cyrrus_scratch\venv\Scripts\python.exe tools\make_terminal_art.py

This requires Pillow in the scratch venv:

    C:\Users\DELL\cyrrus_scratch\venv\Scripts\uv.exe pip install pillow --python C:\Users\DELL\cyrrus_scratch\venv

The tool:

1. Reads `assets/cyrrus-logo.png` (relative to the git root).
2. Verifies the bottom-right corner (x > 84% and y > 84%) contains only the
   small generator watermark star plus pure black. If any other artwork is
   found there, it **refuses** to convert (do not blank the corner).
3. Blanks that corner to pure black.
4. Renders each tier deterministically (fixed thresholds, no randomness) and
   writes `cyrrus/cyrrus/ui/art.py` with a regeneration header.

### Art tiers

- `LARGE_BRAILLE` (40x20) — 2x4 Braille dots per cell, with
  `LARGE_BRAILLE_COLOURS` (one cyan->blue RGB per row).
- `SMALL_BRAILLE` (14x7) — for menu headers.
- `HALF_BLOCK` (40x12) — ▄/▀/█/  fallback.
- `ASCII_ART` (60x20) — pure ASCII (all ord < 128).
- `WORDMARK` (5 rows) — block-letter "cyrrus" designed in code.
- `WISP_FRAMES` (4 frames) — drifting wisps for the intro animation.

All tiers fit within 80x24.
