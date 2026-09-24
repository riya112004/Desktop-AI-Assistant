"""Start the desktop UI and its optional local API with one command."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from urllib.request import urlopen


API_URL = "http://127.0.0.1:8001/api/health"


def _api_is_running() -> bool:
	try:
		with urlopen(API_URL, timeout=1) as response:
			return response.status == 200
	except OSError:
		return False


def main() -> int:
	api_process: subprocess.Popen[bytes] | None = None
	if not _api_is_running():
		api_process = subprocess.Popen(
			[
				sys.executable,
				"-m",
				"uvicorn",
				"api:app",
				"--host",
				"127.0.0.1",
				"--port",
				"8001",
			],
			cwd=os.path.dirname(os.path.abspath(__file__)),
			stdout=subprocess.DEVNULL,
			stderr=subprocess.DEVNULL,
		)
		for _ in range(20):
			if _api_is_running():
				break
			time.sleep(0.25)

	try:
		from main import main as desktop_main

		return desktop_main()
	finally:
		if api_process is not None and api_process.poll() is None:
			api_process.terminate()
			try:
				api_process.wait(timeout=5)
			except subprocess.TimeoutExpired:
				api_process.kill()


if __name__ == "__main__":
		raise SystemExit(main())