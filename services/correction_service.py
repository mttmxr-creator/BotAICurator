"""
OpenAI Correction Assistant service for message corrections.
"""

import logging
import asyncio
from openai import AsyncOpenAI
from typing import Optional

from config import Config

logger = logging.getLogger(__name__)

class CorrectionService:
    """Service for interacting with OpenAI Correction Assistant."""

    def __init__(self):
        """Initialize the Correction service."""
        self.client = AsyncOpenAI(api_key=Config.OPENAI_API_KEY)
        self.correction_assistant_id = Config.CORRECTION_ASSISTANT_ID

        if not self.correction_assistant_id:
            logger.warning("⚠️ CORRECTION_ASSISTANT_ID not configured in environment")

    async def create_thread(self) -> Optional[str]:
        """
        Create a new conversation thread for correction processing.

        Returns:
            Thread ID if successful, None otherwise
        """
        try:
            thread = await self.client.beta.threads.create()
            logger.info(f"✅ Correction thread created: {thread.id}")
            return thread.id
        except Exception as e:
            logger.error(f"❌ Error creating correction thread: {e}")
            return None

    async def send_correction_message(self, thread_id: str, message: str) -> Optional[str]:
        """
        Send a correction message to the assistant and get response.

        Args:
            thread_id: The conversation thread ID
            message: The correction prompt message

        Returns:
            Assistant's corrected response if successful, None otherwise
        """
        try:
            logger.info("📤 SENDING TO CORRECTION ASSISTANT:")
            logger.info(f"   💬 Message length: {len(message)} chars")
            logger.info(f"   📄 Correction prompt preview (first 300 chars):")
            logger.info(f"   {message[:300]}{'...' if len(message) > 300 else ''}")
            logger.info("   " + "="*80)

            # Add message to thread
            await self.client.beta.threads.messages.create(
                thread_id=thread_id,
                role="user",
                content=message
            )

            # Create and run correction assistant
            run = await self.client.beta.threads.runs.create(
                thread_id=thread_id,
                assistant_id=self.correction_assistant_id
            )

            # Wait for completion with polling interval
            logger.info(f"   ⏳ Waiting for correction assistant response (run_id: {run.id})")
            poll_count = 0
            while run.status in ['queued', 'in_progress', 'cancelling']:
                poll_count += 1
                logger.info(f"   💤 Sleep 5 seconds before status check #{poll_count} (current status: {run.status})")
                await asyncio.sleep(5)

                run = await self.client.beta.threads.runs.retrieve(
                    thread_id=thread_id,
                    run_id=run.id
                )
                logger.info(f"   📊 Status check #{poll_count}: {run.status}")

                if run.status == 'completed':
                    logger.info(f"   ✅ Correction assistant completed after {poll_count} checks (~{poll_count * 5} seconds)")
                    break
                elif run.status in ['cancelled', 'expired', 'failed']:
                    logger.error(f"❌ Correction run failed with status: {run.status}")
                    return None

            # Get assistant's response
            messages = await self.client.beta.threads.messages.list(thread_id=thread_id)

            if messages.data:
                # Get the latest assistant message
                for message in messages.data:
                    if message.role == "assistant":
                        if message.content and message.content[0].type == "text":
                            response = message.content[0].text.value

                            logger.info("📥 RECEIVED FROM CORRECTION ASSISTANT:")
                            logger.info(f"   💬 Corrected response length: {len(response)} chars")
                            logger.info(f"   📄 Corrected response preview (first 300 chars):")
                            logger.info(f"   {response[:300]}{'...' if len(response) > 300 else ''}")
                            logger.info("   " + "="*80)

                            return response

            logger.warning("❌ No response from correction assistant")
            return None

        except Exception as e:
            logger.error(f"❌ Error sending message to correction assistant: {e}")
            return None

    async def correct_message(self, original_text: str, correction_request: str) -> Optional[str]:
        """
        Correct a message using the OpenAI Correction Assistant.

        Args:
            original_text: The original AI response text to be corrected
            correction_request: The correction instructions from the moderator

        Returns:
            Corrected text if successful, None otherwise
        """
        if not self.correction_assistant_id:
            logger.error("❌ Correction Assistant not configured (CORRECTION_ASSISTANT_ID missing)")
            return None

        logger.info("🔧 Correction Processing:")
        logger.info(f"   📝 Original text length: {len(original_text)} chars")
        logger.info(f"   📝 Correction request length: {len(correction_request)} chars")
        logger.info(f"   📄 Original text preview (first 200 chars):")
        logger.info(f"   {original_text[:200]}{'...' if len(original_text) > 200 else ''}")
        logger.info(f"   📄 Correction request preview (first 200 chars):")
        logger.info(f"   {correction_request[:200]}{'...' if len(correction_request) > 200 else ''}")
        logger.info(f"   🆔 Correction Assistant ID: {self.correction_assistant_id}")

        # Create a new thread for each correction (stateless approach)
        logger.info("   🧵 Creating new correction thread...")
        thread_id = await self.create_thread()
        if not thread_id:
            logger.error("   ❌ Failed to create correction thread")
            return None

        # Format the correction prompt
        correction_prompt = self._format_correction_prompt(original_text, correction_request)

        logger.info(f"   ✅ Thread created: {thread_id}")
        logger.info(f"   📄 Formatted prompt length: {len(correction_prompt)} chars")

        # Send correction request and get response
        corrected_response = await self.send_correction_message(thread_id, correction_prompt)

        if corrected_response:
            logger.info("🎉 Correction Assistant Final Response:")
            logger.info(f"   📊 Final corrected response length: {len(corrected_response)} chars")
            logger.info(f"   📄 Final corrected response preview (first 300 chars):")
            logger.info(f"   {corrected_response[:300]}{'...' if len(corrected_response) > 300 else ''}")
            if len(corrected_response) > 300:
                logger.info(f"   📄 Final corrected response end (last 200 chars):")
                logger.info(f"   ...{corrected_response[-200:]}")
        else:
            logger.error("   ❌ No corrected response received from Correction Assistant")

        return corrected_response

    def _format_correction_prompt(self, original_text: str, correction_request: str) -> str:
        """
        Format the correction prompt for the OpenAI Correction Assistant.

        Args:
            original_text: The original AI response text
            correction_request: The correction instructions from moderator

        Returns:
            Formatted prompt string
        """
        correction_prompt = f"""Вы получили следующий оригинальный ответ ИИ-ассистента, который необходимо исправить согласно указанным корректировкам.

ОРИГИНАЛЬНЫЙ ОТВЕТ:
{original_text}

КОРРЕКТИРОВКИ ОТ МОДЕРАТОРА:
{correction_request}

ЗАДАЧА:
Пожалуйста, исправьте оригинальный ответ в соответствии с указанными корректировками, сохраняя при этом:
- Естественность и читаемость текста
- Полезность и информативность для пользователя
- Корректный русский язык
- Профессиональный тон

Верните только исправленный текст без дополнительных пояснений или комментариев."""

        logger.debug(f"🔧 Formatted correction prompt ({len(correction_prompt)} chars):")
        logger.debug(f"   First 200 chars: {correction_prompt[:200]}...")

        return correction_prompt