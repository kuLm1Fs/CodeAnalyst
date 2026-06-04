from __future__ import annotations

import os
from pathlib import Path
from typing import Any

_DOTENV_PATH = Path(__file__).resolve().parents[1] / ".env"


def _debug_enabled() -> bool:
    return os.getenv("LUMAK_DEBUG", "").strip().lower() in {"1", "true", "yes", "on"}


def _debug(message: str) -> None:
    if _debug_enabled():
        print(f"[gateway] {message}", flush=True)


def _load_env() -> None:
    if not _DOTENV_PATH.exists():
        _debug(f"_load_env: {_DOTENV_PATH} NOT FOUND")
        return
    _debug(f"_load_env: reading {_DOTENV_PATH}")
    for line in _DOTENV_PATH.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip("\"'")
        if key and value:
            _debug(f"_load_env: set {key}")
            os.environ[key] = value


_load_env()

from agent.config import AnthropicConfig, DeepSeekConfig, MiniMaxConfig, OpenAIConfig
from agent.LLM.anthropic_provider import AnthropicProvider
from agent.LLM.deepseek import DeepSeekProvider
from agent.LLM.minimax import MinimaxProvider
from agent.LLM.openai_compatible import OpenAICompatibleProvider

_ENV_MAP: dict[str, tuple[str, str, str]] = {
    "deepseek": ("DEEPSEEK_API_KEY", "DEEPSEEK_MODEL_ID", "DEEPSEEK_BASE_URL"),
    "anthropic": ("ANTHROPIC_API_KEY", "ANTHROPIC_MODEL_ID", "ANTHROPIC_BASE_URL"),
    "openai": ("OPENAI_API_KEY", "OPENAI_MODEL_ID", "OPENAI_BASE_URL"),
    "minimax": ("MINIMAX_API_KEY", "MINIMAX_MODEL_ID", "MINIMAX_BASE_URL"),
    "custom": ("CUSTOM_API_KEY", "CUSTOM_MODEL_ID", "CUSTOM_BASE_URL"),
}


def _from_env(provider: str) -> dict[str, str]:
    keys = _ENV_MAP.get(provider)
    if not keys:
        return {}
    env_key, env_model, env_url = keys
    result: dict[str, str] = {}
    val = os.getenv(env_key, "").strip()
    if val:
        result["api_key"] = val
    val = os.getenv(env_model, "").strip()
    if val:
        result["model"] = val
    val = os.getenv(env_url, "").strip()
    if val:
        result["base_url"] = val
    return result


def build_request_llm_client(message: dict[str, Any]) -> object | None:
    raw_config = message.get("provider_config")
    if not isinstance(raw_config, dict):
        return None

    provider = str(raw_config.get("provider", "")).strip().lower()
    api_key = str(raw_config.get("api_key", "")).strip()
    model = str(raw_config.get("model", "")).strip()
    base_url = str(raw_config.get("base_url", "")).strip()

    if not provider or not api_key or not model:
        return None

    _debug(f"llm client: provider={provider} model={model}")

    if provider == "minimax":
        if not base_url:
            return None
        return MinimaxProvider(MiniMaxConfig(api_key=api_key, base_url=base_url, model_id=model))
    if provider == "anthropic":
        return AnthropicProvider(AnthropicConfig(api_key=api_key, base_url=base_url, model_id=model))
    if provider == "openai":
        return OpenAICompatibleProvider(OpenAIConfig(api_key=api_key, base_url=base_url, model_id=model))
    if provider == "deepseek":
        return DeepSeekProvider(DeepSeekConfig(api_key=api_key, base_url=base_url or "https://api.deepseek.com", model_id=model))
    if provider == "custom":
        if not base_url:
            return None
        return OpenAICompatibleProvider(OpenAIConfig(api_key=api_key, base_url=base_url, model_id=model))

    supported = "anthropic, custom, deepseek, minimax, openai"
    raise ValueError(f"Unsupported request provider: {provider}. Supported: {supported}")
