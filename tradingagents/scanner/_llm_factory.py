"""Shared LLM client factory for the scanner package.

Used by both `playbook_llm.py` (day-trade) and `longterm_playbook_llm.py`
(long-term). Honors `provider`/`model` overrides; falls back to
DEFAULT_CONFIG. Skips temperature for models that reject it.
"""

from __future__ import annotations

import os
from typing import Optional

from tradingagents.default_config import DEFAULT_CONFIG


def get_llm(provider: Optional[str] = None, model: Optional[str] = None):
    """Construct the quick-think LLM. `provider` and `model` override DEFAULT_CONFIG."""
    provider = (provider or DEFAULT_CONFIG.get("llm_provider", "openai")).lower()

    if provider == "anthropic":
        from langchain_anthropic import ChatAnthropic

        api_key = os.environ.get("ANTHROPIC_API_KEY") or DEFAULT_CONFIG.get("anthropic_api_key")
        model = model or DEFAULT_CONFIG.get("anthropic_quick_think_llm", "claude-sonnet-4-6")
        anthropic_no_temp = ("claude-opus-4",)
        kwargs = {}
        if not any(prefix in model for prefix in anthropic_no_temp):
            kwargs["temperature"] = 0.2
        return ChatAnthropic(model=model, api_key=api_key, **kwargs)

    from langchain_openai import ChatOpenAI

    api_key = os.environ.get("OPENAI_API_KEY") or DEFAULT_CONFIG.get("openai_api_key")
    model = model or DEFAULT_CONFIG.get("quick_think_llm", "gpt-4o-mini")
    kwargs = {}
    no_temp = ["o1", "o3", "o4", "gpt-5"]
    if not any(prefix in model for prefix in no_temp):
        kwargs["temperature"] = 0.2
    return ChatOpenAI(model=model, openai_api_key=api_key, **kwargs)
