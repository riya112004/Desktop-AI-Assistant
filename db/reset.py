"""Destructive reset support for local application data."""

from __future__ import annotations

import sqlite3
import shutil
from pathlib import Path

from core.config import load_config
from db.database import Database


def wipe_all_data(database_path: Path | None = None, data_dir: Path | None = None) -> None:
	"""Delete every application row and every generated file under the data directory."""
	config = load_config()
	database_file = database_path or config.paths.database
	directory = data_dir or config.paths.data_dir

	if database_file.exists():
		connection = sqlite3.connect(database_file)
		try:
			connection.execute("PRAGMA foreign_keys = ON")
			tables = [
				row[0]
				for row in connection.execute(
					"SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
				).fetchall()
			]
			for table in tables:
				quoted_table = table.replace('"', '""')
				connection.execute(f'DELETE FROM "{quoted_table}"')
			connection.commit()
		finally:
			connection.close()

	if directory.exists():
		for artifact in directory.iterdir():
			if artifact == database_file:
				continue
			if artifact.is_dir() and not artifact.is_symlink():
				shutil.rmtree(artifact)
			else:
				artifact.unlink()

	if database_file.exists():
		Database(database_file).initialize()


if __name__ == "__main__":
	wipe_all_data()
	print("Database reset.")
