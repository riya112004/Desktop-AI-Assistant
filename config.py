"""Central configuration and selectable model registry."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parent
CONFIG_PATH = PROJECT_ROOT / "config.json"


@dataclass(frozen=True)
class ModelConfig:
	"""Settings needed to create a client for one model."""

	provider: str
	model: str
	base_url: str = "http://localhost:11434"
	timeout_seconds: float = 60.0


# Add a model here when it becomes part of the application choices.
MODELS: dict[str, ModelConfig] = {
	"qwen3:0.6b": ModelConfig("ollama", "qwen3:0.6b"),
	"qwen3:1.7b": ModelConfig("ollama", "qwen3:1.7b"),
	"llama3.2:3b": ModelConfig("ollama", "llama3.2:3b"),
	"phi3:latest": ModelConfig("ollama", "phi3:latest"),
	"mistral:latest": ModelConfig("ollama", "mistral:latest"),
}


@dataclass(frozen=True)
class LLMConfig:
	provider: str
	model: str
	base_url: str = "http://localhost:11434"
	timeout_seconds: float = 30.0


@dataclass(frozen=True)
class PathConfig:
	data_dir: Path
	database: Path


@dataclass(frozen=True)
class Config:
	llm: LLMConfig
	paths: PathConfig


def load_config(config_path: Path | None = None) -> Config:
	"""Load the active application settings from config.json."""
	path = config_path or CONFIG_PATH
	with path.open(encoding="utf-8") as config_file:
		raw: dict[str, Any] = json.load(config_file)

	llm = raw["llm"]
	paths = raw["paths"]
	project_root = path.parent
	return Config(
		llm=LLMConfig(
			provider=llm["provider"],
			model=llm["model"],
			base_url=llm.get("base_url", "http://localhost:11434"),
			timeout_seconds=float(llm.get("timeout_seconds", 30.0)),
		),
		paths=PathConfig(
			data_dir=project_root / paths["data_dir"],
			database=project_root / paths["database"],
		),
	)


def get_model(model_name: str) -> ModelConfig:
	"""Get a named model configuration for explicit client creation."""
	try:
		return MODELS[model_name]
	except KeyError as error:
		raise ValueError(f"Unknown model: {model_name}") from error