"""M4 structured memory and multilingual phrase checks."""

from __future__ import annotations

import tempfile
from pathlib import Path

from features.memory import MemoryIntent, apply_memory_action, extract_memory_intent
from db.database import Database


PHRASES = [
    ("My brother Rahul's birthday is 12 March", "en", {"relationship": "brother"}),
    ("मेरे भाई राहुल का जन्मदिन 12 मार्च है", "hi", {"relationship": "भाई"}),
    ("Mere bhai ka naam Rahul hai, uska birthday 12 March hai", "hinglish", {"relationship": "bhai"}),
]


class FakeClient:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def chat_json(self, system_prompt: str, messages: list[dict[str, str]]) -> dict:
        return self.payload


def main() -> int:
    for phrase, language, details in PHRASES:
        intent = extract_memory_intent(
            FakeClient({
                "operation": "add",
                "language": language,
                "response": "confirm",
                "category": "family",
                "title": "Rahul",
                "details": details,
                "date_value": "2026-03-12",
                "date_type": "birthday",
                "recurring": True,
            }),
            phrase,
        )
        assert intent.language == language
        assert intent.validated_details()["relationship"] == details["relationship"]

    with tempfile.TemporaryDirectory() as directory:
        database = Database(Path(directory) / "assistant.db")
        intent = MemoryIntent(
            operation="add",
            language="hinglish",
            category="family",
            title="Rahul",
            details={"relationship": "brother"},
            date_value="2026-03-12",
            date_type="birthday",
            recurring=True,
        )
        assert database.list_memories() == []
        saved = apply_memory_action(database, intent)
        assert saved is not None
        assert saved.title == "Rahul"
        assert saved.details["relationship"] == "brother"
        assert database.get_memory(saved.id) is not None
        birthday = database.list_important_dates(saved.id)[0]
        assert birthday.type == "birthday"
        assert birthday.date == "2026-03-12"

    print("PASS: English, Hindi, and Hinglish structured phrases validate")
    print("PASS: confirmed add path stores typed family memory and birthday")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
