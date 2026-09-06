"""Provider-agnostic AI layer for Dockerfile generation.

Supported providers (selected via AI_PROVIDER, default: openrouter):

    openrouter  OpenAI-compatible API, default model ``openrouter/free``
                (auto-router over currently available free models).
    gemini      Google AI Studio (Gemini Developer API), REST via stdlib.
    groq        OpenAI-compatible API at https://api.groq.com/openai/v1.
    openai      Optional legacy provider (never required, never default).

Only the selected provider needs an API key. Every provider exposes the
same internal operation — full response text for the Dockerfile prompt —
so the rest of GitContainer (prompt, JSON contract, WebSocket streaming,
editor) never cares which provider produced it.

Free-tier reality check (Sep 2026): free model IDs rotate and quotas
change. All models are configurable via environment variables; if a
configured model disappears the provider returns a clear error naming
the model. Never describe this as "unlimited free AI" — it is
free-tier / free-model support.
"""

import asyncio
import json
import os
import urllib.request
import urllib.error
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, List, Optional

from dotenv import load_dotenv

load_dotenv()

PROVIDER_OPENROUTER = "openrouter"
PROVIDER_GEMINI = "gemini"
PROVIDER_GROQ = "groq"
PROVIDER_OPENAI = "openai"

DEFAULT_PROVIDER = PROVIDER_OPENROUTER
SUPPORTED_PROVIDERS = (
    PROVIDER_OPENROUTER,
    PROVIDER_GEMINI,
    PROVIDER_GROQ,
    PROVIDER_OPENAI,
)

# Defaults only — every one is overridable via environment.
DEFAULT_OPENROUTER_MODEL = "openrouter/free"
DEFAULT_GEMINI_MODEL = "gemini-2.0-flash"
DEFAULT_GROQ_MODEL = "llama-3.3-70b-versatile"
DEFAULT_OPENAI_MODEL = "gpt-4o-mini"

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
GROQ_BASE_URL = "https://api.groq.com/openai/v1"
GEMINI_GENERATE_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
)

SYSTEM_PROMPT = (
    "You are an expert DevOps engineer specializing in containerization. "
    "Generate production-ready Dockerfiles based on repository analysis. "
    "ALWAYS respond with valid JSON only - no markdown, no explanations, "
    "no code blocks. Just pure JSON that can be parsed directly."
)

ProgressCallback = Optional[Callable[[str], Awaitable[Any]]]


@dataclass(frozen=True)
class AIProviderConfig:
    provider: str = DEFAULT_PROVIDER
    model: str = DEFAULT_OPENROUTER_MODEL
    api_key: str = ""

    @property
    def configured(self) -> bool:
        return bool(self.api_key)


def get_ai_config() -> AIProviderConfig:
    """Read the selected provider's config. Only that provider needs a key."""
    provider = (os.getenv("AI_PROVIDER", DEFAULT_PROVIDER) or DEFAULT_PROVIDER).strip().lower()
    if provider not in SUPPORTED_PROVIDERS:
        raise ValueError(
            f"Unknown AI provider: '{provider}'. "
            f"Supported providers: {', '.join(SUPPORTED_PROVIDERS)}. "
            "Set AI_PROVIDER to one of them."
        )
    if provider == PROVIDER_GEMINI:
        return AIProviderConfig(
            provider=provider,
            model=(os.getenv("GEMINI_MODEL", "") or DEFAULT_GEMINI_MODEL).strip(),
            api_key=(os.getenv("GEMINI_API_KEY", "") or "").strip(),
        )
    if provider == PROVIDER_GROQ:
        return AIProviderConfig(
            provider=provider,
            model=(os.getenv("GROQ_MODEL", "") or DEFAULT_GROQ_MODEL).strip(),
            api_key=(os.getenv("GROQ_API_KEY", "") or "").strip(),
        )
    if provider == PROVIDER_OPENAI:
        return AIProviderConfig(
            provider=provider,
            model=(os.getenv("OPENAI_MODEL", "") or DEFAULT_OPENAI_MODEL).strip(),
            api_key=(os.getenv("OPENAI_API_KEY", "") or "").strip(),
        )
    return AIProviderConfig(
        provider=PROVIDER_OPENROUTER,
        model=(os.getenv("OPENROUTER_MODEL", "") or DEFAULT_OPENROUTER_MODEL).strip(),
        api_key=(os.getenv("OPENROUTER_API_KEY", "") or "").strip(),
    )


def get_ai_status() -> Dict[str, Any]:
    """Secret-free AI status for health checks and setup scripts."""
    try:
        config = get_ai_config()
    except ValueError as exc:
        return {"provider": "", "model": "", "configured": False, "error": str(exc)}
    return {
        "provider": config.provider,
        "model": config.model,
        "configured": config.configured,
    }


def require_api_key(config: AIProviderConfig) -> str:
    """Return the key or raise an actionable, provider-specific error."""
    if config.api_key:
        return config.api_key
    env_var = {
        PROVIDER_OPENROUTER: "OPENROUTER_API_KEY",
        PROVIDER_GEMINI: "GEMINI_API_KEY",
        PROVIDER_GROQ: "GROQ_API_KEY",
        PROVIDER_OPENAI: "OPENAI_API_KEY",
    }[config.provider]
    where = {
        PROVIDER_OPENROUTER: "Create one at https://openrouter.ai/keys (no credit card needed for free models).",
        PROVIDER_GEMINI: "Create one at https://aistudio.google.com/apikey (free tier available).",
        PROVIDER_GROQ: "Create one at https://console.groq.com/keys.",
        PROVIDER_OPENAI: "Create one at https://platform.openai.com/api-keys (paid).",
    }[config.provider]
    raise ValueError(
        f"{env_var} is not configured, but AI provider '{config.provider}' is selected. "
        f"Add {env_var}=your-key to your .env file. {where}"
    )


def build_dockerfile_prompt(
    gitingest_summary: str,
    gitingest_tree: str,
    truncated_content: str,
    additional_instructions: Optional[str] = None,
) -> str:
    """Shared prompt — identical for every provider."""
    additional_instructions_section = ""
    if additional_instructions and additional_instructions.strip():
        additional_instructions_section = (
            f"\n\nADDITIONAL INSTRUCTIONS:\n{additional_instructions.strip()}"
        )
    return f"""Based on the following repository analysis, generate a comprehensive and production-ready Dockerfile.

PROJECT SUMMARY:
{gitingest_summary}

DIRECTORY STRUCTURE:
{gitingest_tree}

SOURCE CODE CONTEXT:
{truncated_content}{additional_instructions_section}

Please generate a Dockerfile that:
1. Uses appropriate base images for the detected technology stack
2. Includes proper dependency management
3. Sets up the correct working directory structure
4. Exposes necessary ports
5. Includes health checks where appropriate
6. Follows Docker best practices (multi-stage builds if beneficial, minimal layers, etc.)
7. Handles environment variables and configuration
8. Sets up proper user permissions for security

If you detect multiple services or a complex architecture, provide a main Dockerfile and suggest docker-compose.yml structure.

IMPORTANT: Respond ONLY with a valid JSON object. Do not include any markdown formatting, explanations, or code blocks. The response must be parseable JSON.

Required JSON format:
{{
  "dockerfile": "FROM python:3.9-slim\\nWORKDIR /app\\nCOPY . .\\nRUN pip install -r requirements.txt\\nEXPOSE 8000\\nCMD [\\"python\\", \\"app.py\\"]",
  "base_image_reasoning": "Explanation of why you chose the base image",
  "technology_stack": "Detected technologies and frameworks",
  "port_recommendations": ["8000", "80"],
  "additional_notes": "Any important setup or deployment notes",
  "docker_compose_suggestion": "Optional docker-compose.yml content if multiple services detected"
}}"""


async def _emit(callback: ProgressCallback, line: str) -> None:
    if callback is None:
        return
    try:
        result = callback(line)
        if asyncio.iscoroutine(result):
            await result
    except Exception:
        pass


def _friendly_provider_error(provider: str, model: str, detail: str) -> RuntimeError:
    """Map raw API failures to actionable errors (never leak keys)."""
    lowered = (detail or "").lower()
    hint = ""
    if "401" in lowered or "unauthorized" in lowered or "invalid api key" in lowered or "api key" in lowered and "invalid" in lowered:
        key_var = {
            PROVIDER_OPENROUTER: "OPENROUTER_API_KEY",
            PROVIDER_GEMINI: "GEMINI_API_KEY",
            PROVIDER_GROQ: "GROQ_API_KEY",
            PROVIDER_OPENAI: "OPENAI_API_KEY",
        }[provider]
        hint = f" Check that {key_var} is correct."
    elif "404" in lowered or "not found" in lowered or "does not exist" in lowered:
        hint = (
            f" The model '{model}' may have been renamed or removed. "
            "Free-model availability changes over time — pick a current model ID "
            "and set it via the provider's *_MODEL variable."
        )
    elif "429" in lowered or "rate" in lowered or "quota" in lowered or "resource_exhausted" in lowered:
        hint = (
            " Rate limit / free-tier quota reached. Wait a little and retry; "
            "free tiers are rate-limited."
        )
    return RuntimeError(f"AI provider '{provider}' failed.{hint} Details: {detail[:800]}".rstrip())


async def generate_openai_compatible(
    base_url: Optional[str],
    api_key: str,
    model: str,
    system_prompt: str,
    user_prompt: str,
    provider: str,
    progress_callback: ProgressCallback = None,
) -> str:
    """OpenAI-compatible chat completions with streaming (openrouter/groq/openai)."""
    from openai import AsyncOpenAI

    kwargs: Dict[str, Any] = {"api_key": api_key}
    if base_url:
        kwargs["base_url"] = base_url
    client = AsyncOpenAI(**kwargs)

    extra_headers = None
    if provider == PROVIDER_OPENROUTER:
        extra_headers = {
            "HTTP-Referer": "https://github.com/Armour007/cloud",
            "X-Title": "GitContainer Cloud",
        }
    try:
        create_kwargs: Dict[str, Any] = dict(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.3,
            max_tokens=2000,
            stream=True,
        )
        if extra_headers:
            create_kwargs["extra_headers"] = extra_headers
        response = await client.chat.completions.create(**create_kwargs)
    except Exception as exc:
        raise _friendly_provider_error(provider, model, str(exc)) from exc

    full_text = ""
    try:
        async for chunk in response:
            delta = chunk.choices[0].delta.content if chunk.choices else None
            if delta:
                full_text += delta
                await _emit(progress_callback, delta)
    except Exception as exc:
        raise _friendly_provider_error(provider, model, str(exc)) from exc
    if not full_text.strip():
        raise _friendly_provider_error(provider, model, "Empty response from model.")
    return full_text


def _gemini_post(api_key: str, model: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Blocking Gemini REST call (runs in a thread). No new dependencies."""
    url = GEMINI_GENERATE_URL.format(model=model) + f"?key={api_key}"
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            detail = exc.read().decode("utf-8", errors="replace")
        except Exception:
            detail = f"HTTP {exc.code}"
        raise _friendly_provider_error("gemini", model, f"HTTP {exc.code}: {detail}") from exc
    except Exception as exc:
        raise _friendly_provider_error("gemini", model, str(exc)) from exc


def extract_gemini_text(response_json: Dict[str, Any], model: str) -> str:
    """Pure helper (unit-testable): first text part of a generateContent response."""
    try:
        candidates = response_json.get("candidates", [])
        parts = candidates[0].get("content", {}).get("parts", [])
        text = "".join(part.get("text", "") for part in parts if isinstance(part, dict))
    except (IndexError, AttributeError, TypeError) as exc:
        raise RuntimeError(
            "Gemini returned an unexpected response shape (no candidates/content)."
        ) from exc
    if not text.strip():
        raise RuntimeError("Gemini returned an empty response.")
    return text


async def generate_gemini(
    api_key: str,
    model: str,
    system_prompt: str,
    user_prompt: str,
    progress_callback: ProgressCallback = None,
) -> str:
    """Gemini via generateContent. Emits text in slices to preserve WS streaming UX."""
    payload = {
        "system_instruction": {"parts": [{"text": system_prompt}]},
        "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
        "generationConfig": {"temperature": 0.3, "maxOutputTokens": 2000},
    }
    response_json = await asyncio.to_thread(_gemini_post, api_key, model, payload)
    text = extract_gemini_text(response_json, model)
    for i in range(0, len(text), 500):
        await _emit(progress_callback, text[i : i + 500])
    return text


async def generate_dockerfile_text(
    prompt: str,
    config: Optional[AIProviderConfig] = None,
    progress_callback: ProgressCallback = None,
) -> Dict[str, str]:
    """One operation for all providers: prompt in, full response text out.

    Returns {"text", "provider", "model"}. Raises with actionable errors.
    """
    cfg = config or get_ai_config()
    api_key = require_api_key(cfg)
    if cfg.provider == PROVIDER_GEMINI:
        text = await generate_gemini(api_key, cfg.model, SYSTEM_PROMPT, prompt, progress_callback)
    else:
        base_url = (
            OPENROUTER_BASE_URL
            if cfg.provider == PROVIDER_OPENROUTER
            else GROQ_BASE_URL
            if cfg.provider == PROVIDER_GROQ
            else None
        )
        text = await generate_openai_compatible(
            base_url, api_key, cfg.model, SYSTEM_PROMPT, prompt, cfg.provider, progress_callback
        )
    return {"text": text, "provider": cfg.provider, "model": cfg.model}


def provider_setup_hint(provider: str) -> List[str]:
    """Setup-script friendly metadata (no secrets)."""
    return {
        PROVIDER_OPENROUTER: [
            "OpenRouter (recommended — free models available)",
            "Get a key at https://openrouter.ai/keys (email signup, no card for free models)",
            "OPENROUTER_API_KEY",
        ],
        PROVIDER_GEMINI: [
            "Gemini (Google free tier)",
            "Get a key at https://aistudio.google.com/apikey (Google account)",
            "GEMINI_API_KEY",
        ],
        PROVIDER_GROQ: [
            "Groq (fast inference)",
            "Get a key at https://console.groq.com/keys",
            "GROQ_API_KEY",
        ],
        PROVIDER_OPENAI: [
            "OpenAI (optional, paid)",
            "Get a key at https://platform.openai.com/api-keys",
            "OPENAI_API_KEY",
        ],
    }[provider]
