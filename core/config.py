"""Application configuration loading."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class LLMConfig:
    provider: str
    model: str


@dataclass(frozen=True)
class PathConfig:
    data_dir: Path
    database: Path


@dataclass(frozen=True)
class Config:
    llm: LLMConfig
    paths: PathConfig


def load_config(config_path: Path | None = None) -> Config:
    """Load application settings from the JSON config file."""
    path = config_path or Path(__file__).resolve().parents[1] / "config.json"
    with path.open(encoding="utf-8") as config_file:
        raw: dict[str, Any] = json.load(config_file)

    llm = raw["llm"]
    paths = raw["paths"]
    project_root = path.parent

    return Config(
        llm=LLMConfig(provider=llm["provider"], model=llm["model"]),
        paths=PathConfig(
            data_dir=project_root / paths["data_dir"],
            database=project_root / paths["database"],
        ),
    )
