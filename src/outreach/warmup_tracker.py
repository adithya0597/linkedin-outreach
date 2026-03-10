"""Warm-up sequence tracker for LinkedIn outreach pre-engagement.

Tracks the progression of warm-up actions (profile views, likes, comments)
before sending a connection request or message. Implements a state machine:

    PENDING -> WARMING -> READY -> SENT

Each contact goes through warm-up actions before being marked ready for outreach.
"""

from __future__ import annotations

import enum
from datetime import UTC, datetime
from typing import Any

from loguru import logger
from sqlalchemy.orm import Session

from src.db.orm import CompanyORM, WarmUpActionORM, WarmUpSequenceORM

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class WarmUpAction(str, enum.Enum):
    """Individual warm-up actions that can be performed on a contact."""

    PROFILE_VIEW = "PROFILE_VIEW"
    LIKE_POST = "LIKE_POST"
    COMMENT = "COMMENT"
    CONNECT = "CONNECT"
    MESSAGE = "MESSAGE"


class WarmUpState(str, enum.Enum):
    """State of a warm-up sequence for a contact."""

    PENDING = "PENDING"    # No actions taken yet
    WARMING = "WARMING"    # At least 1 action done, not all prerequisites complete
    READY = "READY"        # All warm-up actions done, ready for outreach
    SENT = "SENT"          # Outreach message sent


# ---------------------------------------------------------------------------
# State machine transitions
# ---------------------------------------------------------------------------

VALID_WARMUP_TRANSITIONS: dict[WarmUpState, set[WarmUpState]] = {
    WarmUpState.PENDING: {WarmUpState.WARMING},
    WarmUpState.WARMING: {WarmUpState.READY},
    WarmUpState.READY: {WarmUpState.SENT},
    WarmUpState.SENT: set(),  # Terminal state
}

# Actions required before a contact is considered READY for outreach.
# A contact must have at least one of each of these action types recorded.
REQUIRED_WARMUP_ACTIONS: set[WarmUpAction] = {
    WarmUpAction.PROFILE_VIEW,
    WarmUpAction.LIKE_POST,
}


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class InvalidWarmUpTransitionError(Exception):
    """Raised when attempting an invalid warm-up state transition."""

    pass


# ---------------------------------------------------------------------------
# WarmUpTracker
# ---------------------------------------------------------------------------


class WarmUpTracker:
    """Tracks warm-up engagement sequences for LinkedIn contacts.

    Manages the lifecycle of pre-outreach engagement:
    1. Record individual actions (profile view, like, comment, etc.)
    2. Auto-transition sequence state based on completed actions
    3. Surface contacts that are ready for outreach
    4. Recommend daily warm-up actions
    """

    def __init__(self, session: Session) -> None:
        self.session = session

    # ----- Internal helpers -----

    def _get_or_create_sequence(
        self, company_id: int, contact_name: str
    ) -> WarmUpSequenceORM:
        """Get existing sequence or create a new PENDING one."""
        seq = (
            self.session.query(WarmUpSequenceORM)
            .filter(
                WarmUpSequenceORM.company_id == company_id,
                WarmUpSequenceORM.contact_name == contact_name,
            )
            .first()
        )
        if seq is None:
            seq = WarmUpSequenceORM(
                company_id=company_id,
                contact_name=contact_name,
                state=WarmUpState.PENDING.value,
            )
            self.session.add(seq)
            self.session.flush()
        return seq

    def _get_completed_action_types(
        self, company_id: int, contact_name: str
    ) -> set[WarmUpAction]:
        """Return the set of distinct action types completed for a contact."""
        rows = (
            self.session.query(WarmUpActionORM.action_type)
            .filter(
                WarmUpActionORM.company_id == company_id,
                WarmUpActionORM.contact_name == contact_name,
            )
            .distinct()
            .all()
        )
        result: set[WarmUpAction] = set()
        for (action_type_str,) in rows:
            try:
                result.add(WarmUpAction(action_type_str))
            except ValueError:
                continue
        return result

    def _compute_target_state(
        self, completed: set[WarmUpAction], current_state: WarmUpState
    ) -> WarmUpState:
        """Determine the correct state based on completed actions.

        Rules:
        - No actions -> PENDING
        - Some actions but not all required -> WARMING
        - All required actions done -> READY
        - Already SENT -> stay SENT (terminal)
        """
        if current_state == WarmUpState.SENT:
            return WarmUpState.SENT

        if not completed:
            return WarmUpState.PENDING

        if REQUIRED_WARMUP_ACTIONS.issubset(completed):
            return WarmUpState.READY

        return WarmUpState.WARMING

    def _auto_transition(self, seq: WarmUpSequenceORM, completed: set[WarmUpAction]) -> None:
        """Auto-transition the sequence state based on completed actions."""
        current = WarmUpState(seq.state)
        target = self._compute_target_state(completed, current)

        if target == current:
            return

        # Validate transition path: we may need to skip intermediate states.
        # E.g., if first action completes all requirements, go PENDING -> WARMING -> READY.
        # We walk the transition chain rather than jumping directly.
        path = self._find_transition_path(current, target)
        if path is None:
            logger.warning(
                "No valid transition path from {} to {} for {}",
                current.value,
                target.value,
                seq.contact_name,
            )
            return

        for next_state in path:
            seq.state = next_state.value

        seq.updated_at = datetime.now(UTC)
        logger.debug(
            "Auto-transitioned {} ({}) from {} to {}",
            seq.contact_name,
            seq.company_id,
            current.value,
            target.value,
        )

    @staticmethod
    def _find_transition_path(
        current: WarmUpState, target: WarmUpState
    ) -> list[WarmUpState] | None:
        """Find a valid transition path from current to target state.

        Returns list of intermediate states (excluding current, including target),
        or None if no valid path exists.
        """
        if current == target:
            return []

        # BFS through the transition graph
        visited: set[WarmUpState] = {current}
        queue: list[tuple[WarmUpState, list[WarmUpState]]] = [(current, [])]

        while queue:
            state, path = queue.pop(0)
            for next_state in VALID_WARMUP_TRANSITIONS.get(state, set()):
                if next_state in visited:
                    continue
                new_path = [*path, next_state]
                if next_state == target:
                    return new_path
                visited.add(next_state)
                queue.append((next_state, new_path))

        return None

    def _resolve_company_id(self, company_id: int) -> CompanyORM:
        """Validate that a company exists. Raises ValueError if not found."""
        company = (
            self.session.query(CompanyORM)
            .filter(CompanyORM.id == company_id)
            .first()
        )
        if company is None:
            raise ValueError(f"Company not found with id: {company_id}")
        return company

    # ----- Public API -----

    def record_action(
        self,
        company_id: int,
        contact_name: str,
        action: WarmUpAction,
        notes: str = "",
    ) -> WarmUpActionORM:
        """Record a warm-up action and auto-transition the sequence state.

        Args:
            company_id: FK to CompanyORM.id
            contact_name: Name of the LinkedIn contact
            action: The warm-up action performed
            notes: Optional notes about the action

        Returns:
            The created WarmUpActionORM record.

        Raises:
            ValueError: If the company does not exist.
            InvalidWarmUpTransitionError: If the sequence is in SENT state.
        """
        self._resolve_company_id(company_id)

        # Check if sequence is already SENT
        seq = self._get_or_create_sequence(company_id, contact_name)
        if seq.state == WarmUpState.SENT.value:
            raise InvalidWarmUpTransitionError(
                f"Cannot record actions for '{contact_name}' — sequence already in SENT state."
            )

        # Record the action
        action_record = WarmUpActionORM(
            company_id=company_id,
            contact_name=contact_name,
            action_type=action.value,
            performed_at=datetime.now(UTC),
            notes=notes,
        )
        self.session.add(action_record)
        self.session.flush()

        # Auto-transition state
        completed = self._get_completed_action_types(company_id, contact_name)
        self._auto_transition(seq, completed)

        self.session.commit()
        logger.info(
            "Recorded {} for {} (company_id={}), state={}",
            action.value,
            contact_name,
            company_id,
            seq.state,
        )
        return action_record

    def get_status(self, company_id: int, contact_name: str) -> dict[str, Any]:
        """Return current warm-up state and completed actions for a contact.

        Returns:
            Dict with keys: company_id, contact_name, state, completed_actions,
            remaining_actions, action_count, is_ready.
        """
        seq = (
            self.session.query(WarmUpSequenceORM)
            .filter(
                WarmUpSequenceORM.company_id == company_id,
                WarmUpSequenceORM.contact_name == contact_name,
            )
            .first()
        )

        if seq is None:
            return {
                "company_id": company_id,
                "contact_name": contact_name,
                "state": WarmUpState.PENDING.value,
                "completed_actions": [],
                "remaining_actions": sorted(a.value for a in REQUIRED_WARMUP_ACTIONS),
                "action_count": 0,
                "is_ready": False,
            }

        completed = self._get_completed_action_types(company_id, contact_name)
        remaining = REQUIRED_WARMUP_ACTIONS - completed

        action_count = (
            self.session.query(WarmUpActionORM)
            .filter(
                WarmUpActionORM.company_id == company_id,
                WarmUpActionORM.contact_name == contact_name,
            )
            .count()
        )

        return {
            "company_id": company_id,
            "contact_name": contact_name,
            "state": seq.state,
            "completed_actions": sorted(a.value for a in completed),
            "remaining_actions": sorted(a.value for a in remaining),
            "action_count": action_count,
            "is_ready": seq.state == WarmUpState.READY.value,
        }

    def get_ready_contacts(self) -> list[dict[str, Any]]:
        """Return all contacts in READY state, ready for outreach.

        Returns:
            List of dicts with keys: company_id, company_name, contact_name,
            state, action_count.
        """
        sequences = (
            self.session.query(WarmUpSequenceORM)
            .filter(WarmUpSequenceORM.state == WarmUpState.READY.value)
            .all()
        )

        results: list[dict[str, Any]] = []
        for seq in sequences:
            company = (
                self.session.query(CompanyORM)
                .filter(CompanyORM.id == seq.company_id)
                .first()
            )
            company_name = company.name if company else "Unknown"

            action_count = (
                self.session.query(WarmUpActionORM)
                .filter(
                    WarmUpActionORM.company_id == seq.company_id,
                    WarmUpActionORM.contact_name == seq.contact_name,
                )
                .count()
            )

            results.append({
                "company_id": seq.company_id,
                "company_name": company_name,
                "contact_name": seq.contact_name,
                "state": seq.state,
                "action_count": action_count,
            })

        return results

    def get_daily_actions(self) -> list[dict[str, Any]]:
        """Return today's recommended warm-up actions.

        Logic:
        - For PENDING sequences: recommend PROFILE_VIEW as the first action.
        - For WARMING sequences: recommend the next required action not yet done.
        - READY and SENT sequences produce no recommendations.

        Returns:
            List of dicts with keys: company_id, company_name, contact_name,
            current_state, recommended_action, reason.
        """
        # Get all non-terminal sequences
        sequences = (
            self.session.query(WarmUpSequenceORM)
            .filter(
                WarmUpSequenceORM.state.in_([
                    WarmUpState.PENDING.value,
                    WarmUpState.WARMING.value,
                ])
            )
            .all()
        )

        recommendations: list[dict[str, Any]] = []
        for seq in sequences:
            company = (
                self.session.query(CompanyORM)
                .filter(CompanyORM.id == seq.company_id)
                .first()
            )
            company_name = company.name if company else "Unknown"

            completed = self._get_completed_action_types(seq.company_id, seq.contact_name)
            remaining = REQUIRED_WARMUP_ACTIONS - completed

            if not remaining:
                # All required done but state not yet READY — unusual, skip
                continue

            # Recommend actions in a logical order
            action_priority = [
                WarmUpAction.PROFILE_VIEW,
                WarmUpAction.LIKE_POST,
                WarmUpAction.COMMENT,
            ]
            recommended = None
            for action in action_priority:
                if action in remaining:
                    recommended = action
                    break

            if recommended is None:
                # Fallback to any remaining
                recommended = sorted(remaining, key=lambda a: a.value)[0]

            reason = (
                "First warm-up touch — view their profile"
                if recommended == WarmUpAction.PROFILE_VIEW
                else f"Continue warm-up — {recommended.value.lower().replace('_', ' ')}"
            )

            recommendations.append({
                "company_id": seq.company_id,
                "company_name": company_name,
                "contact_name": seq.contact_name,
                "current_state": seq.state,
                "recommended_action": recommended.value,
                "reason": reason,
            })

        return recommendations

    def mark_sent(self, company_id: int, contact_name: str) -> WarmUpSequenceORM:
        """Transition a READY sequence to SENT.

        Raises:
            ValueError: If the sequence does not exist.
            InvalidWarmUpTransitionError: If the sequence is not in READY state.
        """
        seq = (
            self.session.query(WarmUpSequenceORM)
            .filter(
                WarmUpSequenceORM.company_id == company_id,
                WarmUpSequenceORM.contact_name == contact_name,
            )
            .first()
        )
        if seq is None:
            raise ValueError(
                f"No warm-up sequence found for company_id={company_id}, "
                f"contact='{contact_name}'"
            )

        current = WarmUpState(seq.state)
        if current != WarmUpState.READY:
            raise InvalidWarmUpTransitionError(
                f"Cannot mark as SENT — current state is '{current.value}', "
                f"expected 'READY'."
            )

        seq.state = WarmUpState.SENT.value
        seq.updated_at = datetime.now(UTC)
        self.session.commit()
        logger.info(
            "Marked SENT: {} (company_id={})",
            contact_name,
            company_id,
        )
        return seq
