"""Monochrome design system for the optional cyrrus UI.

The brief's mapping table is the source of truth: one hand-authored
black/grey/white palette, hierarchy carried by bold, dim, reverse and
underline rather than hue.  ``NO_COLOR`` is therefore already satisfied by
the palette; the emphasis attributes stay in place when it is set.  Textual
downsamples the palette to 256-colour terminals without losing meaning.
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from typing import Dict, Mapping, Optional, Sequence


VARIANT_LIGHT = "light"
VARIANT_DARK = "dark"

# Original Breezy Trace roles are documented in the brief; this table only
# keeps the monochrome replacement and the attribute that carries it.
ROLE_ATTRIBUTES = {
    "body": "",
    "heading": "bold",
    "muted": "dim",
    "faint": "dim",
    "footer-key": "bold",
    "selection": "reverse bold",
    "active-tab": "bold underline",
    "toast": "reverse bold",
    "focused-rule": "bold",
    "state": "bold",
}


def color_enabled(env: Optional[Mapping[str, str]] = None) -> bool:
    """NO_COLOR disables colour, not emphasis (the palette has no hues)."""
    environment = os.environ if env is None else env
    return "NO_COLOR" not in environment or not environment.get("NO_COLOR")


def _variables(variant: str) -> Dict[str, str]:
    if variant == VARIANT_DARK:
        return {
            "cyrrus-rule": "#808080",
            "cyrrus-rule-focus": "#ffffff",
            "cyrrus-muted": "#b0b0b0",
            "cyrrus-faint": "#707070",
            "cyrrus-selected-bg": "#ffffff",
            "cyrrus-selected-fg": "#000000",
            "cyrrus-toast-bg": "#ffffff",
            "cyrrus-toast-fg": "#000000",
            "cyrrus-tab-active": "#ffffff",
            "cyrrus-surface": "#101010",
        }
    return {
        "cyrrus-rule": "#808080",
        "cyrrus-rule-focus": "#000000",
        "cyrrus-muted": "#555555",
        "cyrrus-faint": "#808080",
        "cyrrus-selected-bg": "#000000",
        "cyrrus-selected-fg": "#ffffff",
        "cyrrus-toast-bg": "#000000",
        "cyrrus-toast-fg": "#ffffff",
        "cyrrus-tab-active": "#000000",
        "cyrrus-surface": "#f2f2f2",
    }


def build_theme(variant: str = VARIANT_LIGHT):
    """Build a Textual theme for one monochrome variant."""
    from textual.theme import Theme

    if variant not in (VARIANT_LIGHT, VARIANT_DARK):
        raise ValueError("variant must be 'light' or 'dark'")
    dark = variant == VARIANT_DARK
    variables = _variables(variant)
    return Theme(
        name="cyrrus-" + variant,
        primary="#ffffff" if dark else "#000000",
        secondary="#b0b0b0" if dark else "#555555",
        warning="#ffffff" if dark else "#000000",
        error="#ffffff" if dark else "#000000",
        success="#ffffff" if dark else "#000000",
        accent="#ffffff" if dark else "#000000",
        foreground="#ffffff" if dark else "#000000",
        background="#000000" if dark else "#ffffff",
        surface=variables["cyrrus-surface"],
        panel=variables["cyrrus-surface"],
        dark=dark,
        ansi=False,
        variables=variables,
    )


def theme_css(no_color: Optional[bool] = None) -> str:
    """Shared CSS.  Colours are only black/white/grey in both variants."""
    if no_color is None:
        no_color = not color_enabled()
    note = "/* NO_COLOR: monochrome attributes carry meaning */\n" if no_color else ""
    return note + """
Screen {
    background: $background;
    color: $foreground;
}
.topbar {
    height: 1;
    background: $surface;
    color: $foreground;
}
.topbar .brand {
    color: $primary;
    text-style: bold;
}
.topbar .counts {
    color: $foreground;
}
.topbar .attention {
    color: $foreground;
    text-style: bold;
}
.topbar .help {
    color: $cyrrus-faint;
}
.panel {
    border: round $cyrrus-rule;
    background: $background;
    color: $foreground;
}
.panel:focus-within {
    border: round $cyrrus-rule-focus;
}
.panel-title {
    color: $cyrrus-muted;
    text-style: bold;
}
.panel:focus-within .panel-title {
    color: $foreground;
}
.heading {
    color: $foreground;
    text-style: bold;
}
.muted {
    color: $cyrrus-muted;
    text-style: dim;
}
.faint {
    color: $cyrrus-faint;
    text-style: dim;
}
.selected {
    background: $cyrrus-selected-bg;
    color: $cyrrus-selected-fg;
    text-style: reverse bold;
}
.state-clean, .state-dirty, .state-ahead, .state-behind,
.state-attention, .state-decision {
    color: $foreground;
    text-style: bold;
}
.tabbar {
    height: 1;
}
.tabbar .tab {
    color: $cyrrus-muted;
}
.tabbar .tab.active {
    color: $cyrrus-tab-active;
    text-style: bold underline;
}
.footer {
    height: 1;
    background: $surface;
    color: $foreground;
}
.footer .key {
    text-style: bold;
}
.footer .description {
    color: $foreground;
}
.toast {
    background: $cyrrus-toast-bg;
    color: $cyrrus-toast-fg;
    text-style: reverse bold;
}
.panel-title, .heading {
    text-style: bold;
}
"""


@dataclass(frozen=True)
class Glyphs:
    check: str
    cross: str
    bullet: str
    arrow: str
    spinner: str
    ramp: str
    spark: str
    bar: str = "\u2588"


_BASIC = Glyphs(
    check="\u221a",          # √
    cross="\u00d7",          # ×
    bullet="\u00b7",         # ·
    arrow="->",
    spinner="|/-\\",
    ramp="\u00b7\u2591\u2592\u2593\u2588",
    spark="\u00b7\u2591\u2592\u2593\u2588",
)
_FULL = Glyphs(
    check="\u2713",          # ✓
    cross="\u00d7",          # ×
    bullet="\u00b7",         # ·
    arrow="\u2192",          # →
    spinner="\u280b\u2819\u2839\u2838\u283c\u2834\u2826\u2827\u2807\u280f",
    ramp="\u00b7\u2591\u2592\u2593\u2588",
    spark="\u2581\u2582\u2583\u2584\u2585\u2586\u2587\u2588",
)


def choose_glyphs(
    platform: Optional[str] = None,
    env: Optional[Mapping[str, str]] = None,
) -> Glyphs:
    """Pick the brief's glyph set.

    Windows legacy consoles get the basic set; Windows Terminal (``WT_SESSION``)
    and every non-Windows platform get the full set.  ``CYRRUS_GLYPHS`` forces
    either mode for tests and for terminals we cannot detect.
    """
    environment = os.environ if env is None else env
    current = sys.platform if platform is None else platform
    forced = (environment.get("CYRRUS_GLYPHS") or "").strip().lower()
    if forced == "full":
        return _FULL
    if forced == "basic":
        return _BASIC
    if current == "win32" and not environment.get("WT_SESSION"):
        return _BASIC
    return _FULL


def glyphs() -> Glyphs:
    return choose_glyphs()


def density_ramp(values: Sequence[float], maximum: Optional[float] = None) -> str:
    """Map numeric intensities onto ``·░▒▓█`` (heat and 30-day ramps)."""
    ramp = glyphs().ramp
    series = list(values)
    if not series:
        return ""
    if maximum is None:
        maximum = max(series) if series else 0
    if maximum is None or maximum <= 0:
        return ramp[0] * len(series)
    out = []
    for value in series:
        fraction = max(0.0, min(1.0, float(value) / float(maximum)))
        out.append(ramp[min(len(ramp) - 1, int(fraction * len(ramp)))])
    return "".join(out)


def sparkline(values: Sequence[float], maximum: Optional[float] = None) -> str:
    """Sparkline using the full block set when available."""
    chars = glyphs().spark
    series = list(values)
    if not series:
        return ""
    top = max(series) if maximum is None else maximum
    if top <= 0:
        return chars[0] * len(series)
    out = []
    for value in series:
        fraction = max(0.0, min(1.0, float(value) / top))
        out.append(chars[min(len(chars) - 1, int(fraction * len(chars)))])
    return "".join(out)


def block_bar(fraction: float, width: int = 8) -> str:
    """A block bar; zero still draws a one-eighth baseline."""
    chars = "\u2581\u2582\u2583\u2584\u2585\u2586\u2587\u2588"
    fraction = max(0.0, min(1.0, float(fraction)))
    index = min(len(chars) - 1, int(fraction * (len(chars) - 1)))
    return chars[index] * max(0, int(width))


def state_text(state: str, text: Optional[str] = None) -> str:
    """Semantic state prefixes from the brief (no colour needed)."""
    labels = {
        "clean": "\u221a",
        "dirty": "\u00b1",
        "ahead": "\u2191",
        "behind": "\u2193",
        "attention": "!",
        "decision": "\u25c6",
    }
    prefix = labels.get(state, "?")
    return prefix + (" " + text if text else "")
