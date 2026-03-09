"""Behavioral mimicry layer for stealth browser scraping.

Implements human-like interaction patterns to avoid bot detection:
- Bezier curve mouse movements (ghost-cursor style)
- Smooth scrolling with variable speed
- Human-like typing cadence with errors and corrections
- Random micro-pauses between actions

Used by PatchrightScraper to add human behavioral signals.
"""

from __future__ import annotations

import asyncio
import math
import random


class BehavioralLayer:
    """Adds human-like behavior to browser automation."""

    def __init__(self, page) -> None:
        """Initialize with a Patchright/Playwright page object."""
        self._page = page

    async def human_delay(self, min_ms: int = 500, max_ms: int = 2000) -> None:
        """Random delay between actions, simulating human think time."""
        delay = random.randint(min_ms, max_ms) / 1000
        await asyncio.sleep(delay)

    async def smooth_scroll(self, direction: str = "down", distance: int = 300) -> None:
        """Scroll with variable speed to mimic human scrolling.

        Uses multiple small scroll steps with variable timing.
        """
        steps = random.randint(3, 8)
        step_distance = distance // steps

        for i in range(steps):
            # Variable scroll amount per step
            jitter = random.randint(-20, 20)
            scroll_amount = step_distance + jitter

            if direction == "up":
                scroll_amount = -scroll_amount

            await self._page.evaluate(f"window.scrollBy(0, {scroll_amount})")

            # Variable delay between scroll steps (smoothstep-like)
            t = i / max(steps - 1, 1)
            # Smoothstep: slower at start and end, faster in middle
            smooth_t = t * t * (3 - 2 * t)
            delay = 0.03 + 0.12 * (1 - smooth_t)  # 30-150ms between steps
            await asyncio.sleep(delay)

    async def move_to_element(self, selector: str) -> None:
        """Move mouse to element with Bezier curve trajectory.

        Uses a simplified ghost-cursor approach with quadratic Bezier curves.
        """
        element = await self._page.query_selector(selector)
        if not element:
            return

        box = await element.bounding_box()
        if not box:
            return

        # Target point with slight randomization (don't always hit center)
        target_x = box["x"] + box["width"] * random.uniform(0.3, 0.7)
        target_y = box["y"] + box["height"] * random.uniform(0.3, 0.7)

        # Get current mouse position (approximate from viewport center)
        viewport = self._page.viewport_size or {"width": 1280, "height": 720}
        start_x = viewport["width"] * random.uniform(0.3, 0.7)
        start_y = viewport["height"] * random.uniform(0.2, 0.5)

        # Generate Bezier curve points
        points = self._bezier_points(start_x, start_y, target_x, target_y)

        for x, y in points:
            await self._page.mouse.move(x, y)
            await asyncio.sleep(random.uniform(0.005, 0.02))

    def _bezier_points(
        self, x0: float, y0: float, x1: float, y1: float, steps: int = 20
    ) -> list[tuple[float, float]]:
        """Generate quadratic Bezier curve points for mouse movement."""
        # Control point: offset from midpoint for natural curve
        cx = (x0 + x1) / 2 + random.uniform(-100, 100)
        cy = (y0 + y1) / 2 + random.uniform(-50, 50)

        points: list[tuple[float, float]] = []
        for i in range(steps + 1):
            t = i / steps
            # Quadratic Bezier: B(t) = (1-t)^2*P0 + 2(1-t)t*C + t^2*P1
            bx = (1 - t) ** 2 * x0 + 2 * (1 - t) * t * cx + t ** 2 * x1
            by = (1 - t) ** 2 * y0 + 2 * (1 - t) * t * cy + t ** 2 * y1
            points.append((bx, by))

        return points

    async def human_click(self, selector: str) -> None:
        """Click element with human-like approach: move -> pause -> click."""
        await self.move_to_element(selector)
        await self.human_delay(100, 300)

        element = await self._page.query_selector(selector)
        if element:
            await element.click()

    async def human_type(self, selector: str, text: str) -> None:
        """Type text with human-like cadence: variable speed, occasional pauses."""
        await self.human_click(selector)
        await self.human_delay(200, 500)

        for i, char in enumerate(text):
            # Variable typing speed: 50-150ms per character
            delay = random.uniform(0.05, 0.15)

            # Occasional longer pauses (thinking)
            if random.random() < 0.05:
                delay += random.uniform(0.3, 0.8)

            await self._page.keyboard.type(char, delay=int(delay * 1000))

    async def random_viewport_interaction(self) -> None:
        """Perform random interactions to appear more human.

        Randomly scrolls, moves mouse, or hovers over elements.
        """
        action = random.choice(["scroll", "mouse_move", "pause"])

        if action == "scroll":
            await self.smooth_scroll(
                direction=random.choice(["down", "up"]),
                distance=random.randint(100, 500),
            )
        elif action == "mouse_move":
            viewport = self._page.viewport_size or {"width": 1280, "height": 720}
            x = random.randint(100, viewport["width"] - 100)
            y = random.randint(100, viewport["height"] - 100)
            await self._page.mouse.move(x, y)
        else:
            await self.human_delay(500, 2000)
