"""
llm_provider.py — Pluggable LLM backend for chart interpretation.

Exposes get_interpretation(system_prompt, user_message) -> str with one
consistent signature regardless of provider. This is the callable that
interpretation_engine.interpret() and answer_astrology_question.answer_question()
both plug in as their `llm` argument.

Provider is chosen via the LLM_PROVIDER environment variable:
    LLM_PROVIDER=anthropic (default)   requires ANTHROPIC_API_KEY
    LLM_PROVIDER=google                requires GOOGLE_API_KEY

.env (if present) is loaded automatically on import.
"""

import os

from dotenv import load_dotenv

load_dotenv()

DEFAULT_CLAUDE_MODEL = "claude-sonnet-4-5"
# gemini-2.0-flash no longer has a free tier (quota limit 0); the -latest
# alias tracks the current free-tier flash model.
DEFAULT_GEMINI_MODEL = "gemini-flash-latest"


def _call_anthropic(system_prompt: str, user_message: str) -> str:
    """Interpretation LLM call (Claude API). Requires ANTHROPIC_API_KEY."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY missing, set it in .env")

    import json
    import urllib.request

    body = json.dumps({
        "model": os.getenv("CLAUDE_MODEL", DEFAULT_CLAUDE_MODEL),
        "max_tokens": 1500,
        "system": system_prompt,
        "messages": [{"role": "user", "content": user_message}],
    }).encode()
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=body,
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=90) as response:
        data = json.loads(response.read())
    return "".join(block["text"] for block in data["content"]
                   if block.get("type") == "text")


def _call_google(system_prompt: str, user_message: str) -> str:
    """Interpretation LLM call (Gemini API). Requires GOOGLE_API_KEY."""
    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError("GOOGLE_API_KEY missing, set it in .env")

    import google.generativeai as genai

    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(
        os.getenv("GEMINI_MODEL", DEFAULT_GEMINI_MODEL),
        system_instruction=system_prompt or None,
    )
    response = model.generate_content(user_message)
    return response.text


_PROVIDERS = {
    "anthropic": _call_anthropic,
    "google": _call_google,
}


def get_interpretation(system_prompt: str, user_message: str) -> str:
    """Call whichever LLM provider LLM_PROVIDER selects (default: anthropic).

    Raises RuntimeError with a clear message if the provider is unknown or
    its required API key is missing.
    """
    provider = os.getenv("LLM_PROVIDER", "anthropic")
    call = _PROVIDERS.get(provider)
    if call is None:
        raise RuntimeError(
            f"Unknown LLM_PROVIDER {provider!r}; expected one of {sorted(_PROVIDERS)}."
        )
    return call(system_prompt, user_message)


_REQUIRED_KEY_NAMES = {"anthropic": "ANTHROPIC_API_KEY", "google": "GOOGLE_API_KEY"}


def required_key_name() -> str:
    """Name of the env var the currently selected LLM_PROVIDER needs."""
    provider = os.getenv("LLM_PROVIDER", "anthropic")
    return _REQUIRED_KEY_NAMES.get(provider, "a valid LLM_PROVIDER API key")


def get_llm():
    """get_interpretation if the selected provider's API key is configured, else None.

    For callers (like app.py's /api/ask) that want to skip the LLM call
    entirely and degrade gracefully when nothing is configured, rather than
    raise. Direct callers of get_interpretation() still get the clear
    RuntimeError above if they call it without a key set.
    """
    required_key = _REQUIRED_KEY_NAMES.get(os.getenv("LLM_PROVIDER", "anthropic"))
    if required_key and os.getenv(required_key):
        return get_interpretation
    return None


if __name__ == "__main__":
    provider = os.getenv("LLM_PROVIDER", "anthropic")
    print(f"LLM_PROVIDER = {provider!r}")
    print(f"get_llm() configured: {get_llm() is not None}")

    try:
        answer = get_interpretation(
            "You are a terse test assistant. Reply in under 10 words.",
            "Say hello and name yourself.",
        )
        print(f"{provider} response: {answer}")
    except RuntimeError as e:
        print(f"SKIPPED: {e}")
