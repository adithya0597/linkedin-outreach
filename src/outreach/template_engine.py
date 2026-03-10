"""Jinja2 template engine for outreach messages with char limit enforcement."""

from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader


class CharCounter:
    """Strict character count validation."""

    LIMITS = {
        "connection_request": 300,
        "inmail": 400,
        "comment": 280,
        "follow_up": None,  # No limit
        "recruiter_message": None,
        "pre_engagement": 280,
    }

    @classmethod
    def validate(cls, text: str, message_type: str) -> tuple[bool, int, int | None]:
        """Returns (is_valid, actual_count, limit)."""
        limit = cls.LIMITS.get(message_type)
        count = len(text)
        if limit is None:
            return True, count, limit
        return count <= limit, count, limit


class OutreachTemplateEngine:
    def __init__(self, template_dir: str | None = None):
        if template_dir is None:
            template_dir = str(Path(__file__).parent / "templates")
        Path(template_dir).mkdir(parents=True, exist_ok=True)
        self.env = Environment(
            loader=FileSystemLoader(template_dir),
            trim_blocks=True,
            lstrip_blocks=True,
        )

    def render(
        self,
        template_name: str,
        context: dict,
        message_type: str = "follow_up",
    ) -> tuple[str, bool, int]:
        """Render a template with context. Returns (text, is_valid, char_count)."""
        template = self.env.get_template(template_name)
        rendered = template.render(**context).strip()

        is_valid, count, _limit = CharCounter.validate(rendered, message_type)
        return rendered, is_valid, count

    def list_templates(self) -> list[str]:
        """List available template files."""
        return self.env.list_templates()


class SequenceBuilder:
    """Build 14-day multi-touch outreach calendars."""

    def __init__(self):
        self.touch_schedule = {
            "pre_engagement": -1,
            "connection_request": 1,
            "follow_up": 4,
            "deeper_engagement": 9,
            "final_touch": 14,
        }

    def build_sequence(
        self, start_date: str, contact_name: str, company_name: str
    ) -> list[dict]:
        """Build a 14-day sequence starting from a given date."""
        from datetime import datetime, timedelta

        start = datetime.strptime(start_date, "%Y-%m-%d")
        sequence = []

        for step_name, day_offset in self.touch_schedule.items():
            touch_date = start + timedelta(days=day_offset)

            # Adjust to Tue/Thu if on Mon/Wed/Fri/Sat/Sun
            weekday = touch_date.weekday()  # 0=Mon
            if weekday in (0, 4, 5, 6):  # Mon, Fri, Sat, Sun
                # Move to next Tuesday
                days_until_tue = (1 - weekday) % 7
                if days_until_tue == 0:
                    days_until_tue = 7
                touch_date += timedelta(days=days_until_tue)
            elif weekday == 2:  # Wednesday -> Thursday
                touch_date += timedelta(days=1)

            sequence.append({
                "step": step_name,
                "date": touch_date.strftime("%Y-%m-%d"),
                "day": touch_date.strftime("%A"),
                "time": "9:00-11:00 AM recipient TZ",
                "contact": contact_name,
                "company": company_name,
            })

        return sequence
