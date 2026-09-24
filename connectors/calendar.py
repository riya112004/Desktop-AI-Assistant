"""Google Calendar connector with safe optional fallback behavior."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

try:
	import winreg
except ImportError:  # pragma: no cover - Windows-only fallback
	winreg = None  # type: ignore[assignment]

try:
	import keyring
except ImportError:  # pragma: no cover - graceful degradation when not installed
	keyring = None  # type: ignore[assignment]

try:
	from google.auth.transport.requests import Request
	from google.oauth2.credentials import Credentials
	from google_auth_oauthlib.flow import InstalledAppFlow
	from googleapiclient.discovery import build
except ImportError:  # pragma: no cover - exercised when optional dependency is absent
	Request = None  # type: ignore[assignment]
	Credentials = None  # type: ignore[assignment]
	InstalledAppFlow = None  # type: ignore[assignment]
	build = None  # type: ignore[assignment]


SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]


@dataclass(frozen=True)
class CalendarEvent:
	"""Simple event representation that keeps the connector dependency-light."""

	id: str
	summary: str
	start: str
	end: str
	all_day: bool = False
	location: str = ""

	def to_dict(self) -> dict[str, object]:
		return {
			"id": self.id,
			"summary": self.summary,
			"start": self.start,
			"end": self.end,
			"all_day": self.all_day,
			"location": self.location,
		}

	@classmethod
	def from_dict(cls, payload: dict[str, object]) -> "CalendarEvent":
		return cls(
			id=str(payload.get("id", "")),
			summary=str(payload.get("summary", "(no title)")),
			start=str(payload.get("start", "")),
			end=str(payload.get("end", "")),
			all_day=bool(payload.get("all_day", False)),
			location=str(payload.get("location", "")),
		)


def _parse_dt(value: str | datetime) -> datetime:
	if isinstance(value, datetime):
		return value.astimezone(timezone.utc) if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
	return datetime.fromisoformat(value).astimezone(timezone.utc) if datetime.fromisoformat(value).tzinfo is not None else datetime.fromisoformat(value).replace(tzinfo=timezone.utc)


def _coerce_time(value: str | datetime | None) -> datetime | None:
	if value is None:
		return None
	dt = _parse_dt(value)
	return dt.astimezone(timezone.utc)


def _normalize_datetime(value: datetime) -> datetime:
	if value.tzinfo is None:
		return value.replace(tzinfo=timezone.utc)
	return value.astimezone(timezone.utc)


def _iter_events(events: Iterable[CalendarEvent | dict[str, object]]) -> list[CalendarEvent]:
	normalized: list[CalendarEvent] = []
	for event in events:
		if isinstance(event, CalendarEvent):
			normalized.append(event)
		else:
			normalized.append(CalendarEvent.from_dict(event))
	return sorted(normalized, key=lambda item: _coerce_time(item.start) or datetime.min.replace(tzinfo=timezone.utc))


def _event_overlaps_date(event: CalendarEvent, value: date) -> bool:
	if event.all_day:
		start_date = date.fromisoformat(event.start[:10])
		end_date = date.fromisoformat(event.end[:10])
		return start_date <= value < end_date
	start = _coerce_time(event.start)
	end = _coerce_time(event.end)
	if start is None or end is None:
		return False
	day_start = datetime.combine(value, datetime.min.time(), tzinfo=timezone.utc)
	day_end = day_start + timedelta(days=1)
	return start < day_end and end > day_start


def _event_label(event: CalendarEvent) -> str:
	if not event.all_day:
		start = _coerce_time(event.start)
		end = _coerce_time(event.end)
		if start is None or end is None:
			return event.summary
		return f"{event.summary} ({start.astimezone().strftime('%H:%M')}-{end.astimezone().strftime('%H:%M')})"

	try:
		start_date = date.fromisoformat(event.start[:10])
		end_date = date.fromisoformat(event.end[:10])
	except ValueError:
		return f"{event.summary} (all day)"
	last_day = end_date - timedelta(days=1)
	if start_date == last_day:
		return f"{event.summary} (all day)"
	return f"{event.summary} (all day, {start_date.strftime('%d %b')}-{last_day.strftime('%d %b')})"


def _event_intersects_range(event: CalendarEvent, start: datetime, end: datetime) -> bool:
	if event.all_day:
		start_date = date.fromisoformat(event.start[:10])
		end_date = date.fromisoformat(event.end[:10])
		return start_date < end.date() and end_date > start.date()
	event_start = _coerce_time(event.start)
	event_end = _coerce_time(event.end)
	return event_start is not None and event_end is not None and event_start < end and event_end > start


def find_free_busy_gaps(
	start: datetime,
	end: datetime,
	events: Iterable[CalendarEvent | dict[str, object]],
) -> list[tuple[datetime, datetime]]:
	"""Return free windows between calendar events inside a timeframe."""

	start_aware = start if start.tzinfo is not None else start.replace(tzinfo=timezone.utc)
	end_aware = end if end.tzinfo is not None else end.replace(tzinfo=timezone.utc)
	if end_aware <= start_aware:
		return []

	busy_intervals: list[tuple[datetime, datetime]] = []
	for event in _iter_events(events):
		event_start = _coerce_time(event.start)
		event_end = _coerce_time(event.end)
		if event_start is None or event_end is None:
			continue
		start_clamped = max(start_aware, event_start)
		end_clamped = min(end_aware, event_end)
		if start_clamped < end_clamped:
			busy_intervals.append((start_clamped, end_clamped))

	if not busy_intervals:
		return [(start_aware, end_aware)]

	busy_intervals.sort(key=lambda pair: pair[0])
	gaps: list[tuple[datetime, datetime]] = []
	cursor = start_aware
	for busy_start, busy_end in busy_intervals:
		if busy_start > cursor:
			gaps.append((cursor, busy_start))
		cursor = max(cursor, busy_end)
		if cursor >= end_aware:
			break
	if cursor < end_aware:
		gaps.append((cursor, end_aware))
	return gaps


class GoogleCalendarConnector:
	"""Google Calendar adapter that fails closed and stays optional."""

	def __init__(
		self,
		enabled: bool | None = None,
		client_id: str | None = None,
		client_secret: str | None = None,
		token_path: str | Path | None = None,
		cache_path: str | Path | None = None,
		cache_ttl_seconds: int = 300,
	) -> None:
		self.enabled = self._resolve_enabled(enabled)
		self.client_id = client_id or self._environment_value("GOOGLE_CALENDAR_CLIENT_ID")
		self.client_secret = client_secret or self._environment_value("GOOGLE_CALENDAR_CLIENT_SECRET")
		project_root = Path(__file__).resolve().parents[1]
		local_app_data = Path(os.getenv("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
		secure_data_dir = local_app_data / "DesktopAiAssistant"
		self.token_path = Path(token_path) if token_path is not None else secure_data_dir / "google_calendar_token.json"
		self.cache_path = Path(cache_path) if cache_path is not None else project_root / "data" / "google_calendar_cache.json"
		self.cache_ttl_seconds = cache_ttl_seconds
		self._cache: dict[str, object] | None = None

	@property
	def authorization_configured(self) -> bool:
		return bool(self.client_id and self.client_secret)

	@staticmethod
	def _resolve_enabled(explicit_enabled: bool | None) -> bool:
		if explicit_enabled is not None:
			return explicit_enabled
		raw = GoogleCalendarConnector._environment_value("GOOGLE_CALENDAR_ENABLED", "false").strip().lower()
		return raw in {"1", "true", "yes", "on"}

	@staticmethod
	def _environment_value(name: str, default: str = "") -> str:
		value = os.getenv(name)
		if value:
			return value
		if winreg is None:
			return default
		try:
			with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Environment") as key:
				value, _ = winreg.QueryValueEx(key, name)
				return str(value)
		except (FileNotFoundError, OSError):
			return default

	def _token_key(self) -> str:
		return "desktop-ai-assistant.calendar.google-token"

	def _write_token_file(self, credentials: Credentials) -> None:
		self.token_path.parent.mkdir(parents=True, exist_ok=True)
		self.token_path.write_text(json.dumps({
			"token": credentials.token,
			"refresh_token": credentials.refresh_token,
			"token_uri": credentials.token_uri,
			"client_id": credentials.client_id,
			"client_secret": credentials.client_secret,
			"scopes": credentials.scopes,
			"expiry": credentials.expiry.isoformat() if credentials.expiry else None,
		}), encoding="utf-8")

	def _read_token_file(self) -> dict[str, object] | None:
		if not self.token_path.exists():
			return None
		try:
			return json.loads(self.token_path.read_text(encoding="utf-8"))
		except (json.JSONDecodeError, OSError):
			return None

	def _save_secure_token(self, payload: dict[str, object]) -> None:
		if keyring is None:
			self._write_token_file(Credentials.from_authorized_user_info(info=payload, scopes=SCOPES))
			return
		try:
			keyring.set_password(self._token_key(), "google_calendar", json.dumps(payload))
		except Exception:
			self._write_token_file(Credentials.from_authorized_user_info(info=payload, scopes=SCOPES))

	def _read_secure_token(self) -> dict[str, object] | None:
		if keyring is None:
			return self._read_token_file()
		try:
			token = keyring.get_password(self._token_key(), "google_calendar")
			if token:
				return json.loads(token)
		except Exception:
			pass
		return self._read_token_file()

	def _credentials_from_token(self) -> Credentials | None:
		if Request is None or Credentials is None:
			return None
		token_json = self._read_secure_token()
		if not token_json:
			return None
		credentials = Credentials.from_authorized_user_info(info=token_json, scopes=SCOPES)
		if credentials and credentials.expired and credentials.refresh_token:
			try:
				credentials.refresh(Request())
				self._save_secure_token({
					"token": credentials.token,
					"refresh_token": credentials.refresh_token,
					"token_uri": credentials.token_uri,
					"client_id": credentials.client_id,
					"client_secret": credentials.client_secret,
					"scopes": credentials.scopes,
					"expiry": credentials.expiry.isoformat() if credentials.expiry else None,
				})
			except Exception:
				return None
		return credentials

	def _credentials_for_flow(self) -> Credentials | None:
		if not self.enabled or not self.client_id or not self.client_secret:
			return None
		if InstalledAppFlow is None:
			return None
		flow = InstalledAppFlow.from_client_config(
			{
				"installed": {
					"client_id": self.client_id,
					"client_secret": self.client_secret,
					"auth_uri": "https://accounts.google.com/o/oauth2/auth",
					"token_uri": "https://oauth2.googleapis.com/token",
					"auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
					"redirect_uris": ["http://localhost"],
				}
			},
			scopes=SCOPES,
		)
		credentials = flow.run_local_server(
			host="127.0.0.1",
			bind_addr="127.0.0.1",
			port=0,
			open_browser=True,
		)
		self._save_secure_token({
			"token": credentials.token,
			"refresh_token": credentials.refresh_token,
			"token_uri": credentials.token_uri,
			"client_id": credentials.client_id,
			"client_secret": credentials.client_secret,
			"scopes": credentials.scopes,
			"expiry": credentials.expiry.isoformat() if credentials.expiry else None,
		})
		return credentials

	def _calendar_service(self):
		if not self.enabled or build is None:
			raise RuntimeError("Calendar connector is disabled or dependency missing")
		credentials = self._credentials_from_token()
		if credentials is None:
			credentials = self._credentials_for_flow()
		if credentials is None:
			raise RuntimeError("Calendar token unavailable")
		return build("calendar", "v3", credentials=credentials)

	def load_events_from_cache(self) -> list[CalendarEvent]:
		if self._cache is not None:
			events = self._cache.get("events", [])
			timestamp = self._cache.get("timestamp")
			if timestamp is not None:
				try:
					last_ts = datetime.fromisoformat(str(timestamp))
					now = datetime.now().astimezone()
					if (now - last_ts).total_seconds() <= self.cache_ttl_seconds:
						return [CalendarEvent.from_dict(event) for event in events]
				except ValueError:
					pass
		if not self.cache_path.exists():
			return []
		try:
			payload = json.loads(self.cache_path.read_text(encoding="utf-8"))
		except (json.JSONDecodeError, OSError):
			return []
		timestamp = payload.get("timestamp")
		if not timestamp:
			return []
		last_ts = datetime.fromisoformat(timestamp)
		now = datetime.now().astimezone()
		if (now - last_ts).total_seconds() > self.cache_ttl_seconds:
			return []
		events = payload.get("events", [])
		return [_iter_events([event])[0] if False else CalendarEvent.from_dict(event) for event in events]

	def save_events_to_cache(self, events: list[CalendarEvent]) -> None:
		self._cache = {
			"timestamp": datetime.now().astimezone().isoformat(),
			"events": [event.to_dict() for event in events],
		}
		self.cache_path.parent.mkdir(parents=True, exist_ok=True)
		self.cache_path.write_text(
			json.dumps({
				"timestamp": datetime.now().astimezone().isoformat(),
				"events": [event.to_dict() for event in events],
			}),
			encoding="utf-8",
		)

	def list_events(self, start: datetime | None = None, end: datetime | None = None) -> list[CalendarEvent]:
		if not self.enabled:
			return []
		now = datetime.now().astimezone()
		start_dt = _normalize_datetime(start) if start is not None else (now - timedelta(hours=1))
		end_dt = _normalize_datetime(end) if end is not None else (now + timedelta(days=7))
		cached_events = self.load_events_from_cache()
		if cached_events:
			return cached_events
		try:
			service = self._calendar_service()
			response = service.events().list(
				calendarId="primary",
				timeMin=start_dt.isoformat(),
				timeMax=end_dt.isoformat(),
				singleEvents=True,
				orderBy="startTime",
			).execute()
		except Exception:
			return cached_events

		events: list[CalendarEvent] = []
		for item in response.get("items", []):
			start_value = item.get("start", {}).get("dateTime") or item.get("start", {}).get("date")
			end_value = item.get("end", {}).get("dateTime") or item.get("end", {}).get("date")
			if not start_value or not end_value:
				continue
			events.append(
				CalendarEvent(
					id=str(item.get("id", "")),
					summary=str(item.get("summary") or "(no title)"),
					start=str(start_value),
					end=str(end_value),
					all_day=bool(item.get("start", {}).get("date") is not None),
					location=str(item.get("location") or ""),
				)
			)
		self.save_events_to_cache(events)
		return events

	def summary_for_context(self, now: datetime | None = None) -> str:
		if not self.enabled:
			return "CALENDAR: unavailable"
		try:
			current = _normalize_datetime(now) if now is not None else datetime.now().astimezone()
			today_start = current.replace(hour=0, minute=0, second=0, microsecond=0)
			week_end = today_start + timedelta(days=7)

			events = self.list_events(today_start, week_end)
			if not events:
				return "CALENDAR: no events found for today or the next 7 days."

			today_items = [event for event in events if _event_overlaps_date(event, current.date())]
			tomorrow = current.date() + timedelta(days=1)
			tomorrow_items = [event for event in events if _event_overlaps_date(event, tomorrow)]

			lines = ["CALENDAR: available"]
			if today_items:
				lines.append("Today:")
				for event in today_items:
					lines.append(f"- {_event_label(event)}")
			else:
				lines.append("Today: no calendar events.")
			if tomorrow_items:
				lines.append("Tomorrow:")
				for event in tomorrow_items:
					lines.append(f"- {_event_label(event)}")
			week_events = [event for event in events if _event_intersects_range(event, today_start, week_end)]
			if week_events:
				lines.append("This week:")
				for event in week_events[:3]:
					start = _coerce_time(event.start)
					if start is None:
						continue
					lines.append(f"- {start.astimezone().strftime('%a %d %b')} {_event_label(event)}")
			return "\n".join(lines)
		except Exception:
			return "CALENDAR: unavailable"

	def availability_at(self, message: str, now: datetime | None = None) -> str | None:
		"""Answer a simple same-day availability question from verified events."""
		match = re.search(r"\b(?:at|around)\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b", message.lower())
		if match is None:
			return None
		hour = int(match.group(1))
		minute = int(match.group(2) or 0)
		meridiem = match.group(3)
		if meridiem == "am" and hour == 12:
			hour = 0
		elif meridiem == "pm" and hour < 12:
			hour += 12
		if hour > 23 or minute > 59:
			return "I could not understand that time."

		current = _normalize_datetime(now) if now is not None else datetime.now().astimezone()
		target = current.replace(hour=hour, minute=minute, second=0, microsecond=0)
		day_start = target.replace(hour=0, minute=0)
		day_end = day_start + timedelta(days=1)
		events = self.list_events(day_start, day_end)
		for event in events:
			event_start = _coerce_time(event.start)
			event_end = _coerce_time(event.end)
			if event_start and event_end and event_start <= target < event_end:
				return f"No, you have '{event.summary}' from {event_start.astimezone().strftime('%H:%M')} to {event_end.astimezone().strftime('%H:%M')}."
		return f"Yes, you are free at {target.strftime('%H:%M')} today."
