"""Tests for dashboard theme system."""

import re
from dataclasses import fields, FrozenInstanceError

import pytest

from src.dashboard.themes import DARK, LIGHT, ThemeColors, get_theme


HEX_PATTERN = re.compile(r"^#[0-9A-Fa-f]{6}$")


class TestGetTheme:
    def test_get_theme_light(self):
        theme = get_theme("light")
        assert theme is LIGHT

    def test_get_theme_dark(self):
        theme = get_theme("dark")
        assert theme is DARK

    def test_get_theme_unknown_falls_back_to_light(self):
        theme = get_theme("unknown")
        assert theme is LIGHT

    def test_get_theme_case_insensitive(self):
        assert get_theme("DARK") is DARK
        assert get_theme("Light") is LIGHT


class TestThemeColorsImmutable:
    def test_frozen_dataclass(self):
        with pytest.raises(FrozenInstanceError):
            LIGHT.primary = "#000000"  # type: ignore[misc]


class TestColorValidity:
    def test_all_light_colors_are_valid_hex(self):
        for field in fields(LIGHT):
            value = getattr(LIGHT, field.name)
            assert HEX_PATTERN.match(value), (
                f"LIGHT.{field.name} = {value!r} is not a valid hex color"
            )

    def test_all_dark_colors_are_valid_hex(self):
        for field in fields(DARK):
            value = getattr(DARK, field.name)
            assert HEX_PATTERN.match(value), (
                f"DARK.{field.name} = {value!r} is not a valid hex color"
            )
