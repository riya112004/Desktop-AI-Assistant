"""Executable checks for the provider-neutral LLM layer."""

from __future__ import annotations

import os
import re
from pathlib import Path

import httpx

import core.llm_client as llm_module
from core.config import LLMConfig
from core.llm_client import HostedClient, LLMClient, LLMError, OllamaClient, create_llm_client


class FakeResponse:
	def __init__(self, payload: dict) -> None:
		self.payload = payload

	def raise_for_status(self) -> None:
		return None

	def json(self) -> dict:
		return self.payload


def run_same_prompt(client: LLMClient) -> str:
	return client.chat(
		"You are a concise desktop assistant.",
		[{"role": "user", "content": "Say hello."}],
	)


def assert_provider_imports_are_isolated() -> None:
	pattern = re.compile(r"^\s*(?:from|import)\s+(?:openai|ollama)(?:\.|\s|$)")
	root = Path(__file__).resolve().parent
	violations = [
		path
		for path in root.rglob("*.py")
		if path != root / "core" / "llm_client.py"
		and any(pattern.match(line) for line in path.read_text(encoding="utf-8").splitlines())
	]
	assert not violations, f"Provider SDK imports found outside core/llm_client.py: {violations}"


def main() -> int:
	original_post = llm_module.httpx.post
	original_key = os.environ.get("OPENAI_API_KEY")
	try:
		def fake_post(url: str, **_: object) -> FakeResponse:
			if url.endswith("/api/chat"):
				return FakeResponse({"message": {"content": "local reply"}})
			return FakeResponse({"choices": [{"message": {"content": "hosted reply"}}]})

		llm_module.httpx.post = fake_post
		os.environ["OPENAI_API_KEY"] = "test-key"
		local = create_llm_client(LLMConfig("ollama", "test-model"))
		hosted = create_llm_client(LLMConfig("hosted", "test-model", "https://hosted.test/v1"))
		assert run_same_prompt(local) == "local reply"
		assert run_same_prompt(hosted) == "hosted reply"
		assert_provider_imports_are_isolated()

		class FencedClient(LLMClient):
			def chat(self, system_prompt: str, messages: list[dict[str, str]]) -> str:
				return '```json\n{"ok": true, "count": 2}\n```'

		assert FencedClient().chat_json("system", []) == {"ok": True, "count": 2}

		def offline_post(*_: object, **__: object) -> None:
			raise httpx.ConnectError("offline")

		llm_module.httpx.post = offline_post
		try:
			OllamaClient("test-model", "http://localhost:11434").chat("system", [])
			raise AssertionError("offline provider did not fail")
		except LLMError as error:
			assert "not running" in str(error)

		print("PASS: same prompt flow works for Ollama and hosted providers")
		print("PASS: fenced JSON is parsed by chat_json()")
		print("PASS: offline provider becomes a readable LLMError")
		print("PASS: provider SDK imports are isolated to core/llm_client.py")
		return 0
	finally:
		llm_module.httpx.post = original_post
		if original_key is None:
			os.environ.pop("OPENAI_API_KEY", None)
		else:
			os.environ["OPENAI_API_KEY"] = original_key


if __name__ == "__main__":
	raise SystemExit(main())