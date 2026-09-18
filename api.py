"""HTTP API for the desktop assistant data layer."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException, Query, Response
from pydantic import BaseModel, Field

from core.config import load_config
from core.llm_client import LLMError, create_llm_client
from db.database import Database, ImportantDate, Memory, Reminder, UserProfile


app = FastAPI(title="Desktop AI Assistant API", version="1.0.0")
database = Database()


class ProfileInput(BaseModel):
    name: str
    language_pref: str = "en"
    personality: str = ""
    city: str = ""
    zodiac_sign: str = ""


class MemoryInput(BaseModel):
    category: str
    title: str
    details: dict[str, Any] = Field(default_factory=dict)
    notes: str = ""


class ImportantDateInput(BaseModel):
    memory_id: int
    date: str = Field(description="ISO date, for example 2026-09-25")
    type: str = Field(description="birthday, renewal, or service")
    recurring: bool = False


class ReminderInput(BaseModel):
    text: str
    due_at: str = Field(description="ISO timestamp, for example 2026-09-18T09:00:00+00:00")
    recurrence_rule: str | None = None
    status: str = "pending"


class ReminderStatusInput(BaseModel):
    status: str


class MessageInput(BaseModel):
    role: str
    content: str


class LLMRequest(BaseModel):
    system_prompt: str = "You are a helpful desktop assistant."
    messages: list[MessageInput] = Field(min_length=1)


class StateInput(BaseModel):
    value: str


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/llm/provider")
def llm_provider() -> dict[str, str | float]:
    """Show the configured provider without exposing credentials."""
    settings = load_config().llm
    return {
        "provider": settings.provider,
        "model": settings.model,
        "base_url": settings.base_url,
        "timeout_seconds": settings.timeout_seconds,
    }


@app.post("/api/llm/chat")
def llm_chat(request: LLMRequest) -> dict[str, str]:
    """Send a provider-neutral chat request."""
    try:
        reply = create_llm_client().chat(
            request.system_prompt,
            [message.model_dump() for message in request.messages],
        )
    except LLMError as error:
        raise HTTPException(status_code=503, detail=f"AI unavailable: {error}") from error
    return {"reply": reply}


@app.post("/api/llm/chat-json")
def llm_chat_json(request: LLMRequest) -> dict[str, object]:
    """Send a chat request and parse the response as a JSON object."""
    try:
        data = create_llm_client().chat_json(
            request.system_prompt,
            [message.model_dump() for message in request.messages],
        )
    except LLMError as error:
        raise HTTPException(status_code=503, detail=f"AI unavailable: {error}") from error
    return {"data": data}


@app.get("/api/profile")
def get_profile() -> UserProfile | None:
    return database.get_profile()


@app.put("/api/profile")
def save_profile(profile: ProfileInput) -> UserProfile:
    value = UserProfile(**profile.model_dump())
    database.upsert_profile(value)
    return value


@app.post("/api/memories", status_code=201)
def create_memory(memory: MemoryInput) -> Memory:
    memory_id = database.add_memory(Memory(**memory.model_dump()))
    return database.get_memory(memory_id)  # type: ignore[return-value]


@app.get("/api/memories")
def list_memories(category: str | None = Query(default=None)) -> list[Memory]:
    return database.list_memories(category)


@app.get("/api/memories/upcoming-dates")
def upcoming_dates(start_date: str, end_date: str) -> list[dict[str, Any]]:
    return database.dates_due_between(start_date, end_date)


@app.get("/api/memories/{memory_id}")
def get_memory(memory_id: int) -> Memory:
    memory = database.get_memory(memory_id)
    if memory is None:
        raise HTTPException(status_code=404, detail="Memory not found")
    return memory


@app.put("/api/memories/{memory_id}")
def update_memory(memory_id: int, memory: MemoryInput) -> Memory:
    current = database.get_memory(memory_id)
    if current is None:
        raise HTTPException(status_code=404, detail="Memory not found")
    database.update_memory(Memory(id=memory_id, **memory.model_dump()))
    return database.get_memory(memory_id)  # type: ignore[return-value]


@app.delete("/api/memories/{memory_id}", status_code=204)
def delete_memory(memory_id: int) -> Response:
    if database.get_memory(memory_id) is None:
        raise HTTPException(status_code=404, detail="Memory not found")
    database.delete_memory(memory_id)
    return Response(status_code=204)


@app.post("/api/important-dates", status_code=201)
def create_important_date(value: ImportantDateInput) -> dict[str, Any]:
    if database.get_memory(value.memory_id) is None:
        raise HTTPException(status_code=404, detail="Memory not found")
    date_id = database.add_important_date(ImportantDate(**value.model_dump()))
    return {"id": date_id, **value.model_dump()}


@app.post("/api/reminders", status_code=201)
def create_reminder(reminder: ReminderInput) -> dict[str, Any]:
    reminder_id = database.add_reminder(Reminder(**reminder.model_dump()))
    return {"id": reminder_id, **reminder.model_dump()}


@app.get("/api/reminders")
def list_reminders(status: str | None = Query(default=None)) -> list[dict[str, Any]]:
    return database.list_reminders(status)


@app.patch("/api/reminders/{reminder_id}/status")
def update_reminder_status(reminder_id: int, value: ReminderStatusInput) -> dict[str, str | int]:
    reminders = database.list_reminders()
    if not any(reminder["id"] == reminder_id for reminder in reminders):
        raise HTTPException(status_code=404, detail="Reminder not found")
    database.update_reminder_status(reminder_id, value.status)
    return {"id": reminder_id, "status": value.status}


@app.delete("/api/reminders/{reminder_id}", status_code=204)
def delete_reminder(reminder_id: int) -> Response:
    if not any(reminder["id"] == reminder_id for reminder in database.list_reminders()):
        raise HTTPException(status_code=404, detail="Reminder not found")
    database.delete_reminder(reminder_id)
    return Response(status_code=204)


@app.post("/api/conversation", status_code=201)
def log_message(message: MessageInput) -> dict[str, Any]:
    message_id = database.log_message(message.role, message.content)
    return {"id": message_id, **message.model_dump()}


@app.get("/api/conversation")
def get_conversation(limit: int = Query(default=50, ge=1, le=500)) -> list[dict[str, Any]]:
    return database.get_conversation(limit)


@app.get("/api/state/{key}")
def get_state(key: str) -> dict[str, str | None]:
    return {"key": key, "value": database.get_state(key)}


@app.put("/api/state/{key}")
def set_state(key: str, value: StateInput) -> dict[str, str]:
    database.set_state(key, value.value)
    return {"key": key, "value": value.value}
