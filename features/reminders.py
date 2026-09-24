"""Local reminder parsing, scheduling, and notification lifecycle."""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Callable

from apscheduler.schedulers.background import BackgroundScheduler
from dateutil.relativedelta import relativedelta
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from core.llm_client import LLMClient
from db.database import Database, Reminder


class ReminderIntent(BaseModel):
    model_config = ConfigDict(extra="ignore")
    operation: str = "none"
    response: str = ""
    text: str | None = None
    due_at: str | None = None
    recurrence_rule: str | None = None

    @field_validator("due_at")
    @classmethod
    def valid_due_at(cls, value: str | None) -> str | None:
        if value is not None:
            datetime.fromisoformat(value)
        return value


REMINDER_PROMPT = """You manage local reminders only. Return JSON only with this shape:
{"operation":"none|add","response":"","text":null,"due_at":null,"recurrence_rule":null}
For a reminder request, operation is add, text is the exact task, due_at is an ISO-8601
local timestamp with timezone, and recurrence_rule is null, daily, weekly, monthly, yearly,
or an interval such as every 5 minutes. Resolve natural language using CURRENT DATE/TIME. Never invent a missing
time; ask a clarification question in response instead. Always include the parsed due_at
in response for confirmation. This app is fully local and does not use external services.
"""


def extract_reminder_intent(client: LLMClient, message: str, now: datetime | None = None) -> ReminderIntent:
    if not is_reminder_request(message):
        return ReminderIntent()
    current_time = now or datetime.now().astimezone()
    current = current_time.isoformat(timespec="seconds")
    try:
        result = client.chat_json(
            f"{REMINDER_PROMPT}\nCURRENT DATE/TIME: {current}",
            [{"role": "user", "content": message}],
        )
        intent = ReminderIntent.model_validate(result)
    except (ValidationError, ValueError) as error:
        raise ValueError("The AI returned an invalid reminder operation.") from error
    relative_due = _relative_due_time(message, current_time)
    if relative_due is not None and intent.operation == "add":
        intent = intent.model_copy(update={"due_at": relative_due})
    if intent.operation == "add":
        updates: dict[str, str] = {}
        recurrence_rule = _recurrence_rule(message)
        interval_due = _interval_due_time(recurrence_rule, current_time)
        clock_due = _clock_due_time(message, current_time, recurrence_rule)
        if recurrence_rule is not None:
            updates["recurrence_rule"] = recurrence_rule
        if interval_due is not None:
            updates["due_at"] = interval_due
        if clock_due is not None:
            updates["due_at"] = clock_due
        if updates:
            intent = intent.model_copy(update=updates)
    if intent.operation == "add" and (not intent.text or not intent.due_at):
        return ReminderIntent(operation="none", response="Please provide the reminder task and due time.")
    return intent


def is_reminder_request(message: str) -> bool:
    normalized = message.lower()
    return any(phrase in normalized for phrase in ("remind me", "set a reminder", "set reminder", "reminder"))


def _relative_due_time(message: str, now: datetime) -> str | None:
    match = re.search(r"(?:in|after)\s+(\d+)\s*(minute|minutes|min|hour|hours|hr|hrs)\b", message.lower())
    if not match:
        return None
    amount = int(match.group(1))
    unit = match.group(2)
    delta = timedelta(hours=amount) if unit in {"hour", "hours", "hr", "hrs"} else timedelta(minutes=amount)
    return (now + delta).isoformat(timespec="seconds")


def _recurrence_rule(message: str) -> str | None:
    normalized = " ".join(message.lower().split())
    interval = re.search(
        r"\bevery\s+(\d+)\s*(second|seconds|sec|secs|minute|minutes|min|mins|hour|hours|hr|hrs|day|days)\b",
        normalized,
    )
    if interval:
        unit = interval.group(2)
        if unit.startswith("sec"):
            unit = "seconds"
        elif unit.startswith("min"):
            unit = "minutes"
        elif unit.startswith("h"):
            unit = "hours"
        else:
            unit = "days"
        return f"interval:{interval.group(1)}:{unit}"
    if re.search(r"\b(every day|daily|each day)\b", normalized):
        return "daily"
    if re.search(r"\b(every week|weekly|each week)\b", normalized):
        return "weekly"
    if re.search(r"\b(every month|monthly|each month)\b", normalized):
        return "monthly"
    if re.search(r"\b(every year|yearly|annually|each year)\b", normalized):
        return "yearly"
    return None


def _interval_due_time(rule: str | None, now: datetime) -> str | None:
    match = re.fullmatch(r"interval:(\d+):(seconds|minutes|hours|days)", rule or "")
    if not match:
        return None
    amount = int(match.group(1))
    unit = match.group(2)
    delta = {
        "seconds": timedelta(seconds=amount),
        "minutes": timedelta(minutes=amount),
        "hours": timedelta(hours=amount),
        "days": timedelta(days=amount),
    }[unit]
    return (now + delta).isoformat(timespec="seconds")


def _clock_due_time(message: str, now: datetime, recurrence_rule: str | None) -> str | None:
    match = re.search(r"\bat\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b", message.lower())
    if not match:
        return None
    hour = int(match.group(1))
    minute = int(match.group(2) or 0)
    if not 1 <= hour <= 12 or minute > 59:
        return None
    if match.group(3) == "pm" and hour != 12:
        hour += 12
    if match.group(3) == "am" and hour == 12:
        hour = 0
    due = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if recurrence_rule and due <= now:
        due = next_occurrence(due.isoformat(), recurrence_rule)
        return due
    return due.isoformat(timespec="seconds")


def next_occurrence(due_at: str, rule: str | None) -> str:
    due = datetime.fromisoformat(due_at)
    interval_match = re.fullmatch(r"interval:(\d+):(seconds?|minutes?|hours?|days?)", rule or "")
    if interval_match:
        amount = int(interval_match.group(1))
        unit = interval_match.group(2)
        if unit.startswith("second"):
            next_due = due + timedelta(seconds=amount)
        elif unit.startswith("minute"):
            next_due = due + timedelta(minutes=amount)
        elif unit.startswith("hour"):
            next_due = due + timedelta(hours=amount)
        else:
            next_due = due + timedelta(days=amount)
    elif rule == "daily":
        next_due = due + timedelta(days=1)
    elif rule == "weekly":
        next_due = due + timedelta(weeks=1)
    elif rule == "monthly":
        next_due = due + relativedelta(months=1)
    elif rule == "yearly":
        next_due = due + relativedelta(years=1)
    else:
        raise ValueError("A recurrence rule is required for recurring reminders.")
    return next_due.isoformat(timespec="seconds")


def format_reminder_confirmation(intent: ReminderIntent) -> str:
    if intent.operation != "add" or not intent.text or not intent.due_at:
        return intent.response
    recurrence = f" ({intent.recurrence_rule})" if intent.recurrence_rule else ""
    return f"Reminder: {intent.text}. Due: {intent.due_at}{recurrence}. Should I save it? Reply yes or no."


class ReminderScheduler:
    def __init__(self, database: Database, on_due: Callable[[dict], None]) -> None:
        self.database = database
        self.on_due = on_due
        self.scheduler = BackgroundScheduler()
        self.scheduler.add_job(self.check_due, "interval", seconds=15, id="reminder-check", replace_existing=True)

    def start(self) -> None:
        self.surface_missed()
        self.scheduler.start()

    def stop(self) -> None:
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)

    def surface_missed(self) -> None:
        for reminder in self.database.list_reminders(status="pending"):
            if datetime.fromisoformat(reminder["due_at"]) <= datetime.now().astimezone():
                self._notify(reminder, missed=True)

    def check_due(self) -> None:
        for reminder in self.database.list_reminders(status="pending"):
            if datetime.fromisoformat(reminder["due_at"]) <= datetime.now().astimezone():
                self._notify(reminder, missed=False)

    def _notify(self, reminder: dict, missed: bool) -> None:
        if reminder["recurrence_rule"]:
            next_due = next_occurrence(reminder["due_at"], reminder["recurrence_rule"])
            self.database.update_reminder(reminder["id"], next_due, "pending")
        else:
            self.database.update_reminder_status(reminder["id"], "overdue")
        self.on_due({**reminder, "missed": missed})

def save_reminder(database: Database, intent: ReminderIntent) -> int:
    if intent.operation != "add" or not intent.text or not intent.due_at:
        raise ValueError("Reminder task and due time are required.")
    return database.add_reminder(Reminder(intent.text, intent.due_at, intent.recurrence_rule))
