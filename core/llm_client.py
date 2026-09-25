"""Provider-neutral LLM clients and factory."""

from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Mapping, Sequence

import httpx

from core.config import LLMConfig, load_config


Message = Mapping[str, str]


class LLMError(RuntimeError):
	"""Readable, user-facing error from an LLM provider."""


class LLMClient(ABC):
	"""Stable interface used by features instead of provider-specific SDKs."""

	@abstractmethod
	def chat(self, system_prompt: str, messages: Sequence[Message]) -> str:
		"""Return the provider's text response."""

	def chat_json(self, system_prompt: str, messages: Sequence[Message]) -> dict[str, Any]:
		"""Return a JSON object from the provider's response."""
		response = self.chat(
			system_prompt + "\nReturn only a valid JSON object. Do not use markdown fences.",
			messages,
		)
		response = response.strip()
		if response.startswith("```") and response.endswith("```"):
			lines = response.splitlines()
			if lines and lines[0].strip().lower() in {"```", "```json"}:
				lines = lines[1:]
			if lines and lines[-1].strip() == "```":
				lines = lines[:-1]
			response = "\n".join(lines).strip()
		try:
			value = json.loads(response)
		except json.JSONDecodeError as error:
			raise LLMError("The AI returned invalid structured data.") from error
		if not isinstance(value, dict):
			raise LLMError("The AI returned structured data in an unexpected format.")
		return value


class FallbackClient(LLMClient):
	"""Try a secondary model when the primary provider cannot answer."""

	def __init__(self, primary: LLMClient, fallback: LLMClient) -> None:
		self.primary = primary
		self.fallback = fallback

	def chat(self, system_prompt: str, messages: Sequence[Message]) -> str:
		try:
			return self.primary.chat(system_prompt, messages)
		except LLMError as primary_error:
			try:
				return self.fallback.chat(system_prompt, messages)
			except LLMError as fallback_error:
				raise LLMError(
					f"Primary AI failed ({primary_error}); fallback AI failed ({fallback_error})."
				) from fallback_error


def _load_dotenv(path: Path | None = None) -> dict[str, str]:
	"""Load simple KEY=VALUE entries without requiring a dotenv package."""
	env_path = path or Path(__file__).resolve().parents[1] / ".env"
	if not env_path.exists():
		return {}
	values: dict[str, str] = {}
	for line in env_path.read_text(encoding="utf-8").splitlines():
		line = line.strip()
		if not line or line.startswith("#") or "=" not in line:
			continue
		key, value = line.split("=", 1)
		values[key.strip()] = value.strip().strip("\"'")
	return values


def _request_error(error: Exception, provider: str) -> LLMError:
	if isinstance(error, httpx.TimeoutException):
		return LLMError(f"The {provider} AI request timed out. Try again shortly.")
	if isinstance(error, httpx.ConnectError):
		return LLMError(f"The {provider} AI service is not running or cannot be reached.")
	if isinstance(error, httpx.HTTPStatusError):
		return LLMError(f"The {provider} AI service returned HTTP {error.response.status_code}.")
	return LLMError(f"The {provider} AI request failed.")


class OllamaClient(LLMClient):
	"""Local Ollama client using Ollama's HTTP API."""

	def __init__(self, model: str, base_url: str, timeout_seconds: float = 30.0) -> None:
		self.model = model
		self.base_url = base_url.rstrip("/")
		self.timeout_seconds = timeout_seconds

	def chat(self, system_prompt: str, messages: Sequence[Message]) -> str:
		payload = {
			"model": self.model,
			"stream": False,
			"think": False,
			"keep_alive": "10m",
			"options": {"num_ctx": 2048, "num_predict": 350, "temperature": 0.2},
			"messages": [{"role": "system", "content": system_prompt}, *messages],
		}
		try:
			response = httpx.post(f"{self.base_url}/api/chat", json=payload, timeout=self.timeout_seconds)
			response.raise_for_status()
			content = response.json().get("message", {}).get("content", "").strip()
		except (httpx.HTTPError, ValueError, AttributeError) as error:
			raise _request_error(error, "Ollama") from error
		if not content:
			raise LLMError("Ollama returned an empty response.")
		return content


class HostedClient(LLMClient):
	"""Hosted OpenAI-compatible client; the API key is read from .env or the environment."""

	def __init__(self, model: str, base_url: str = "https://api.openai.com/v1", timeout_seconds: float = 30.0, env_path: Path | None = None) -> None:
		values = _load_dotenv(env_path)
		self.api_key = os.getenv("OPENAI_API_KEY") or values.get("OPENAI_API_KEY", "")
		self.model = model
		self.base_url = base_url.rstrip("/")
		self.timeout_seconds = timeout_seconds

	def chat(self, system_prompt: str, messages: Sequence[Message]) -> str:
		if not self.api_key:
			raise LLMError("The hosted AI provider needs OPENAI_API_KEY in .env.")
		payload = {
			"model": self.model,
			"messages": [{"role": "system", "content": system_prompt}, *messages],
		}
		try:
			response = httpx.post(
				f"{self.base_url}/chat/completions",
				headers={"Authorization": f"Bearer {self.api_key}"},
				json=payload,
				timeout=self.timeout_seconds,
			)
			response.raise_for_status()
			content = response.json()["choices"][0]["message"]["content"].strip()
		except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as error:
			raise _request_error(error, "hosted") from error
		if not content:
			raise LLMError("The hosted AI provider returned an empty response.")
		return content


def create_llm_client(config: LLMConfig | None = None) -> LLMClient:
	"""Create the configured provider client."""
	settings = config or load_config().llm
	primary = _create_configured_client(settings.provider, settings.model, settings.base_url, settings.timeout_seconds)
	if not settings.fallback_model:
		return primary
	fallback = _create_configured_client(
		settings.fallback_provider or settings.provider,
		settings.fallback_model,
		settings.fallback_base_url or settings.base_url,
		settings.fallback_timeout_seconds or settings.timeout_seconds,
	)
	return FallbackClient(primary, fallback)


def _create_configured_client(provider_name: str, model: str, base_url: str, timeout_seconds: float) -> LLMClient:
	provider = provider_name.lower()
	if provider in {"ollama", "local"}:
		return OllamaClient(model, base_url, timeout_seconds)
	if provider in {"openai", "hosted"}:
		hosted_url = base_url if base_url != "http://localhost:11434" else "https://api.openai.com/v1"
		return HostedClient(model, hosted_url, timeout_seconds)
	raise LLMError(f"Unsupported AI provider: {provider_name}")


LLMClientFactory = create_llm_client
