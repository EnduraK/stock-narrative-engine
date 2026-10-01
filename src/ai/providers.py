"""
Multi-provider AI router.

Priority order (auto-detects which keys are available):
  1. Anthropic Claude  — best nuanced financial reasoning
  2. OpenAI GPT-4      — strong alternative
  3. Google Gemini     — free tier available
  4. Ollama (local)    — 100% free, runs locally, no data leaves machine

Pass provider="auto" to let the engine pick based on available keys.
"""

import json
import logging
import os
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Provider constants
# ---------------------------------------------------------------------------
ANTHROPIC  = "anthropic"
OPENAI     = "openai"
GEMINI     = "gemini"
OLLAMA     = "ollama"

DEFAULT_MODELS = {
    ANTHROPIC: "claude-haiku-4-5-20251001",
    OPENAI:    "gpt-4o",
    GEMINI:    "gemini-1.5-pro",
    OLLAMA:    "llama3",            # or mistral, etc.
}

OLLAMA_DEFAULT_URL = "http://localhost:11434/api/generate"


# ---------------------------------------------------------------------------
# Core completion function
# ---------------------------------------------------------------------------
def complete(
    system_prompt: str,
    user_prompt: str,
    provider: str = "auto",
    model: Optional[str] = None,
    temperature: float = 0.3,
    max_tokens: int = 2048,
    anthropic_key: str = "",
    openai_key: str = "",
    gemini_key: str = "",
    ollama_url: str = "",
) -> str:
    """
    Send a prompt to the chosen provider and return the text response.

    provider="auto" cascades through available providers in priority order.
    """
    resolved_provider = _resolve_provider(
        provider, anthropic_key, openai_key, gemini_key, ollama_url
    )
    resolved_model = model or DEFAULT_MODELS[resolved_provider]

    logger.debug("Using provider=%s model=%s", resolved_provider, resolved_model)

    if resolved_provider == ANTHROPIC:
        return _call_anthropic(
            system_prompt, user_prompt, resolved_model,
            temperature, max_tokens, anthropic_key
        )
    elif resolved_provider == OPENAI:
        return _call_openai(
            system_prompt, user_prompt, resolved_model,
            temperature, max_tokens, openai_key
        )
    elif resolved_provider == GEMINI:
        return _call_gemini(
            system_prompt, user_prompt, resolved_model,
            temperature, max_tokens, gemini_key
        )
    elif resolved_provider == OLLAMA:
        return _call_ollama(
            system_prompt, user_prompt, resolved_model,
            temperature, max_tokens, ollama_url or OLLAMA_DEFAULT_URL
        )
    else:
        raise ValueError(f"Unknown provider: {resolved_provider}")


# ---------------------------------------------------------------------------
# Anthropic (Claude)
# ---------------------------------------------------------------------------
def _call_anthropic(
    system: str, user: str, model: str,
    temperature: float, max_tokens: int, api_key: str
) -> str:
    try:
        import anthropic
    except ImportError:
        raise ImportError("Run: pip install anthropic")

    client = anthropic.Anthropic(api_key=api_key, max_retries=0)
    last_exc = None
    for attempt in range(6):
        try:
            message = client.messages.create(
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                system=system,
                messages=[{"role": "user", "content": user}],
            )
            return message.content[0].text
        except anthropic._exceptions.OverloadedError as exc:
            last_exc = exc
            wait = 15 * (2 ** attempt)
            logger.warning("Anthropic overloaded (attempt %d/6) — waiting %ds", attempt + 1, wait)
            time.sleep(wait)
    raise last_exc


# ---------------------------------------------------------------------------
# OpenAI (GPT-4)
# ---------------------------------------------------------------------------
def _call_openai(
    system: str, user: str, model: str,
    temperature: float, max_tokens: int, api_key: str
) -> str:
    try:
        from openai import OpenAI
    except ImportError:
        raise ImportError("Run: pip install openai")

    client = OpenAI(api_key=api_key)
    resp = client.chat.completions.create(
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        messages=[
            {"role": "system", "content": system},
            {"role": "user",   "content": user},
        ],
    )
    return resp.choices[0].message.content


# ---------------------------------------------------------------------------
# Google Gemini
# ---------------------------------------------------------------------------
def _call_gemini(
    system: str, user: str, model: str,
    temperature: float, max_tokens: int, api_key: str
) -> str:
    try:
        import google.generativeai as genai
    except ImportError:
        raise ImportError("Run: pip install google-generativeai")

    genai.configure(api_key=api_key)
    gmodel = genai.GenerativeModel(
        model_name=model,
        system_instruction=system,
        generation_config=genai.types.GenerationConfig(
            temperature=temperature,
            max_output_tokens=max_tokens,
        ),
    )
    response = gmodel.generate_content(user)
    return response.text


# ---------------------------------------------------------------------------
# Ollama (local, free, private)
# ---------------------------------------------------------------------------
def _call_ollama(
    system: str, user: str, model: str,
    temperature: float, max_tokens: int, base_url: str
) -> str:
    import requests

    payload = {
        "model":  model,
        "prompt": f"System: {system}\n\nUser: {user}",
        "stream": False,
        "options": {
            "temperature": temperature,
            "num_predict": max_tokens,
        },
    }
    resp = requests.post(base_url, json=payload, timeout=120)
    resp.raise_for_status()
    return resp.json().get("response", "")


# ---------------------------------------------------------------------------
# Auto-resolve provider
# ---------------------------------------------------------------------------
def _resolve_provider(
    provider: str,
    anthropic_key: str,
    openai_key: str,
    gemini_key: str,
    ollama_url: str,
) -> str:
    if provider != "auto":
        return provider

    if anthropic_key:
        return ANTHROPIC
    if openai_key:
        return OPENAI
    if gemini_key:
        return GEMINI
    # Try Ollama if running locally
    try:
        import requests
        url = ollama_url or OLLAMA_DEFAULT_URL
        requests.get(url.replace("/api/generate", "/api/tags"), timeout=2)
        return OLLAMA
    except Exception:
        pass

    raise RuntimeError(
        "No AI provider available. Set ANTHROPIC_API_KEY, OPENAI_API_KEY, "
        "GEMINI_API_KEY, or start an Ollama server."
    )


def list_available_providers(
    anthropic_key: str = "",
    openai_key: str = "",
    gemini_key: str = "",
    ollama_url: str = "",
) -> List[str]:
    """Return which providers are currently reachable."""
    available = []
    if anthropic_key:
        available.append(ANTHROPIC)
    if openai_key:
        available.append(OPENAI)
    if gemini_key:
        available.append(GEMINI)
    try:
        import requests
        url = ollama_url or OLLAMA_DEFAULT_URL
        requests.get(url.replace("/api/generate", "/api/tags"), timeout=2)
        available.append(OLLAMA)
    except Exception:
        pass
    return available
