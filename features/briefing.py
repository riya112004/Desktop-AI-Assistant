"""Daily briefing generator for first-open-of-day summaries."""

from __future__ import annotations

from datetime import datetime, timedelta

from connectors.weather import get_weather_summary
from core.llm_client import LLMError, create_llm_client
from db.database import Database


def _today_key(now: datetime | None = None) -> str:
    current = now or datetime.now().astimezone()
    return current.date().isoformat()


def _greeting_for_time(now: datetime, mode: str) -> str:
    hour = now.hour
    if mode == "light":
        if 5 <= hour < 12:
            return "Quick morning briefing"
        if 12 <= hour < 18:
            return "Quick afternoon briefing"
        return "Quick evening briefing"
    if 5 <= hour < 12:
        return "Good morning"
    if 12 <= hour < 18:
        return "Good afternoon"
    return "Good evening"


def _time_since_last_briefing(database: Database, now: datetime) -> float:
    last_time = database.get_state("last_briefing_time")
    if not last_time:
        return 0.0
    try:
        last_dt = datetime.fromisoformat(last_time)
        return (now - last_dt).total_seconds()
    except ValueError:
        return 0.0


def _format_reminder_due(due_at: str) -> str:
    try:
        value = datetime.fromisoformat(due_at)
        return value.strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return due_at


def _ranked_today_items(database: Database, now: datetime | None = None) -> list[str]:
    current = now or datetime.now().astimezone()
    items: list[tuple[datetime, int, str]] = []

    for reminder in database.list_reminders(status="pending"):
        due_at = datetime.fromisoformat(reminder["due_at"]).astimezone()
        urgency = 0 if due_at <= current else 1 if due_at.date() == current.date() else 2
        items.append((due_at, urgency, f"Reminder: {reminder['text']} ({_format_reminder_due(reminder['due_at'])})"))

    for item in database.dates_due_between(current.date().isoformat(), (current.date() + timedelta(days=6)).isoformat()):
        due_date = datetime.fromisoformat(item["date"]).astimezone()
        urgency = 0 if due_date.date() == current.date() else 1 if due_date.date() <= (current.date() + timedelta(days=2)) else 2
        label = f"{item['type'].title()}: {item['title']} ({item['date']})"
        items.append((due_date, urgency, label))

    ordered = sorted(items, key=lambda value: (value[1], value[0]))
    seen: set[str] = set()
    ranked: list[str] = []
    for _, _, entry in ordered:
        if entry not in seen:
            ranked.append(entry)
            seen.add(entry)
    return ranked[:8]


def _fallback_briefing(database: Database, now: datetime | None = None, mode: str = "full") -> str:
    current = now or datetime.now().astimezone()
    profile = database.get_profile()
    profile_name = profile.name if profile and profile.name else "you"
    city = profile.city if profile and profile.city else ""
    zodiac = profile.zodiac_sign if profile and profile.zodiac_sign else "your sign"

    items = _ranked_today_items(database, current)
    item_text = "\n- ".join(f"{index}. {item}" for index, item in enumerate(items, start=1)) if items else "- Nothing urgent is scheduled right now."
    pending_count = len(database.list_reminders(status="pending"))
    greeting = _greeting_for_time(current, mode)

    if profile is None:
        summary = (
            f"{greeting}. Here is your briefing for you:\n\n"
            "What matters today:\n"
            f"- {item_text}\n\n"
            "Your profile is still empty, so there is no personal detail to add yet.\n"
            f"You currently have {pending_count} active reminder(s)."
        )
    else:
        summary = (
            f"{greeting}. Here is your briefing for {profile_name}:\n\n"
            "What matters today:\n"
            f"- {item_text}\n\n"
            f"You currently have {pending_count} active reminder(s).\n"
            f"Horoscope (entertainment): {zodiac} energy is favorable for steady planning and quiet momentum today."
        )

    if city:
        weather = get_weather_summary(city, enabled=True)
        if weather:
            summary += f"\n\n{weather}"
    return summary.strip()


def generate_daily_briefing(database: Database, now: datetime | None = None) -> str:
    """Generate a full or short daily briefing based on the day-open flow."""
    current = now or datetime.now().astimezone()
    today = _today_key(current)
    last_date = database.get_state("last_briefing_date")
    last_kind = database.get_state("last_briefing_kind") or "full"
    last_time = database.get_state("last_briefing_time")

    if last_date == today and last_kind == "full":
        elapsed = _time_since_last_briefing(database, current)
        mode = "light" if elapsed >= 600 else "full"
    else:
        mode = "full"

    summary = _fallback_briefing(database, current, mode)
    database.set_state("last_briefing_date", today)
    database.set_state("last_briefing_kind", mode)
    database.set_state("last_briefing_time", current.isoformat(timespec="seconds"))
    return summary.strip()


def should_generate_daily_briefing(database: Database, now: datetime | None = None) -> bool:
    current = now or datetime.now().astimezone()
    today = _today_key(current)
    last_date = database.get_state("last_briefing_date")
    if not last_date or last_date != today:
        return True

    last_kind = database.get_state("last_briefing_kind") or "full"
    if last_kind != "full":
        return False

    elapsed = _time_since_last_briefing(database, current)
    return elapsed >= 600
