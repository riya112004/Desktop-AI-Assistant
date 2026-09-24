"""SQLite access layer for the assistant's durable data."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

from core.config import load_config


SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def _now() -> str:
	return datetime.now().astimezone().isoformat(timespec="seconds")


def _local_timestamp(value: str) -> str:
	timestamp = datetime.fromisoformat(value)
	if timestamp.tzinfo is None:
		timestamp = timestamp.astimezone()
	else:
		timestamp = timestamp.astimezone()
	return timestamp.isoformat(timespec="seconds")


@dataclass(frozen=True)
class UserProfile:
	name: str
	language_pref: str = "en"
	personality: str = ""
	city: str = ""
	zodiac_sign: str = ""


@dataclass(frozen=True)
class Memory:
	category: str
	title: str
	details: dict[str, Any]
	notes: str = ""
	id: int | None = None


@dataclass(frozen=True)
class ImportantDate:
	memory_id: int
	date: str
	type: str
	recurring: bool = False
	id: int | None = None


@dataclass(frozen=True)
class Reminder:
	text: str
	due_at: str
	recurrence_rule: str | None = None
	status: str = "pending"
	id: int | None = None


class Database:
	"""Small, parameterized CRUD facade over the SQLite database."""

	def __init__(self, path: Path | None = None) -> None:
		self.path = path or load_config().paths.database
		self.path.parent.mkdir(parents=True, exist_ok=True)
		self.initialize()

	def connect(self) -> sqlite3.Connection:
		connection = sqlite3.connect(self.path)
		connection.row_factory = sqlite3.Row
		connection.execute("PRAGMA foreign_keys = ON")
		return connection

	@contextmanager
	def connection(self) -> Any:
		connection = self.connect()
		try:
			yield connection
			connection.commit()
		finally:
			connection.close()

	def initialize(self) -> None:
		with self.connection() as connection:
			connection.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))

	def upsert_profile(self, profile: UserProfile) -> None:
		timestamp = _now()
		with self.connection() as connection:
			connection.execute(
				"""INSERT INTO user_profile
				   (id, name, language_pref, personality, city, zodiac_sign, created_at, updated_at)
				   VALUES (1, ?, ?, ?, ?, ?, ?, ?)
				   ON CONFLICT(id) DO UPDATE SET name=excluded.name,
				   language_pref=excluded.language_pref, personality=excluded.personality,
				   city=excluded.city, zodiac_sign=excluded.zodiac_sign, updated_at=excluded.updated_at""",
				(profile.name, profile.language_pref, profile.personality, profile.city,
				 profile.zodiac_sign, timestamp, timestamp),
			)

	def get_profile(self) -> UserProfile | None:
		with self.connection() as connection:
			row = connection.execute("SELECT name, language_pref, personality, city, zodiac_sign FROM user_profile WHERE id = 1").fetchone()
		return UserProfile(**dict(row)) if row else None

	def add_memory(self, memory: Memory) -> int:
		timestamp = _now()
		with self.connection() as connection:
			cursor = connection.execute(
				"INSERT INTO memories (category, title, details, notes, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
				(memory.category, memory.title, json.dumps(memory.details), memory.notes, timestamp, timestamp),
			)
			return int(cursor.lastrowid)

	def get_memory(self, memory_id: int) -> Memory | None:
		with self.connection() as connection:
			row = connection.execute("SELECT id, category, title, details, notes FROM memories WHERE id = ?", (memory_id,)).fetchone()
		return Memory(row["category"], row["title"], json.loads(row["details"]), row["notes"], row["id"]) if row else None

	def list_memories(self, category: str | None = None) -> list[Memory]:
		query = "SELECT id, category, title, details, notes FROM memories"
		parameters: tuple[str, ...] = ()
		if category is not None:
			query += " WHERE category = ?"
			parameters = (category,)
		query += " ORDER BY id"
		with self.connection() as connection:
			rows = connection.execute(query, parameters).fetchall()
		return [Memory(row["category"], row["title"], json.loads(row["details"]), row["notes"], row["id"]) for row in rows]

	def update_memory(self, memory: Memory) -> None:
		if memory.id is None:
			raise ValueError("memory.id is required for an update")
		with self.connection() as connection:
			connection.execute(
				"UPDATE memories SET category = ?, title = ?, details = ?, notes = ?, updated_at = ? WHERE id = ?",
				(memory.category, memory.title, json.dumps(memory.details), memory.notes, _now(), memory.id),
			)

	def delete_memory(self, memory_id: int) -> None:
		with self.connection() as connection:
			connection.execute("DELETE FROM memories WHERE id = ?", (memory_id,))

	def add_important_date(self, important_date: ImportantDate) -> int:
		with self.connection() as connection:
			cursor = connection.execute(
				"INSERT INTO important_dates (memory_id, date, type, recurring) VALUES (?, ?, ?, ?)",
				(important_date.memory_id, important_date.date, important_date.type, int(important_date.recurring)),
			)
			return int(cursor.lastrowid)

	def get_important_date(self, date_id: int) -> ImportantDate | None:
		with self.connection() as connection:
			row = connection.execute(
				"SELECT id, memory_id, date, type, recurring FROM important_dates WHERE id = ?",
				(date_id,),
			).fetchone()
		return ImportantDate(row["memory_id"], row["date"], row["type"], bool(row["recurring"]), row["id"]) if row else None

	def update_important_date(self, important_date: ImportantDate) -> None:
		if important_date.id is None:
			raise ValueError("important_date.id is required for an update")
		with self.connection() as connection:
			connection.execute(
				"UPDATE important_dates SET memory_id = ?, date = ?, type = ?, recurring = ? WHERE id = ?",
				(important_date.memory_id, important_date.date, important_date.type,
				 int(important_date.recurring), important_date.id),
			)

	def delete_important_date(self, date_id: int) -> None:
		with self.connection() as connection:
			connection.execute("DELETE FROM important_dates WHERE id = ?", (date_id,))

	def list_important_dates(self, memory_id: int) -> list[ImportantDate]:
		with self.connection() as connection:
			rows = connection.execute(
				"SELECT id, memory_id, date, type, recurring FROM important_dates WHERE memory_id = ? ORDER BY id",
				(memory_id,),
			).fetchall()
		return [ImportantDate(row["memory_id"], row["date"], row["type"], bool(row["recurring"]), row["id"]) for row in rows]

	def dates_due_between(self, start_date: str, end_date: str) -> list[dict[str, Any]]:
		start = date.fromisoformat(start_date)
		end = date.fromisoformat(end_date)
		if end < start:
			raise ValueError("end_date must not be before start_date")
		with self.connection() as connection:
			rows = connection.execute(
				"""SELECT important_dates.id, important_dates.memory_id, important_dates.date,
						  important_dates.type, important_dates.recurring, memories.title
				   FROM important_dates JOIN memories ON memories.id = important_dates.memory_id""",
			).fetchall()

		upcoming: list[dict[str, Any]] = []
		for row in rows:
			stored_date = date.fromisoformat(row["date"])
			occurrences = range(start.year - 1, end.year + 2) if row["recurring"] else (stored_date.year,)
			for year in occurrences:
				try:
					occurrence = stored_date.replace(year=year) if row["recurring"] else stored_date
				except ValueError:
					continue
				if start <= occurrence <= end:
					item = dict(row)
					item["date"] = occurrence.isoformat()
					upcoming.append(item)
		return sorted(upcoming, key=lambda item: item["date"])

	def add_reminder(self, reminder: Reminder) -> int:
		with self.connection() as connection:
			cursor = connection.execute(
				"INSERT INTO reminders (text, due_at, recurrence_rule, status, created_at) VALUES (?, ?, ?, ?, ?)",
				(reminder.text, _local_timestamp(reminder.due_at), reminder.recurrence_rule, reminder.status, _now()),
			)
			return int(cursor.lastrowid)

	def list_reminders(self, status: str | None = None) -> list[dict[str, Any]]:
		query = "SELECT * FROM reminders"
		parameters: tuple[str, ...] = ()
		if status is not None:
			query += " WHERE status = ?"
			parameters = (status,)
		query += " ORDER BY due_at"
		with self.connection() as connection:
			return [dict(row) for row in connection.execute(query, parameters).fetchall()]

	def update_reminder_status(self, reminder_id: int, status: str) -> None:
		with self.connection() as connection:
			connection.execute("UPDATE reminders SET status = ? WHERE id = ?", (status, reminder_id))

	def update_reminder(self, reminder_id: int, due_at: str, status: str = "pending") -> None:
		with self.connection() as connection:
			connection.execute(
				"UPDATE reminders SET due_at = ?, status = ? WHERE id = ?",
				(_local_timestamp(due_at), status, reminder_id),
			)

	def get_reminder(self, reminder_id: int) -> dict[str, Any] | None:
		with self.connection() as connection:
			row = connection.execute("SELECT * FROM reminders WHERE id = ?", (reminder_id,)).fetchone()
		return dict(row) if row else None

	def delete_reminder(self, reminder_id: int) -> None:
		with self.connection() as connection:
			connection.execute("DELETE FROM reminders WHERE id = ?", (reminder_id,))

	def log_message(self, role: str, content: str) -> int:
		with self.connection() as connection:
			cursor = connection.execute(
				"INSERT INTO conversation_log (role, content, timestamp) VALUES (?, ?, ?)",
				(role, content, _now()),
			)
			return int(cursor.lastrowid)

	def get_conversation(self, limit: int = 50) -> list[dict[str, Any]]:
		with self.connection() as connection:
			rows = connection.execute("SELECT * FROM conversation_log ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
		return [dict(row) for row in reversed(rows)]

	def get_state(self, key: str, default: str | None = None) -> str | None:
		with self.connection() as connection:
			row = connection.execute("SELECT value FROM app_state WHERE key = ?", (key,)).fetchone()
		return row["value"] if row else default

	def set_state(self, key: str, value: str) -> None:
		with self.connection() as connection:
			connection.execute(
				"INSERT INTO app_state (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
				(key, value),
			)

	def delete_state(self, key: str) -> None:
		with self.connection() as connection:
			connection.execute("DELETE FROM app_state WHERE key = ?", (key,))
