"""
Message Filter service for comprehensive message validation.
Implements multi-stage filtering to optimize processing pipeline.
"""

import logging
from typing import Dict, Any
from dataclasses import dataclass

from services.validation_service import get_validation_service
from services.lightrag_service import LightRAGService

logger = logging.getLogger(__name__)

@dataclass
class FilterResult:
    """Result of message filtering process."""
    should_process: bool
    stage_failed: str
    reason: str
    details: Dict[str, Any]

class MessageFilter:
    """
    Multi-stage message filter for optimizing processing pipeline.

    Implements two-stage filtering:
    1. Length validation (minimum 10 characters)
    2. Work-related validation (ValidationService via OpenAI)

    Note: Stage 3 (LightRAG relevance check) has been disabled as redundant.
    """

    # Configuration
    MIN_MESSAGE_LENGTH = 10

    def __init__(self):
        """Initialize the MessageFilter with required services."""
        self.validation_service = get_validation_service()
        # LightRAG service no longer needed for filtering (Stage 3 disabled)
        # self.lightrag_service = LightRAGService()

        logger.info("🔄 MessageFilter initialized with two-stage filtering (Stage 3 disabled)")

    async def should_process(self, message: str, user_id: int, chat_id: int) -> bool:
        """
        Determine if a message should be processed through the RAG pipeline.

        Implements two-stage filtering:
        1. Length check (minimum 10 characters)
        2. ValidationService check (work-related validation via OpenAI)

        Args:
            message: The user's message
            user_id: Telegram user ID
            chat_id: Telegram chat ID

        Returns:
            True if message should be processed, False otherwise
        """
        logger.info("🚪 Message Filter - Two-Stage Analysis:")
        logger.info(f"   👤 User: {user_id}, Chat: {chat_id}")
        logger.info(f"   📝 Message: {message[:100]}{'...' if len(message) > 100 else ''}")

        # Stage 1: Length Validation
        logger.info("   🔍 Stage 1: Length Validation")
        if not self._check_message_length(message):
            logger.info(f"   ❌ REJECTED at Stage 1: Message too short ({len(message)} < {self.MIN_MESSAGE_LENGTH} chars)")
            return False

        logger.info(f"   ✅ Stage 1 PASSED: Length OK ({len(message)} chars)")

        # Stage 2: Work-Related Validation
        logger.info("   🔍 Stage 2: Work-Related Validation")
        try:
            is_work_related = await self.validation_service.validate_message(message)
            if not is_work_related:
                logger.info("   ❌ REJECTED at Stage 2: Message is not work-related")
                return False

            logger.info("   ✅ Stage 2 PASSED: Message is work-related")
        except Exception as e:
            logger.error(f"   ⚠️ Stage 2 ERROR: {e} - Allowing message to proceed")
            # On validation error, allow message through (fail-safe approach)

        # Stage 3: Knowledge Base Relevance - DISABLED
        # Stage 3 removed - ValidationService (Stage 2) is sufficient for relevance checking
        # LightRAG check was causing timeouts and is redundant with AI validation
        logger.info("   ℹ️ Stage 3: Skipped (disabled - Stage 2 validation is sufficient)")

        # All stages passed
        logger.info("   🎉 STAGES 1-2 PASSED - Message approved for RAG processing")
        return True

    async def get_detailed_filter_result(self, message: str, user_id: int, chat_id: int) -> FilterResult:
        """
        Get detailed filtering results for analysis and debugging.

        Args:
            message: The user's message
            user_id: Telegram user ID
            chat_id: Telegram chat ID

        Returns:
            FilterResult with detailed information about filtering decision
        """
        logger.debug("🔬 Detailed Filter Analysis:")
        logger.debug(f"   👤 User: {user_id}, Chat: {chat_id}")

        # Stage 1: Length Validation
        if not self._check_message_length(message):
            return FilterResult(
                should_process=False,
                stage_failed="length_check",
                reason=f"Message too short: {len(message)} < {self.MIN_MESSAGE_LENGTH} characters",
                details={
                    "message_length": len(message),
                    "min_required": self.MIN_MESSAGE_LENGTH,
                    "user_id": user_id,
                    "chat_id": chat_id
                }
            )

        # Stage 2: Work-Related Validation
        try:
            is_work_related = await self.validation_service.validate_message(message)
            if not is_work_related:
                return FilterResult(
                    should_process=False,
                    stage_failed="work_validation",
                    reason="Message is not work-related",
                    details={
                        "validation_result": False,
                        "user_id": user_id,
                        "chat_id": chat_id,
                        "message_length": len(message)
                    }
                )
        except Exception as e:
            logger.warning(f"Validation service error: {e}")
            # Continue to next stage on error

        # Stage 3: Knowledge Base Relevance - DISABLED
        # Stage 3 removed - ValidationService (Stage 2) is sufficient for relevance checking
        # LightRAG check was causing timeouts and is redundant with AI validation

        # All stages passed
        return FilterResult(
            should_process=True,
            stage_failed="none",
            reason="All validation stages passed (Stage 1-2)",
            details={
                "all_stages_passed": True,
                "user_id": user_id,
                "chat_id": chat_id,
                "message_length": len(message)
            }
        )

    def _check_message_length(self, message: str) -> bool:
        """
        Check if message meets minimum length requirement.

        Args:
            message: The message to check

        Returns:
            True if message is long enough, False otherwise
        """
        if not message:
            return False

        # Remove excessive whitespace and check actual content length
        cleaned_message = message.strip()
        return len(cleaned_message) >= self.MIN_MESSAGE_LENGTH

    def get_filter_stats(self) -> Dict[str, Any]:
        """
        Get statistics about the filtering configuration.

        Returns:
            Dictionary with filter configuration and capabilities
        """
        return {
            "min_message_length": self.MIN_MESSAGE_LENGTH,
            "validation_service_available": hasattr(self, 'validation_service'),
            "lightrag_service_available": False,  # Stage 3 disabled
            "filtering_stages": [
                "length_check",
                "work_validation"
                # "relevance_check" - DISABLED
            ],
            "fail_safe_mode": True,  # Allows messages through on service errors
            "stage_3_disabled": True,
            "stage_3_disabled_reason": "Redundant with Stage 2 OpenAI validation, caused timeouts"
        }

    def should_skip_validation(self, user_id: int) -> bool:
        """
        Check if validation should be skipped for specific users (e.g., admins).

        Args:
            user_id: Telegram user ID

        Returns:
            True if validation should be skipped, False otherwise
        """
        # This could be expanded to check admin user IDs from config
        # For now, no special users skip validation
        return False

    async def get_rejection_message(self, filter_result: FilterResult) -> str:
        """
        Generate appropriate user-facing message for rejection.

        Args:
            filter_result: The result from filtering

        Returns:
            Empty string (no user message sent for rejections)
        """
        # No user messages sent for any type of rejection
        return ""


# Global service instance
_message_filter = None

def get_message_filter() -> MessageFilter:
    """
    Get the global MessageFilter instance.

    Returns:
        MessageFilter instance
    """
    global _message_filter
    if _message_filter is None:
        _message_filter = MessageFilter()
    return _message_filter