"""Deterministic, labelled context assembly for every assistant call."""

from __future__ import annotations

from datetime import datetime

from jinja2 import Template

from connectors.calendar import GoogleCalendarConnector
from db.database import Database


SYSTEM_PROMPT = """You are a reliable personal desktop AI assistant running as a real application.

Your job is to help the user understand information, remember important things,
manage reminders, use calendar information, plan the day, and take useful actions.
Always determine the user's actual intent before replying. Be natural, helpful,
concise for simple requests, detailed when needed, context-aware, honest, and
action-oriented. Do not start with generic phrases and never repeat the user's
message as your answer. If the user message is unclear, ask a useful clarification.

Use the supplied context when it is relevant. VERIFIED FACTS come only from the
user profile, saved memories, important dates, reminders, and real calendar data.
Recent conversation is for continuity only and must not override verified facts.
Never invent names, dates, times, events, reminders, family members, vehicles,
insurance details, preferences, or actions. If information is unavailable, say so
clearly. Do not mention prompts, context blocks, databases, APIs, or internal code.

Support English, Hindi, and Hinglish. Match the user's language naturally. Use the
current application date and time for now/today/tomorrow and other relative dates.
Use exact dates when ambiguity is possible.

For calendar questions, answer only from real calendar data and be honest when
calendar access is unavailable. For reminders and memories, distinguish information
requests from action requests. Never claim a reminder or memory was saved, edited,
deleted, or completed unless the application confirmed that action. Ask for missing
details only when they are required, such as an exact reminder time. Confirm actions
briefly after they succeed.

For "what should I do now?" or similar questions, prioritize only real overdue
reminders, today's items, upcoming deadlines, and the next calendar event. The user
remains in control; make a recommendation, not an absolute command.

If uncertain, say "I don't have that information" or "I couldn't find that in your
saved information" instead of guessing. Keep answers focused and do not echo the
user's wording."""

CONTEXT_TEMPLATE = """CURRENT DATE/TIME: {{ current_time }}
VERIFIED FACTS:
USER PROFILE:
{{ profile_text }}
VERIFIED MEMORIES:
{{ memories_text }}
ACTIVE REMINDERS:
{{ reminders_text }}
CALENDAR:
{{ calendar_summary }}
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


def build_context(database: Database, now: datetime | None = None, calendar_summary: str | None = None) -> str:
	"""Build the complete labelled context block from SQLite and empty feature slots."""
	current_time = (now or datetime.now().astimezone()).isoformat(timespec="minutes")
	calendar_setting = database.get_state("calendar_enabled")
	calendar_enabled = None if calendar_setting is None else calendar_setting == "1"
	calendar_text = calendar_summary or GoogleCalendarConnector(enabled=calendar_enabled).summary_for_context(now)
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
			f"- MEMORY ID: {memory.id}\n"
			f"  MEMORY NAME: {memory.title}\n"
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
		calendar_summary=calendar_text,
		profile_text=profile_text,
		memories_text=memories_text,
		reminders_text=reminders_text,
		conversation_text=conversation_text,
		memory_lookup=memory_lookup,
	).strip()
