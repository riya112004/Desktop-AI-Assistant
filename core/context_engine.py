"""Deterministic, labelled context assembly for every assistant call."""

from __future__ import annotations

from datetime import datetime

from jinja2 import Template

from db.database import Database


SYSTEM_PROMPT = """You are a careful personal desktop assistant.

Use the context block supplied with every request.
Information under VERIFIED FACTS comes only from the current user's profile,
SQLite memories, and active reminders and may be treated as fact.
Information under AI SUGGESTIONS is only a suggestion and must never be presented
as a verified fact.
RECENT CONVERSATION is provided only for continuity. Previous assistant messages
are not verified facts and must never override current SQLite data.
If the requested information is not present in the context block, say exactly that
you do not know. Never guess or invent names, dates, numbers, reminders, or other
personal details. Ask the user for the missing information when useful.
When the user asks about a person, match the person's name against VERIFIED
MEMORIES and answer from that matching memory. Do not use the USER PROFILE to
describe another person.
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
Treat this conversation only as continuity. Any PREVIOUS ASSISTANT RESPONSE is
UNVERIFIED and may be wrong. If it conflicts with VERIFIED FACTS, ignore it.
AUTHORITATIVE MEMORY LOOKUP:
{{ memory_lookup }}
Use this lookup for person questions before using conversation history.
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
	memory_blocks: list[str] = []
	for memory in memory_rows:
		details = "\n".join(
			f"  {key.upper()}: {value}"
			for key, value in memory.details.items()
		) or "  DETAILS: (empty)"
		memory_blocks.append(
			f"- MEMORY NAME: {memory.title}\n"
			f"  CATEGORY: {memory.category}\n"
			f"{details}\n"
			f"  NOTES: {memory.notes or '(empty)'}"
		)
	memories_text = "\n".join(memory_blocks) or "(empty)"

	reminder_rows = database.list_reminders(status="pending")
	reminders_text = "\n".join(
		f"- {reminder['text']} | due_at: {reminder['due_at']}"
		for reminder in reminder_rows
	) or "(empty — M5)"

	conversation_rows = database.get_conversation(limit=6)
	conversation_text = "\n".join(
		f"- USER: {message['content']}" if message["role"] == "user"
		else f"- PREVIOUS ASSISTANT RESPONSE (UNVERIFIED): {message['content']}"
		for message in conversation_rows
	) or "(empty)"
	memory_lookup = "\n".join(
		f"- {memory.title} = {memory.details.get('relationship', memory.category)}"
		for memory in memory_rows
	) or "(empty)"

	return Template(CONTEXT_TEMPLATE).render(
		current_time=current_time,
		profile_text=profile_text,
		memories_text=memories_text,
		reminders_text=reminders_text,
		conversation_text=conversation_text,
		memory_lookup=memory_lookup,
	).strip()
