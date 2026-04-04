"""
ollama_client.py — Local Ollama LLM interface for BrainCache.

All AI inference goes through this module.
No API keys. No external services. Talks to the Ollama
container at OLLAMA_HOST via its local HTTP API.
"""

import httpx
import os
import json
import logging

logger = logging.getLogger(__name__)

OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://ollama:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3.2")


def check_ollama_ready() -> bool:
    """
    Return True if Ollama is reachable and the configured
    model is available locally.
    """
    try:
        resp = httpx.get(f"{OLLAMA_HOST}/api/tags", timeout=5)
        resp.raise_for_status()
        tags = resp.json()
        models = [m["name"] for m in tags.get("models", [])]
        return any(OLLAMA_MODEL in m for m in models)
    except Exception as exc:
        logger.debug("Ollama not ready: %s", exc)
        return False


def pull_model_if_needed() -> None:
    """
    Pull OLLAMA_MODEL from Ollama registry if not already
    present locally. Blocking — logs progress as it streams.
    Called once on app startup as a background task.
    """
    if check_ollama_ready():
        logger.info(
            "Ollama model '%s' already available — skipping pull",
            OLLAMA_MODEL
        )
        return

    logger.info(
        "Pulling Ollama model '%s' — this may take several minutes "
        "on first run...",
        OLLAMA_MODEL
    )

    try:
        with httpx.stream(
            "POST",
            f"{OLLAMA_HOST}/api/pull",
            json={"name": OLLAMA_MODEL},
            timeout=600,
        ) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines():
                if line:
                    try:
                        data = json.loads(line)
                        status = data.get("status", "")
                        if status:
                            logger.info("Ollama pull: %s", status)
                    except json.JSONDecodeError:
                        pass
        logger.info("Model pull complete: %s", OLLAMA_MODEL)
    except httpx.HTTPError as exc:
        logger.error(
            "Failed to pull model '%s': %s — "
            "sessions will be unavailable until model is ready",
            OLLAMA_MODEL, exc
        )


def generate(
    prompt: str,
    system: str = None,
    expect_json: bool = False,
    timeout: int = 120,
) -> str:
    """
    Send a prompt to Ollama and return the response as a string.

    Args:
        prompt: The user prompt to send.
        system: Optional system instruction prepended to the prompt.
        expect_json: If True, sets format='json' in the request and
                     strips any markdown fences from the response.
        timeout: Request timeout in seconds.

    Returns:
        Response text from the model, stripped of surrounding
        whitespace and markdown fences if expect_json is True.

    Raises:
        httpx.HTTPError: If the Ollama API call fails.
    """
    payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
    }

    if system:
        payload["system"] = system

    if expect_json:
        payload["format"] = "json"

    resp = httpx.post(
        f"{OLLAMA_HOST}/api/generate",
        json=payload,
        timeout=timeout,
    )
    resp.raise_for_status()

    text = resp.json().get("response", "").strip()

    if expect_json:
        # Strip markdown code fences some models add despite format=json
        if text.startswith("```"):
            parts = text.split("```")
            if len(parts) >= 2:
                text = parts[1]
                if text.startswith("json"):
                    text = text[4:]
                text = text.strip()

    return text


def generate_json(
    prompt: str,
    system: str = None,
    timeout: int = 120,
) -> dict | list:
    """
    Generate a response from Ollama and parse it as JSON.

    Returns:
        Parsed dict or list.

    Raises:
        ValueError: If the model response cannot be parsed as JSON.
        httpx.HTTPError: If the Ollama API call fails.
    """
    text = generate(prompt, system=system, expect_json=True,
                    timeout=timeout)
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        logger.error(
            "Ollama response was not valid JSON.\n"
            "Model: %s\nRaw response (first 500 chars): %s",
            OLLAMA_MODEL, text[:500]
        )
        raise ValueError(
            f"Model did not return valid JSON: {exc}"
        ) from exc
