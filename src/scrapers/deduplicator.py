from __future__ import annotations

from thefuzz import fuzz


class Deduplicator:
    """Cross-portal fuzzy company name matching."""

    def is_duplicate(
        self,
        name: str,
        existing_names: list[str],
        threshold: int = 85,
    ) -> tuple[bool, str | None]:
        """Check if a company name is a fuzzy duplicate of any existing name.

        Returns (is_dup, matched_name). If no match, returns (False, None).
        """
        if not name or not existing_names:
            return False, None

        normalized = name.strip().lower()
        # Also create a no-space version for comparing "LlamaIndex" vs "Llama Index"
        normalized_nospace = normalized.replace(" ", "")

        for existing in existing_names:
            existing_norm = existing.strip().lower()
            existing_nospace = existing_norm.replace(" ", "")

            # Exact match (with or without spaces)
            if normalized == existing_norm or normalized_nospace == existing_nospace:
                return True, existing

            # Fuzzy match using token sort ratio (handles word reordering)
            score = fuzz.token_sort_ratio(normalized, existing_norm)
            if score >= threshold:
                return True, existing

            # Also try ratio without spaces for camelCase vs space-separated
            nospace_score = fuzz.ratio(normalized_nospace, existing_nospace)
            if nospace_score >= threshold:
                return True, existing

        return False, None
