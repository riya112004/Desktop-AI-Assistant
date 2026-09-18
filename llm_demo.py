"""Send one prompt through the configured provider."""

from core.llm_client import LLMError, create_llm_client


def main() -> int:
	client = create_llm_client()
	try:
		print(client.chat("You are a concise desktop assistant.", [{"role": "user", "content": "Say hello in one sentence."}]))
	except LLMError as error:
		print(f"AI unavailable: {error}")
		return 1
	return 0


if __name__ == "__main__":
	raise SystemExit(main())