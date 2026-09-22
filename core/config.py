"""Backward-compatible imports for the root configuration module."""

from config import AssistantConfig, Config, LLMConfig, ModelConfig, PathConfig, get_model, load_config

__all__ = [
	"Config",
	"AssistantConfig",
	"LLMConfig",
	"ModelConfig",
	"PathConfig",
	"get_model",
	"load_config",
]
