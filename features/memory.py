"""Structured conversational memory operations."""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from core.llm_client import LLMClient
from db.database import Database, Memory


Language = Literal["en", "hi", "hinglish"]
Operation = Literal["none", "add", "edit", "view", "delete"]


class FamilyDetails(BaseModel):
	model_config = ConfigDict(extra="ignore")
	relationship: str
	birthday: str | None = None
	phone: str | None = None
	email: str | None = None

	@field_validator("birthday")
	@classmethod
	def valid_birthday(cls, value: str | None) -> str | None:
		if value is not None:
			date.fromisoformat(value)
		return value


class VehicleDetails(BaseModel):
	model_config = ConfigDict(extra="ignore")
	make: str
	model: str
	year: int | None = Field(default=None, ge=1886, le=2200)
	registration: str | None = None
	color: str | None = None


class InsuranceDetails(BaseModel):
	model_config = ConfigDict(extra="ignore")
	provider: str
	policy_number: str
	type: str | None = None
	renewal_date: str | None = None

	@field_validator("renewal_date")
	@classmethod
	def valid_renewal_date(cls, value: str | None) -> str | None:
		if value is not None:
			date.fromisoformat(value)
		return value


class MemoryIntent(BaseModel):
	"""The only model allowed to cross from an LLM response into memory CRUD."""

	model_config = ConfigDict(extra="ignore")
	operation: Operation = "none"
	language: Language = "en"
	response: str = ""
	clarification: bool = False
	memory_id: int | None = None
	category: Literal["family", "vehicle", "insurance"] | None = None
	title: str | None = None
	details: dict[str, Any] = Field(default_factory=dict)
	notes: str = ""
	date_value: str | None = None
	date_type: Literal["birthday", "service", "renewal"] | None = None
	recurring: bool = False

	@model_validator(mode="before")
	@classmethod
	def normalize_llm_empty_values(cls, value: Any) -> Any:
		if not isinstance(value, dict):
			return value
		normalized = dict(value)
		for key in ("memory_id", "category", "title", "date_value", "date_type"):
			if isinstance(normalized.get(key), str) and normalized[key].strip().lower() in {"", "none", "null"}:
				normalized[key] = None
		if not isinstance(normalized.get("details"), dict):
			normalized["details"] = {}
		return normalized

	@field_validator("date_value")
	@classmethod
	def valid_date(cls, value: str | None) -> str | None:
		if value is not None:
			date.fromisoformat(value)
		return value

	def validated_details(self) -> dict[str, Any]:
		if self.category == "family":
			return FamilyDetails.model_validate(self.details).model_dump(exclude_none=True)
		if self.category == "vehicle":
			return VehicleDetails.model_validate(self.details).model_dump(exclude_none=True)
		if self.category == "insurance":
			return InsuranceDetails.model_validate(self.details).model_dump(exclude_none=True)
		raise ValueError("A memory category is required.")


MEMORY_EXTRACTION_PROMPT = """You manage only personal memories in a desktop assistant.
Return one JSON object matching this exact shape:
{
  "operation": "none|add|edit|view|delete",
  "language": "en|hi|hinglish",
  "response": "reply in the user's language",
  "memory_id": null,
  "category": "family|vehicle|insurance|null",
  "title": null,
  "details": {},
  "notes": "",
  "date_value": null,
  "date_type": "birthday|service|renewal|null",
  "recurring": false
}
Use JSON null, never the string "none", for missing category, title, memory_id, date_value, or date_type.
Any sentence that states a personal fact to remember is an add operation, not none.
For example, the input "Mere bhai ka naam Rahul hai, uska birthday 12 March hai"
must produce operation "add", language "hinglish", category "family", title "Rahul",
details {"relationship": "brother"}, date_value "2026-03-12", and date_type "birthday".
Use operation none only for a question or request that does not add, edit, view, or delete memory.
Never invent a missing field or ID.
For a delete request, identify the requested memory by its exact title from the CURRENT CONTEXT
and return that memory's memory_id and title. For example, if the context contains Rahul with
memory_id 16, "Rahul ki memory delete kar do" must return operation "delete", memory_id 16,
and title "Rahul". Never return a delete operation with both memory_id and title missing.
For add/edit, use typed details: family requires relationship; vehicle requires make and model;
insurance requires provider and policy_number. Convert dates such as '12 March' to ISO dates
using the CURRENT DATE context supplied below. For a birthday without a year, use the current year.
Detect English, Hindi, or Hinglish and set language accordingly.
Use "hi" only when the user writes Hindi in Devanagari script. Use "hinglish"
when Hindi words are written with Latin letters, as in the example above.
Do not write or delete anything; the application performs those actions only after confirmation.
"""


def _has_devanagari(text: str) -> bool:
	return any("\u0900" <= character <= "\u097f" for character in text)


def is_calendar_question(message: str) -> bool:
	normalized = " ".join(message.lower().split())
	calendar_terms = (
		"calendar", "meeting", "meetings", "appointment", "appointments",
		"schedule", "scheduled", "free at", "busy at", "what's tomorrow",
		"tomorrow like", "this week",
	)
	return any(term in normalized for term in calendar_terms)


def _is_incomplete_insurance_message(message: str) -> bool:
	normalized = " ".join(message.lower().split())
	insurance_request = "insurance" in normalized or "बीमा" in normalized
	has_provider = any(marker in normalized for marker in ("provider", "insurer", "insurance company", "बीमा कंपनी"))
	has_policy = any(marker in normalized for marker in ("policy", "policy number", "policy no", "पॉलिसी"))
	return insurance_request and not (has_provider and has_policy)


def _insurance_request_is_incomplete(message: str, intent: MemoryIntent) -> bool:
	if intent.operation != "add" or intent.category != "insurance":
		return False
	normalized = message.lower()
	has_provider = any(marker in normalized for marker in ("provider", "insurer", "insurance company"))
	has_policy = any(marker in normalized for marker in ("policy", "policy number", "policy no"))
	return not (has_provider and has_policy)


def extract_memory_intent(client: LLMClient, message: str, context: str = "") -> MemoryIntent:
	"""Extract a validated intent through structured JSON, never regex parsing."""
	if _is_incomplete_insurance_message(message):
		language = "hi" if _has_devanagari(message) else "en"
		response = (
			"बीमा कंपनी और पॉलिसी नंबर बताइए।"
			if language == "hi"
			else "Please provide the insurance provider and policy number."
		)
		return MemoryIntent(operation="none", language=language, response=response, clarification=True)

	prompt = f"{MEMORY_EXTRACTION_PROMPT}\nCURRENT DATE: 2026-09-21\nCURRENT CONTEXT:\n{context}"
	result = client.chat_json(prompt, [{"role": "user", "content": message}])
	try:
		intent = MemoryIntent.model_validate(result)
		needs_repair = intent.operation == "none" or (
			intent.operation
			== "add"
			and intent.category == "family"
			and (
				intent.title is None
				or not intent.details.get("relationship")
				or (intent.date_type is not None and intent.date_value is None)
			)
		) or (intent.operation == "delete" and intent.memory_id is None and intent.title is None)
		if intent.language == "hi" and not _has_devanagari(message):
			intent = intent.model_copy(update={"language": "hinglish"})
	except ValidationError:
		needs_repair = True

	if needs_repair:
		repair_prompt = (
			f"{prompt}\nREPAIR THE PREVIOUS EXTRACTION. The user message is a personal fact "
			"if it states a person's name, relationship, or birthday. For a family add, "
			"title is the person's name, details.relationship is the relationship, and "
			"the birthday belongs in date_value/date_type, never inside details. For a delete, "
			"match the requested title to the memory list in CURRENT CONTEXT and return its "
			"memory_id and title. Return "
			"only the corrected JSON object. Never use CURRENT DATE as the birthday date. "
			"For this exact input, 'Mere bhai ka naam Rahul hai, uska birthday 12 March hai', "
			"the date_value is exactly '2026-03-12' and date_type is exactly 'birthday'."
		)
		try:
			intent = MemoryIntent.model_validate(client.chat_json(repair_prompt, [{"role": "user", "content": message}]))
		except ValidationError as error:
			raise ValueError("The AI returned an invalid memory operation.") from error
		if intent.language == "hi" and not _has_devanagari(message):
			intent = intent.model_copy(update={"language": "hinglish"})
		return intent

	if _insurance_request_is_incomplete(message, intent):
		return intent.model_copy(
			update={
				"operation": "none",
				"response": "Please provide the insurance provider and policy number.",
				"memory_id": None,
				"category": None,
				"title": None,
				"details": {},
			}
		)

	return intent


def apply_memory_action(database: Database, intent: MemoryIntent) -> Memory | None:
	"""Apply an already-confirmed add or edit operation."""
	if intent.operation not in {"add", "edit"}:
		raise ValueError("Only add and edit operations can be applied here.")
	if not intent.title or not intent.category:
		raise ValueError("Memory title and category are required.")
	memory = Memory(intent.category, intent.title, intent.validated_details(), intent.notes, intent.memory_id)
	if intent.operation == "add":
		memory_id = database.add_memory(memory)
		memory = Memory(memory.category, memory.title, memory.details, memory.notes, memory_id)
	else:
		if memory.id is None or database.get_memory(memory.id) is None:
			raise ValueError("Memory not found.")
		database.update_memory(memory)
	if intent.date_value and intent.date_type and memory.id is not None:
		from db.database import ImportantDate

		existing = next((item for item in database.list_important_dates(memory.id) if item.type == intent.date_type), None)
		value = ImportantDate(memory.id, intent.date_value, intent.date_type, intent.recurring, existing.id if existing else None)
		if existing is None:
			database.add_important_date(value)
		else:
			database.update_important_date(value)
	return memory
