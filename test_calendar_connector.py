from datetime import datetime, timedelta, timezone
from pathlib import Path

from connectors.calendar import CalendarEvent, GoogleCalendarConnector, find_free_busy_gaps
from core.context_engine import build_context
from db.database import Database


def test_build_context_uses_unavailable_calendar_when_connector_disabled(tmp_path):
    db = Database(tmp_path / "calendar_test.db")
    connector = GoogleCalendarConnector(enabled=False)
    context = build_context(
        db,
        now=datetime(2026, 9, 24, 9, 0),
        calendar_summary=connector.summary_for_context(),
    )
    assert "CALENDAR: unavailable" in context


def test_find_free_busy_gaps_returns_available_windows():
    events = [
        CalendarEvent("1", "Team sync", "2026-09-24T09:00:00+00:00", "2026-09-24T10:00:00+00:00"),
        CalendarEvent("2", "Lunch", "2026-09-24T12:30:00+00:00", "2026-09-24T13:00:00+00:00"),
    ]
    gaps = find_free_busy_gaps(
        start=datetime(2026, 9, 24, 8, 0, tzinfo=None),
        end=datetime(2026, 9, 24, 14, 0, tzinfo=None),
        events=events,
    )
    assert len(gaps) == 3
    assert gaps[0][0].hour == 8
    assert gaps[0][1].hour == 9
    assert gaps[1][0].hour == 10
    assert gaps[1][1].hour == 12
    assert gaps[2][0].hour == 13
    assert gaps[2][1].hour == 14


def test_connector_uses_cache_when_events_are_still_fresh(tmp_path):
    cache_path = tmp_path / "calendar_cache.json"
    connector = GoogleCalendarConnector(enabled=True, cache_path=cache_path)
    connector._cache = {
        "timestamp": datetime.now().astimezone().isoformat(),
        "events": [
            CalendarEvent("1", "Demo", "2026-09-24T15:00:00+00:00", "2026-09-24T16:00:00+00:00").to_dict()
        ],
    }
    summary = connector.summary_for_context(datetime(2026, 9, 24, 9, 0))
    assert "Demo" in summary


def test_availability_at_answers_free_time_from_events(tmp_path):
    connector = GoogleCalendarConnector(enabled=True, cache_path=tmp_path / "calendar_cache.json")
    connector._cache = {
        "timestamp": datetime.now().astimezone().isoformat(),
        "events": [
            CalendarEvent("1", "Demo", "2026-09-24T15:00:00+00:00", "2026-09-24T16:00:00+00:00").to_dict()
        ],
    }
    assert "free at 04:00" in connector.availability_at("Am I free at 4am?", datetime(2026, 9, 24, 9, 0))
    assert "Demo" in connector.availability_at("Am I free at 3pm?", datetime(2026, 9, 24, 9, 0))


def test_all_day_and_multi_day_events_are_displayed_as_date_ranges(tmp_path):
    connector = GoogleCalendarConnector(enabled=True, cache_path=tmp_path / "calendar_cache.json")
    events = [
        CalendarEvent("all", "Holiday", "2026-09-25", "2026-09-26", True),
        CalendarEvent("multi", "Conference", "2026-09-27", "2026-09-30", True),
    ]
    connector._cache = {
        "timestamp": datetime.now().astimezone().isoformat(),
        "events": [event.to_dict() for event in events],
    }
    summary = connector.summary_for_context(datetime(2026, 9, 24, 9, 0))
    assert "Holiday (all day)" in summary
    assert "Conference (all day, 27 Sep-29 Sep)" in summary
    assert "05:30-05:30" not in summary


def test_all_day_dates_are_not_shifted_by_local_timezone(tmp_path):
    connector = GoogleCalendarConnector(enabled=True, cache_path=tmp_path / "calendar_cache.json")
    event = CalendarEvent("all", "Date event", "2026-09-25", "2026-09-26", True)
    connector._cache = {
        "timestamp": datetime.now().astimezone().isoformat(),
        "events": [event.to_dict()],
    }
    summary = connector.summary_for_context(datetime(2026, 9, 25, 1, 0, tzinfo=timezone.utc))
    assert "Date event (all day)" in summary
