"""Deterministic, labelled context assembly for every assistant call."""

from __future__ import annotations

from datetime import datetime

from jinja2 import Template

from db.database import Database


SYSTEM_PROMPT = """You are a careful personal desktop assistant.

Use the context block supplied with every request.
Information under VERIFIED FACTS comes from the user's profile, SQLite memories,
reminders, or conversation log and may be treated as fact.
Information under AI SUGGESTIONS is only a suggestion and must never be presented
as a verified fact.
If the requested information is not present in the context block, say exactly that
you do not know. Never guess or invent names, dates, numbers, reminders, or other
personal details. Ask the user for the missing information when useful.
"""

CONTEXT_TEMPLATE = """CURRENT DATE/TIME: {{ current_time }}
VERIFIED FACTS:
USER PROFILE:
{{ profile_text }}
VERIFIED MEMORIES:
{{ memories_text }}
ACTIVE REMINDERS:
{{ reminders_text }}
CALENDAR:
(not connected — M7)
RECENT CONVERSATION: last 6 turns
{{ conversation_text }}
AI SUGGESTIONS:
(empty — suggestions are not verified facts)
"""


def build_context(database: Database, now: datetime | None = None) -> str:
	"""Build the complete labelled context block from SQLite and empty feature slots."""
	current_time = (now or datetime.now().astimezone()).isoformat(timespec="minutes")
	profile = database.get_profile()
	profile_text = "(empty)"
	if profile is not None:
		profile_text = (
			f"name: {profile.name}\n"
			f"language preference: {profile.language_pref}\n"
			f"personality: {profile.personality or '(empty)'}\n"
			f"city: {profile.city or '(empty)'}\n"
			f"zodiac sign: {profile.zodiac_sign or '(empty)'}"
		)

	memory_rows = database.list_memories()
	memories_text = "\n".join(
		f"- [{memory.category}] {memory.title}; details: {memory.details}; notes: {memory.notes or '(empty)'}"
		for memory in memory_rows
	) or "(empty)"

	reminder_rows = database.list_reminders(status="pending")
	reminders_text = "\n".join(
		f"- {reminder['text']} | due_at: {reminder['due_at']}"
		for reminder in reminder_rows
	) or "(empty — M5)"

	conversation_rows = database.get_conversation(limit=6)
	conversation_text = "\n".join(
		f"- {message['role']}: {message['content']}"
		for message in conversation_rows
	) or "(empty)"

	return Template(CONTEXT_TEMPLATE).render(
		current_time=current_time,
		profile_text=profile_text,
		memories_text=memories_text,
		reminders_text=reminders_text,
		conversation_text=conversation_text,
	).strip()
