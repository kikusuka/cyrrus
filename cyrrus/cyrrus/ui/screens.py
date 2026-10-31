"""Shared presentation helpers for terminal setup screens."""
from .widgets import footer, panel, step_header


def welcome(ui):
    step_header(ui, 1, 6, "Welcome")
    panel(ui, "cyrrus", ["Add focused context and memory in front of a model.", "Configure it here; chat stays in your app."])


def review(ui, config):
    step_header(ui, 6, 6, "Review")
    provider = config.get("provider", {})
    gateway = config.get("gateway", {})
    panel(ui, "Ready to save", ["Provider: %s" % (provider.get("service") or "not selected"), "Gateway: %s" % gateway.get("mode", "inject")])
    footer(ui)
