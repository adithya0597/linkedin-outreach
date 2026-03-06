"""Dashboard theme system — extract hardcoded colors to configurable themes."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ThemeColors:
    """Color palette for the dashboard."""
    # Validation status
    validation_pass: str
    validation_fail: str
    validation_borderline: str
    # H1B status
    h1b_confirmed: str
    h1b_likely: str
    h1b_unknown: str
    h1b_explicit_no: str
    h1b_na: str
    # General
    primary: str
    success: str
    warning: str
    danger: str


LIGHT = ThemeColors(
    validation_pass="#2d6a2e",
    validation_fail="#8b2020",
    validation_borderline="#8b6914",
    h1b_confirmed="#2d6a2e",
    h1b_likely="#4a7c4b",
    h1b_unknown="#8b6914",
    h1b_explicit_no="#8b2020",
    h1b_na="#666666",
    primary="#1f77b4",
    success="#2d6a2e",
    warning="#8b6914",
    danger="#8b2020",
)

DARK = ThemeColors(
    validation_pass="#4CAF50",
    validation_fail="#EF5350",
    validation_borderline="#FFC107",
    h1b_confirmed="#4CAF50",
    h1b_likely="#81C784",
    h1b_unknown="#FFC107",
    h1b_explicit_no="#EF5350",
    h1b_na="#9E9E9E",
    primary="#42A5F5",
    success="#4CAF50",
    warning="#FFC107",
    danger="#EF5350",
)

_THEMES = {"light": LIGHT, "dark": DARK}


def get_theme(name: str = "light") -> ThemeColors:
    """Get theme by name. Defaults to light."""
    return _THEMES.get(name.lower(), LIGHT)
