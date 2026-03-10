"""LLM-powered response classifier using Claude API.

Optional enhancement -- falls back to keyword classifier when no API key.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from loguru import logger

from src.outreach.constants import ALL_CLASSIFICATIONS


@dataclass
class ClassificationResult:
    """Result from LLM classification."""
    classification: str      # POSITIVE, NEGATIVE, NEUTRAL, REFERRAL, AUTO_REPLY
    confidence: float        # 0.0 - 1.0
    reasoning: str           # Short explanation
    suggested_action: str    # Next step recommendation


VALID_CLASSIFICATIONS = set(ALL_CLASSIFICATIONS)

SYSTEM_PROMPT = """You are a LinkedIn outreach response classifier for a job seeker.
Classify the response into exactly one category:
- POSITIVE: Interest in meeting, scheduling a call, or further discussion
- NEGATIVE: Rejection, not hiring, position filled, not a fit
- NEUTRAL: Acknowledgment without clear interest or rejection
- REFERRAL: Suggests contacting someone else or forwarding info
- AUTO_REPLY: Out of office, automatic reply, vacation notice

Respond in this exact format (no markdown, no extra text):
CLASSIFICATION: <one of POSITIVE/NEGATIVE/NEUTRAL/REFERRAL/AUTO_REPLY>
CONFIDENCE: <0.0 to 1.0>
REASONING: <one sentence explanation>
ACTION: <recommended next step>"""


class LLMClassifier:
    """Classify responses using Claude API."""

    def __init__(self, api_key: str | None = None, model: str = "claude-haiku-4-5-20251001"):
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY", "")
        self.model = model
        self._client = None

    def _get_client(self):
        """Lazy-load anthropic client."""
        if self._client is None:
            try:
                import anthropic
                self._client = anthropic.Anthropic(api_key=self.api_key)
            except ImportError:
                logger.warning("anthropic package not installed")
                raise
        return self._client

    def classify(self, response_text: str, company_context: str = "") -> ClassificationResult:
        """Classify using Claude. Synchronous."""
        if not self.api_key:
            raise ValueError("No API key configured for LLM classifier")

        user_msg = f"Response text: {response_text}"
        if company_context:
            user_msg += f"\nCompany context: {company_context}"

        try:
            client = self._get_client()
            message = client.messages.create(
                model=self.model,
                max_tokens=200,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_msg}],
            )

            return self._parse_response(message.content[0].text)
        except Exception as e:
            logger.warning(f"LLM classification failed: {e}")
            raise

    def batch_classify(self, texts: list[str]) -> list[ClassificationResult]:
        """Classify multiple texts sequentially."""
        results = []
        for text in texts:
            try:
                results.append(self.classify(text))
            except Exception as e:
                logger.warning(f"Batch classification failed for text: {e}")
                results.append(ClassificationResult(
                    classification="NEUTRAL",
                    confidence=0.0,
                    reasoning="LLM classification failed",
                    suggested_action="Manual review needed",
                ))
        return results

    def _parse_response(self, raw: str) -> ClassificationResult:
        """Parse the structured LLM response into a ClassificationResult."""
        lines = raw.strip().split("\n")
        classification = "NEUTRAL"
        confidence = 0.5
        reasoning = ""
        action = ""

        for line in lines:
            line = line.strip()
            if line.startswith("CLASSIFICATION:"):
                val = line.split(":", 1)[1].strip().upper()
                if val in VALID_CLASSIFICATIONS:
                    classification = val
            elif line.startswith("CONFIDENCE:"):
                try:
                    confidence = float(line.split(":", 1)[1].strip())
                    confidence = max(0.0, min(1.0, confidence))
                except ValueError:
                    confidence = 0.5
            elif line.startswith("REASONING:"):
                reasoning = line.split(":", 1)[1].strip()
            elif line.startswith("ACTION:"):
                action = line.split(":", 1)[1].strip()

        return ClassificationResult(
            classification=classification,
            confidence=confidence,
            reasoning=reasoning,
            suggested_action=action,
        )


def get_classifier() -> LLMClassifier | None:
    """Factory: returns LLMClassifier if ANTHROPIC_API_KEY set, else None."""
    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if api_key:
        return LLMClassifier(api_key=api_key)
    return None
