"""Backward-compatible imports for the root configuration module."""

from config import Config, LLMConfig, ModelConfig, PathConfig, get_model, load_config

__all__ = [
	"Config",
	"LLMConfig",
	"ModelConfig",
	"PathConfig",
	"get_model",
	"load_config",
]
