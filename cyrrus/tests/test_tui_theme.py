"""Monochrome design-system tests (brief mapping table)."""
from __future__ import annotations

from cyrrus.tui import theme


def test_light_and_dark_variants_are_monochrome():
    light = theme.build_theme("light")
    dark = theme.build_theme("dark")

    assert light.name == "cyrrus-light"
    assert dark.name == "cyrrus-dark"
    assert light.background.lower() == "#ffffff" and light.foreground.lower() == "#000000"
    assert dark.background.lower() == "#000000" and dark.foreground.lower() == "#ffffff"
    assert light.dark is False and dark.dark is True

    for t in (light, dark):
        for key in (
            "cyrrus-rule",
            "cyrrus-rule-focus",
            "cyrrus-muted",
            "cyrrus-faint",
            "cyrrus-selected-bg",
            "cyrrus-toast-bg",
        ):
            assert key in t.variables


def test_selection_and_states_carry_meaning_without_colour():
    css = theme.theme_css()
    assert "text-style: reverse bold" in css
    assert "text-style: bold underline" in css
    assert "text-style: bold" in css
    assert "text-style: dim" in css


def test_no_color_is_honoured_but_palette_stays_legible():
    assert theme.color_enabled({}) is True
    assert theme.color_enabled({"NO_COLOR": "1"}) is False
    # The palette is already monochrome; NO_COLOR must not remove the
    # emphasis attributes that carry the hierarchy.
    css = theme.theme_css(no_color=True)
    assert "reverse bold" in css
    assert "bold underline" in css


def test_glyph_fallback_windows():
    basic = theme.choose_glyphs(platform="win32", env={})
    full_wt = theme.choose_glyphs(platform="win32", env={"WT_SESSION": "1"})
    full_env = theme.choose_glyphs(platform="win32", env={"CYRRUS_GLYPHS": "full"})
    forced_basic = theme.choose_glyphs(platform="linux", env={"CYRRUS_GLYPHS": "basic"})

    assert basic.check == "\u221a"          # √
    assert basic.cross == "\u00d7"          # ×
    assert basic.ramp == "\u00b7\u2591\u2592\u2593\u2588"
    assert full_wt.check == "\u2713"        # ✓
    assert full_env.check == "\u2713"
    assert forced_basic.check == "\u221a"
    assert theme.choose_glyphs(platform="linux", env={}).check == "\u2713"


def test_density_ramp_and_block_bars():
    assert theme.density_ramp([0, 1, 2, 3, 4], maximum=4) == "\u00b7\u2591\u2592\u2593\u2588"
    assert theme.density_ramp([0, 0, 0], maximum=0) == "\u00b7\u00b7\u00b7"
    assert theme.block_bar(0.0, width=4) == "\u2581\u2581\u2581\u2581"
    assert theme.block_bar(1.0, width=4) == "\u2588\u2588\u2588\u2588"
    assert len(theme.sparkline([1, 4, 2, 8])) == 4
