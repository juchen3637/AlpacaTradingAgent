"""Unit tests for the catalyst LLM web-search explainer."""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

import pytest

from tradingagents.scanner.catalyst_explainer import (
    _build_user_prompt,
    explain_catalyst,
)
from tradingagents.scanner.models import CatalystFacts


def _facts(category: str = "M&A") -> CatalystFacts:
    return CatalystFacts(
        has_catalyst=True,
        category=category,
        short_text="ACME acquires Foo",
        structured_md="**ACME announces acquisition**\n\nDetails…",
        raw_items=({"headline": "ACME acquires Foo Inc", "url": "https://x.com/a"},),
    )


# ─── User prompt builder ──────────────────────────────────────────────

@pytest.mark.unit
def test_build_user_prompt_contains_symbol_and_category():
    prompt = _build_user_prompt("ACME", _facts(category="FDA"))
    assert "ACME" in prompt
    assert "FDA" in prompt


@pytest.mark.unit
def test_build_user_prompt_includes_short_text_and_raw_items():
    facts = _facts()
    prompt = _build_user_prompt("ACME", facts)
    assert facts.short_text in prompt
    assert "ACME acquires Foo Inc" in prompt


# ─── explain_catalyst dispatch ────────────────────────────────────────

@pytest.mark.unit
def test_explain_catalyst_returns_empty_for_no_catalyst():
    facts = CatalystFacts(has_catalyst=False)
    result = explain_catalyst("ACME", facts, provider="openai", model="gpt-5-mini")
    assert result == ""


@pytest.mark.unit
def test_explain_catalyst_calls_openai_path_when_provider_openai():
    facts = _facts()
    fake_llm = MagicMock()
    fake_llm.invoke.return_value = MagicMock(content="**Acquisition announced** — ACME bought Foo.")

    with patch(
        "tradingagents.scanner.catalyst_explainer._get_explainer_llm",
        return_value=fake_llm,
    ) as mock_get:
        result = explain_catalyst(
            "ACME", facts, provider="openai", model="gpt-5-mini",
            cache_key=f"explainer-test-{uuid.uuid4().hex}",
        )
    mock_get.assert_called_once_with(provider="openai", model="gpt-5-mini")
    assert "Acquisition" in result


@pytest.mark.unit
def test_explain_catalyst_calls_anthropic_path_when_provider_anthropic():
    facts = _facts(category="FDA")
    fake_llm = MagicMock()
    fake_llm.invoke.return_value = MagicMock(content="FDA approval narrative.")

    with patch(
        "tradingagents.scanner.catalyst_explainer._get_explainer_llm",
        return_value=fake_llm,
    ) as mock_get:
        result = explain_catalyst(
            "ACME", facts, provider="anthropic", model="claude-sonnet-4-6",
            cache_key=f"explainer-test-{uuid.uuid4().hex}",
        )
    mock_get.assert_called_once_with(provider="anthropic", model="claude-sonnet-4-6")
    assert "FDA" in result


@pytest.mark.unit
def test_explain_catalyst_returns_empty_on_llm_exception():
    facts = _facts()
    fake_llm = MagicMock()
    fake_llm.invoke.side_effect = RuntimeError("rate limit")

    with patch(
        "tradingagents.scanner.catalyst_explainer._get_explainer_llm",
        return_value=fake_llm,
    ):
        result = explain_catalyst(
            "ACME", facts, provider="openai", model="gpt-5-mini",
            cache_key=f"explainer-test-{uuid.uuid4().hex}",
        )
    assert result == ""


@pytest.mark.unit
def test_explain_catalyst_extracts_string_content_from_message_object():
    facts = _facts()
    fake_msg = MagicMock()
    fake_msg.content = "Plain narrative string."
    fake_llm = MagicMock()
    fake_llm.invoke.return_value = fake_msg

    with patch(
        "tradingagents.scanner.catalyst_explainer._get_explainer_llm",
        return_value=fake_llm,
    ):
        result = explain_catalyst(
            "ACME", facts, provider="openai", model="gpt-5-mini",
            cache_key=f"explainer-test-{uuid.uuid4().hex}",
        )
    assert result == "Plain narrative string."


@pytest.mark.unit
def test_explain_catalyst_handles_anthropic_block_list_content():
    """Anthropic returns content as list[dict] when web_search tool is used."""
    facts = _facts(category="M&A")
    fake_msg = MagicMock()
    fake_msg.content = [
        {"type": "text", "text": "M&A explanation. "},
        {"type": "tool_use", "name": "web_search"},
        {"type": "text", "text": "More context."},
    ]
    fake_llm = MagicMock()
    fake_llm.invoke.return_value = fake_msg

    with patch(
        "tradingagents.scanner.catalyst_explainer._get_explainer_llm",
        return_value=fake_llm,
    ):
        result = explain_catalyst(
            "ACME", facts, provider="anthropic", model="claude-sonnet-4-6",
            cache_key=f"explainer-test-{uuid.uuid4().hex}",
        )
    assert "M&A explanation" in result
    assert "More context" in result
