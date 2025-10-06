#!/usr/bin/env python3
"""
Telegram bot for answering user questions using OpenAI Assistant and LightRAG.
"""

import logging
import asyncio
from telegram.ext import Application, MessageHandler, CommandHandler, filters

from config import Config
from handlers import MessageHandlers
from services.bot_communication import get_bot_messenger

# Configure detailed logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.DEBUG
)
logger = logging.getLogger(__name__)

class EkaterinaBot:
    """Main bot class."""
    
    def __init__(self):
        """Initialize the bot."""
        try:
            Config.validate()
            logger.info("Configuration validated successfully")
        except ValueError as e:
            logger.error(f"Configuration validation failed: {e}")
            raise

        self.application = Application.builder().token(Config.TELEGRAM_BOT_TOKEN).build()

        # Initialize bot communication service
        self.bot_messenger = get_bot_messenger(use_redis=False)  # Use Redis in production

        # Store original message references for replies
        self.message_references = {}  # chat_id -> {user_id: original_message_id}

        self.setup_handlers()
    
    def setup_handlers(self):
        """Set up message and command handlers."""
        # Initialize message handlers instance with reference to main bot
        self.message_handlers = MessageHandlers(main_bot=self)

        # Command handlers
        self.application.add_handler(
            CommandHandler("start", MessageHandlers.start_command)
        )

        # Message handlers (for all text messages)
        self.application.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, self.message_handlers.handle_message)
        )

        # Error handler
        self.application.add_error_handler(MessageHandlers.error_handler)

        logger.info("Handlers configured successfully")

    async def process_approved_messages(self):
        """
        Process approved messages from admin bot and send them to users.
        This method polls for messages in the communication queue.
        """
        try:
            # Get pending messages from admin bot
            pending_messages = await self.bot_messenger.get_pending_responses("main_bot")

            if not pending_messages:
                logger.debug("📭 No approved messages pending")
                return

            logger.info(f"📥 Processing {len(pending_messages)} approved messages")

            for message in pending_messages:
                try:
                    logger.info(f"🔄 Processing approved message {message.message_id}")
                    logger.info(f"   💬 Target chat: {message.chat_id}")
                    logger.info(f"   👤 Target user: {message.user_id}")
                    logger.info(f"   📄 Text length: {len(message.text)} chars")

                    # Use original_message_id from approved message for reply (works for group chats)
                    original_message_id = message.original_message_id

                    # Detailed logging as requested
                    logger.info(f"📤 Отправка сообщения в чат {message.chat_id}")
                    logger.info(f"📝 Текст: {message.text[:50]}{'...' if len(message.text) > 50 else ''}")
                    logger.info(f"🔗 Original message ID for reply: {original_message_id}")

                    # Send message to user
                    if original_message_id:
                        # Send as reply to original message
                        await self.application.bot.send_message(
                            chat_id=message.chat_id,
                            text=message.text,
                            reply_to_message_id=original_message_id
                        )
                        logger.info(f"✅ Результат отправки: успех (reply)")
                        logger.info(f"✅ Sent approved message {message.message_id} as reply to message {original_message_id}")
                    else:
                        # Send as regular message
                        await self.application.bot.send_message(
                            chat_id=message.chat_id,
                            text=message.text
                        )
                        logger.info(f"✅ Результат отправки: успех (regular)")
                        logger.info(f"✅ Sent approved message {message.message_id} as regular message")

                    # Mark message as successfully sent
                    await self.bot_messenger.mark_message_sent(message.message_id)

                except Exception as send_error:
                    logger.error(f"❌ Результат отправки: ошибка ({send_error})")
                    logger.error(f"❌ Failed to send approved message {message.message_id}: {send_error}")

                    # Mark message as failed (will retry automatically)
                    await self.bot_messenger.mark_message_failed(message.message_id, str(send_error))

        except Exception as e:
            logger.error(f"❌ Error processing approved messages: {e}")

    def store_original_message_reference(self, chat_id: int, user_id: int, message_id: int):
        """
        Store reference to original user message for later reply.

        Args:
            chat_id: Chat ID where message was sent
            user_id: User ID who sent the message
            message_id: Original message ID to reply to
        """
        if chat_id not in self.message_references:
            self.message_references[chat_id] = {}

        self.message_references[chat_id][user_id] = message_id
        logger.debug(f"📝 Stored message reference: chat {chat_id}, user {user_id}, message {message_id}")

    def _get_original_message_id(self, chat_id: int, user_id: int) -> int:
        """
        Get original message ID for reply.

        Args:
            chat_id: Chat ID
            user_id: User ID

        Returns:
            Original message ID if found, None otherwise
        """
        if chat_id in self.message_references:
            return self.message_references[chat_id].get(user_id)
        return None

    def _remove_message_reference(self, chat_id: int, user_id: int):
        """
        Remove message reference after successful delivery.

        Args:
            chat_id: Chat ID
            user_id: User ID
        """
        if chat_id in self.message_references:
            if user_id in self.message_references[chat_id]:
                del self.message_references[chat_id][user_id]
                logger.debug(f"🗑️ Removed message reference: chat {chat_id}, user {user_id}")

                # Clean up empty chat entries
                if not self.message_references[chat_id]:
                    del self.message_references[chat_id]

    async def start_message_processing_loop(self):
        """
        Start the background task for processing approved messages.
        This runs continuously while the bot is active.
        """
        logger.info("🔄 Starting approved message processing loop...")

        while True:
            try:
                await self.process_approved_messages()
                await asyncio.sleep(5)  # Check every 5 seconds
            except asyncio.CancelledError:
                logger.info("⏹️ Message processing loop cancelled")
                break
            except Exception as e:
                logger.error(f"❌ Error in message processing loop: {e}")
                await asyncio.sleep(10)  # Wait longer on error
    
    async def start(self):
        """Start the bot."""
        logger.info("Starting Ekaterina Bot...")
        await self.application.initialize()
        await self.application.start()
        await self.application.updater.start_polling()

        # Initialize message handlers (start priority queue workers)
        await self.message_handlers.initialize()

        # Start the background task for processing approved messages
        processing_task = asyncio.create_task(self.start_message_processing_loop())

        logger.info("Bot is running. Press Ctrl+C to stop.")
        logger.info("🔄 Approved message processing loop started")

        try:
            # Keep the bot running
            await asyncio.Event().wait()
        except KeyboardInterrupt:
            logger.info("Received interrupt signal")
        finally:
            # Cancel the processing task
            processing_task.cancel()
            try:
                await processing_task
            except asyncio.CancelledError:
                pass
            await self.stop()
    
    async def stop(self):
        """Stop the bot."""
        logger.info("Stopping bot...")

        # Stop message handlers (priority queue workers)
        await self.message_handlers.stop_queue()

        await self.application.updater.stop()
        await self.application.stop()
        await self.application.shutdown()
        logger.info("Bot stopped")

async def main():
    """Main function."""
    bot = EkaterinaBot()
    await bot.start()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        raise