"""
OpenAI Validation Assistant service for message validation.
"""

import logging
import asyncio
import time
from collections import deque
from typing import Optional
from openai import AsyncOpenAI
from openai import RateLimitError

from config import Config

logger = logging.getLogger(__name__)

class RateLimiter:
    """Rate limiter for OpenAI API requests with exponential backoff retry."""

    def __init__(self, max_requests_per_minute: int = 50):
        self.max_requests_per_minute = max_requests_per_minute
        self.requests = deque()  # Track request timestamps
        self.lock = asyncio.Lock()  # Thread-safe operations

    async def acquire(self):
        """Acquire permission to make a request, with rate limiting."""
        async with self.lock:
            current_time = time.time()

            # Remove requests older than 1 minute
            while self.requests and current_time - self.requests[0] > 60:
                self.requests.popleft()

            # Check if we're approaching the limit
            if len(self.requests) >= self.max_requests_per_minute - 5:  # Buffer of 5 requests
                logger.warning(f"⚠️ Rate limit warning: {len(self.requests)}/{self.max_requests_per_minute} requests in last minute")
                await asyncio.sleep(2)  # Wait 2 seconds when approaching limit

            # Wait if we've hit the limit
            if len(self.requests) >= self.max_requests_per_minute:
                wait_time = 60 - (current_time - self.requests[0])
                if wait_time > 0:
                    logger.warning(f"🛑 Rate limit reached. Waiting {wait_time:.1f} seconds...")
                    await asyncio.sleep(wait_time)
                    # Remove old requests after waiting
                    current_time = time.time()
                    while self.requests and current_time - self.requests[0] > 60:
                        self.requests.popleft()

            # Record this request
            self.requests.append(current_time)
            logger.debug(f"📊 Rate limiter: {len(self.requests)}/{self.max_requests_per_minute} requests in last minute")

    async def retry_with_exponential_backoff(self, func, *args, max_retries: int = 3, **kwargs):
        """Retry a function with exponential backoff on rate limit errors."""
        for attempt in range(max_retries + 1):
            try:
                await self.acquire()  # Apply rate limiting before each attempt
                return await func(*args, **kwargs)
            except RateLimitError as e:
                if attempt == max_retries:
                    logger.error(f"❌ Rate limit error after {max_retries} retries: {e}")
                    raise

                # Exponential backoff: 2^attempt seconds
                wait_time = 2 ** attempt
                logger.warning(f"⏳ Rate limit hit (attempt {attempt + 1}/{max_retries + 1}). Waiting {wait_time}s...")
                await asyncio.sleep(wait_time)
            except Exception as e:
                # Re-raise non-rate-limit errors immediately
                raise

class ValidationService:
    """Service for validating messages using OpenAI Validation Assistant."""

    def __init__(self):
        """Initialize the Validation service."""
        self.client = AsyncOpenAI(api_key=Config.OPENAI_API_KEY)
        self.validation_assistant_id = Config.VALIDATION_ASSISTANT_ID
        self.rate_limiter = RateLimiter(max_requests_per_minute=50)

        if not self.validation_assistant_id:
            logger.warning("⚠️ VALIDATION_ASSISTANT_ID not configured in environment")

    async def create_thread(self) -> Optional[str]:
        """
        Create a new conversation thread for validation processing.

        Returns:
            Thread ID if successful, None otherwise
        """
        try:
            thread = await self.rate_limiter.retry_with_exponential_backoff(
                self.client.beta.threads.create
            )
            logger.debug(f"✅ Validation thread created: {thread.id}")
            return thread.id
        except Exception as e:
            logger.error(f"❌ Error creating validation thread: {e}")
            return None

    async def send_validation_message(self, thread_id: str, message: str) -> Optional[str]:
        """
        Send a validation message to the assistant and get response.

        Args:
            thread_id: The conversation thread ID
            message: The validation prompt message

        Returns:
            Assistant's validation response if successful, None otherwise
        """
        try:
            logger.debug("📤 SENDING TO VALIDATION ASSISTANT:")
            logger.debug(f"   💬 Message length: {len(message)} chars")
            logger.debug(f"   📄 Validation prompt preview (first 200 chars):")
            logger.debug(f"   {message[:200]}{'...' if len(message) > 200 else ''}")

            # Add message to thread (with rate limiting)
            await self.rate_limiter.retry_with_exponential_backoff(
                self.client.beta.threads.messages.create,
                thread_id=thread_id,
                role="user",
                content=message
            )

            # Create and run validation assistant (with rate limiting)
            run = await self.rate_limiter.retry_with_exponential_backoff(
                self.client.beta.threads.runs.create,
                thread_id=thread_id,
                assistant_id=self.validation_assistant_id
            )

            # Wait for completion
            while run.status in ['queued', 'in_progress', 'cancelling']:
                run = await self.rate_limiter.retry_with_exponential_backoff(
                    self.client.beta.threads.runs.retrieve,
                    thread_id=thread_id,
                    run_id=run.id
                )

                if run.status == 'completed':
                    break
                elif run.status in ['cancelled', 'expired', 'failed']:
                    logger.error(f"❌ Validation run failed with status: {run.status}")
                    return None

            # Get assistant's response (with rate limiting)
            messages = await self.rate_limiter.retry_with_exponential_backoff(
                self.client.beta.threads.messages.list,
                thread_id=thread_id
            )

            if messages.data:
                # Get the latest assistant message
                for message in messages.data:
                    if message.role == "assistant":
                        if message.content and message.content[0].type == "text":
                            response = message.content[0].text.value

                            logger.debug("📥 RECEIVED FROM VALIDATION ASSISTANT:")
                            logger.debug(f"   💬 Validation response: {response}")

                            return response

            logger.warning("❌ No response from validation assistant")
            return None

        except Exception as e:
            logger.error(f"❌ Error sending message to validation assistant: {e}")
            return None

    async def validate_message(self, message: str) -> bool:
        """
        Validate if a message is a work-related question for the knowledge base.

        Args:
            message: The message to validate

        Returns:
            True if the message is a valid work-related question, False otherwise
        """
        if not self.validation_assistant_id:
            logger.error("❌ Validation Assistant not configured (VALIDATION_ASSISTANT_ID missing)")
            # Default to True if validation service is not configured
            logger.info("🔄 Defaulting to True - allowing message through")
            return True

        logger.info("🔍 Message Validation Processing:")
        logger.info(f"   📝 Message length: {len(message)} chars")
        logger.info(f"   📄 Message preview (first 200 chars):")
        logger.info(f"   {message[:200]}{'...' if len(message) > 200 else ''}")
        logger.info(f"   🆔 Validation Assistant ID: {self.validation_assistant_id}")

        # Create a new thread for each validation (stateless approach)
        logger.debug("   🧵 Creating new validation thread...")
        thread_id = await self.create_thread()
        if not thread_id:
            logger.error("   ❌ Failed to create validation thread")
            # Default to True if thread creation fails
            logger.info("🔄 Defaulting to True due to thread creation failure")
            return True

        # Format the validation prompt
        validation_prompt = self._format_validation_prompt(message)

        logger.debug(f"   ✅ Thread created: {thread_id}")
        logger.debug(f"   📄 Formatted prompt length: {len(validation_prompt)} chars")

        # Send validation request and get response
        validation_response = await self.send_validation_message(thread_id, validation_prompt)

        if validation_response:
            # Parse the response for YES/NO
            result = self._parse_validation_response(validation_response)

            logger.info("🎉 Validation Assistant Final Response:")
            logger.info(f"   📊 Validation response: {validation_response.strip()}")
            logger.info(f"   ✅ Validation result: {'VALID' if result else 'INVALID'}")

            return result
        else:
            logger.error("   ❌ No validation response received from Validation Assistant")
            # Default to True if no response received
            logger.info("🔄 Defaulting to True due to no response")
            return True

    def _format_validation_prompt(self, message: str) -> str:
        """
        Format the validation prompt for the OpenAI Validation Assistant.

        Args:
            message: The message to validate

        Returns:
            Formatted prompt string
        """
        validation_prompt = f"""Сообщение: {message}

Является ли это рабочим вопросом для базы знаний? Ответь только YES или NO"""

        logger.debug(f"🔍 Formatted validation prompt ({len(validation_prompt)} chars):")
        logger.debug(f"   Content: {validation_prompt}")

        return validation_prompt

    def _parse_validation_response(self, response: str) -> bool:
        """
        Parse the validation response from the assistant.

        Args:
            response: The assistant's response

        Returns:
            True if response indicates valid work question (YES), False if not (NO)
        """
        # Clean and normalize the response
        cleaned_response = response.strip().upper()

        logger.debug(f"🔍 Parsing validation response:")
        logger.debug(f"   Original: '{response}'")
        logger.debug(f"   Cleaned: '{cleaned_response}'")

        # Check for YES response
        if "YES" in cleaned_response:
            logger.debug("   ✅ Found YES - message is valid")
            return True
        # Check for NO response
        elif "NO" in cleaned_response:
            logger.debug("   ❌ Found NO - message is invalid")
            return False
        else:
            # If response is unclear, log warning and default to True
            logger.warning(f"⚠️ Unclear validation response: '{response}' - defaulting to True")
            return True


# Global service instance
_validation_service = None

def get_validation_service() -> ValidationService:
    """
    Get the global ValidationService instance.

    Returns:
        ValidationService instance
    """
    global _validation_service
    if _validation_service is None:
        _validation_service = ValidationService()
    return _validation_service