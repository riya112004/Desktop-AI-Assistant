# Database schema design

The database stores the user's profile, durable memories, dates attached to those memories, reminders, conversation history, and small application settings.

## Tables

- `user_profile`: one profile row with name, language, personality, city, and zodiac sign.
- `memories`: durable items such as family members, vehicles, policies, or general notes. `details` is JSON text so each category can keep its own fields.
- `important_dates`: one shared date model for birthdays, policy renewals, and vehicle service dates. Each row belongs to a memory through `memory_id`.
- `reminders`: actionable reminders with an optional recurrence rule and lifecycle status.
- `conversation_log`: timestamped user and assistant messages.
- `app_state`: string key/value settings such as `last_briefing_date` and `onboarding_complete`.

Dates use ISO-8601 text (`YYYY-MM-DD` for calendar dates). Timestamps use ISO-8601 local time with an explicit UTC offset and seconds precision, for example `2026-09-18T09:00:00-07:00`. Foreign keys are enabled by the access layer, and deleting a memory also deletes its important dates.

## Shared due-date query

All birthdays, renewals, and service dates can use the same query:

```sql
SELECT important_dates.*, memories.title
FROM important_dates
JOIN memories ON memories.id = important_dates.memory_id;
```

The access layer applies the requested window to each stored date and projects recurring dates into the requested year, so a birthday is not trapped in its original birth year.
