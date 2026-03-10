"""Tests for LLM-powered response classifier.

All tests mock the Anthropic API -- no real API calls are made.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.outreach.llm_classifier import (
    VALID_CLASSIFICATIONS,
    ClassificationResult,
    LLMClassifier,
    get_classifier,
)

# ---- Test 1: ClassificationResult dataclass creation ----

def test_classification_result_dataclass():
    result = ClassificationResult(
        classification="POSITIVE",
        confidence=0.95,
        reasoning="Expressed interest in meeting",
        suggested_action="Schedule call",
    )
    assert result.classification == "POSITIVE"
    assert result.confidence == 0.95
    assert result.reasoning == "Expressed interest in meeting"
    assert result.suggested_action == "Schedule call"


# ---- Test 2: _parse_response with well-formed response ----

def test_parse_response_well_formed():
    classifier = LLMClassifier(api_key="test-key")
    raw = (
        "CLASSIFICATION: POSITIVE\n"
        "CONFIDENCE: 0.92\n"
        "REASONING: The response shows clear interest in scheduling a call\n"
        "ACTION: Schedule a follow-up meeting"
    )
    result = classifier._parse_response(raw)
    assert result.classification == "POSITIVE"
    assert result.confidence == 0.92
    assert "interest" in result.reasoning.lower()
    assert "follow-up" in result.suggested_action.lower()


# ---- Test 3: _parse_response with malformed response (defaults to NEUTRAL) ----

def test_parse_response_malformed_defaults_neutral():
    classifier = LLMClassifier(api_key="test-key")
    raw = "This is not a structured response at all."
    result = classifier._parse_response(raw)
    assert result.classification == "NEUTRAL"
    assert result.confidence == 0.5
    assert result.reasoning == ""
    assert result.suggested_action == ""


# ---- Test 4: _parse_response with missing fields ----

def test_parse_response_missing_fields():
    classifier = LLMClassifier(api_key="test-key")
    raw = "CLASSIFICATION: NEGATIVE\nCONFIDENCE: 0.8"
    result = classifier._parse_response(raw)
    assert result.classification == "NEGATIVE"
    assert result.confidence == 0.8
    assert result.reasoning == ""
    assert result.suggested_action == ""


# ---- Test 5: _parse_response with invalid classification name ----

def test_parse_response_invalid_classification():
    classifier = LLMClassifier(api_key="test-key")
    raw = (
        "CLASSIFICATION: MAYBE_POSITIVE\n"
        "CONFIDENCE: 0.6\n"
        "REASONING: Unclear\n"
        "ACTION: Wait"
    )
    result = classifier._parse_response(raw)
    # Invalid classification falls back to NEUTRAL default
    assert result.classification == "NEUTRAL"
    assert result.confidence == 0.6


# ---- Test 6: _parse_response confidence clamped to [0, 1] ----

def test_parse_response_confidence_clamped():
    classifier = LLMClassifier(api_key="test-key")

    # Over 1.0
    raw_high = "CLASSIFICATION: POSITIVE\nCONFIDENCE: 1.5"
    result_high = classifier._parse_response(raw_high)
    assert result_high.confidence == 1.0

    # Below 0.0
    raw_low = "CLASSIFICATION: POSITIVE\nCONFIDENCE: -0.3"
    result_low = classifier._parse_response(raw_low)
    assert result_low.confidence == 0.0


# ---- Test 7: get_classifier returns None without API key ----

def test_get_classifier_returns_none_without_key():
    env_without_key = {k: v for k, v in __import__("os").environ.items() if k != "ANTHROPIC_API_KEY"}
    with patch.dict("os.environ", env_without_key, clear=True):
        result = get_classifier()
        assert result is None


# ---- Test 8: get_classifier returns LLMClassifier with API key ----

def test_get_classifier_returns_classifier_with_key():
    with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-test-123"}):
        result = get_classifier()
        assert result is not None
        assert isinstance(result, LLMClassifier)
        assert result.api_key == "sk-test-123"


# ---- Test 9: classify raises ValueError without API key ----

def test_classify_raises_without_api_key():
    classifier = LLMClassifier(api_key="")
    with pytest.raises(ValueError, match="No API key"):
        classifier.classify("Hello there")


# ---- Test 10: batch_classify returns NEUTRAL on failure with confidence 0.0 ----

def test_batch_classify_returns_neutral_on_failure():
    classifier = LLMClassifier(api_key="")  # No key -> classify will raise
    results = classifier.batch_classify(["Hello", "World"])
    assert len(results) == 2
    for r in results:
        assert r.classification == "NEUTRAL"
        assert r.confidence == 0.0
        assert r.reasoning == "LLM classification failed"
        assert r.suggested_action == "Manual review needed"


# ---- Test 11: classify with mocked anthropic client returns correct result ----

def test_classify_with_mocked_client():
    classifier = LLMClassifier(api_key="sk-test-123")

    # Mock the anthropic client
    mock_client = MagicMock()
    mock_message = MagicMock()
    mock_content_block = MagicMock()
    mock_content_block.text = (
        "CLASSIFICATION: REFERRAL\n"
        "CONFIDENCE: 0.88\n"
        "REASONING: The person suggests contacting their colleague\n"
        "ACTION: Reach out to the referred person"
    )
    mock_message.content = [mock_content_block]
    mock_client.messages.create.return_value = mock_message

    classifier._client = mock_client

    result = classifier.classify("You should talk to our CTO about this")
    assert result.classification == "REFERRAL"
    assert result.confidence == 0.88
    assert "colleague" in result.reasoning
    assert "referred" in result.suggested_action.lower()

    # Verify the API was called with correct params
    mock_client.messages.create.assert_called_once()
    call_kwargs = mock_client.messages.create.call_args
    assert call_kwargs.kwargs["model"] == "claude-haiku-4-5-20251001"
    assert call_kwargs.kwargs["max_tokens"] == 200


# ---- Test 12: classify with company context included in prompt ----

def test_classify_includes_company_context():
    classifier = LLMClassifier(api_key="sk-test-123")

    mock_client = MagicMock()
    mock_message = MagicMock()
    mock_content_block = MagicMock()
    mock_content_block.text = (
        "CLASSIFICATION: POSITIVE\n"
        "CONFIDENCE: 0.9\n"
        "REASONING: Interest expressed\n"
        "ACTION: Schedule call"
    )
    mock_message.content = [mock_content_block]
    mock_client.messages.create.return_value = mock_message
    classifier._client = mock_client

    classifier.classify("Sounds great!", company_context="Tier 1 AI startup")

    call_kwargs = mock_client.messages.create.call_args
    user_msg = call_kwargs.kwargs["messages"][0]["content"]
    assert "Tier 1 AI startup" in user_msg
    assert "Sounds great!" in user_msg


# ---- Test 13: VALID_CLASSIFICATIONS contains all expected values ----

def test_valid_classifications_complete():
    expected = {"POSITIVE", "NEGATIVE", "NEUTRAL", "REFERRAL", "AUTO_REPLY"}
    assert expected == VALID_CLASSIFICATIONS


# ---- Test 14: _parse_response handles non-numeric confidence gracefully ----

def test_parse_response_non_numeric_confidence():
    classifier = LLMClassifier(api_key="test-key")
    raw = "CLASSIFICATION: POSITIVE\nCONFIDENCE: high"
    result = classifier._parse_response(raw)
    assert result.classification == "POSITIVE"
    assert result.confidence == 0.5  # Default fallback
