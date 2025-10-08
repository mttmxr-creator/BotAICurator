"""
OpenAI Assistant service for the Telegram bot.
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

class OpenAIService:
    """Service for interacting with OpenAI Assistant."""

    def __init__(self):
        """Initialize the OpenAI service."""
        self.client = AsyncOpenAI(api_key=Config.OPENAI_API_KEY)
        self.assistant_id = Config.OPENAI_ASSISTANT_ID
        self.rate_limiter = RateLimiter(max_requests_per_minute=50)
    
    async def create_thread(self) -> Optional[str]:
        """
        Create a new conversation thread.

        Returns:
            Thread ID if successful, None otherwise
        """
        try:
            thread = await self.rate_limiter.retry_with_exponential_backoff(
                self.client.beta.threads.create
            )
            logger.info(f"Created thread: {thread.id}")
            return thread.id
        except Exception as e:
            logger.error(f"Error creating thread: {e}")
            return None
    
    async def send_message(self, thread_id: str, message: str) -> Optional[str]:
        """
        Send a message to the assistant and get response.
        
        Args:
            thread_id: The conversation thread ID
            message: The user's message
            
        Returns:
            Assistant's response if successful, None otherwise
        """
        try:
            logger.info("📤 SENDING TO OPENAI ASSISTANT:")
            logger.info(f"   💬 Message length: {len(message)} chars")
            logger.info(f"   📄 Full message content:")
            logger.info(f"   {message}")
            logger.info("   " + "="*80)

            # Add message to thread (with rate limiting)
            await self.rate_limiter.retry_with_exponential_backoff(
                self.client.beta.threads.messages.create,
                thread_id=thread_id,
                role="user",
                content=message
            )

            # Create and run assistant (with rate limiting)
            run = await self.rate_limiter.retry_with_exponential_backoff(
                self.client.beta.threads.runs.create,
                thread_id=thread_id,
                assistant_id=self.assistant_id
            )

            # Wait for completion with polling interval
            logger.info(f"   ⏳ Waiting for main assistant response (run_id: {run.id})")
            poll_count = 0
            while run.status in ['queued', 'in_progress', 'cancelling']:
                poll_count += 1
                logger.info(f"   💤 Sleep 5 seconds before status check #{poll_count} (current status: {run.status})")
                await asyncio.sleep(5)

                run = await self.rate_limiter.retry_with_exponential_backoff(
                    self.client.beta.threads.runs.retrieve,
                    thread_id=thread_id,
                    run_id=run.id
                )
                logger.info(f"   📊 Status check #{poll_count}: {run.status}")

                if run.status == 'completed':
                    logger.info(f"   ✅ Main assistant completed after {poll_count} checks (~{poll_count * 5} seconds)")
                    break
                elif run.status in ['cancelled', 'expired', 'failed']:
                    logger.error(f"❌ Run failed with status: {run.status}")
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

                            logger.info("📥 RECEIVED FROM OPENAI ASSISTANT:")
                            logger.info(f"   💬 Response length: {len(response)} chars")
                            logger.info(f"   📄 Full assistant response:")
                            logger.info(f"   {response}")
                            logger.info("   " + "="*80)

                            return response
            
            logger.warning("No response from assistant")
            return None
            
        except Exception as e:
            logger.error(f"Error sending message to assistant: {e}")
            return None
    
    async def process_query(self, user_message: str) -> Optional[str]:
        """
        Process a user query using OpenAI Assistant.
        
        Args:
            user_message: The user's message
            
        Returns:
            Assistant's response if successful, None otherwise
        """
        logger.info("🤖 OpenAI Assistant Processing:")
        logger.info(f"   📝 Input message length: {len(user_message)} chars")
        logger.info(f"   📄 Input message preview (first 500 chars):")
        logger.info(f"   {user_message[:500]}{'...' if len(user_message) > 500 else ''}")
        logger.info(f"   🆔 Assistant ID: {self.assistant_id}")
        
        # Create a new thread for each query (stateless approach)
        logger.info("   🧵 Creating new thread...")
        thread_id = await self.create_thread()
        if not thread_id:
            logger.error("   ❌ Failed to create thread")
            return None
        
        logger.info(f"   ✅ Thread created: {thread_id}")
        response = await self.send_message(thread_id, user_message)
        
        if response:
            logger.info("🎉 OpenAI Assistant Final Response:")
            logger.info(f"   📊 Final response length: {len(response)} chars")
            logger.info(f"   📄 Final response preview (first 500 chars):")
            logger.info(f"   {response[:500]}{'...' if len(response) > 500 else ''}")
            if len(response) > 500:
                logger.info(f"   📄 Final response end (last 300 chars):")
                logger.info(f"   ...{response[-300:]}")
        else:
            logger.error("   ❌ No response received from OpenAI Assistant")
        
        return response