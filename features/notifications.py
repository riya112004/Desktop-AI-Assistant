"""Best-effort native desktop notifications for local reminders."""

from __future__ import annotations

from plyer import notification


def show_reminder_notification(text: str, due_at: str, missed: bool = False) -> None:
    prefix = "Missed reminder" if missed else "Reminder"
    notification.notify(
        title=prefix,
        message=f"{text}\nDue: {due_at}",
        app_name="Assistant",
        timeout=10,
    )
