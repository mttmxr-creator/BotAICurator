"""
Bot communication service for inter-bot messaging and coordination.
Handles communication between main bot and admin bot using shared storage.
"""

import logging
import json
import time
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any, Union
from dataclasses import dataclass, asdict
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)

@dataclass
class BotMessage:
    """Data class for inter-bot messages."""
    message_id: str
    chat_id: int
    user_id: int
    text: str
    message_type: str  # 'final_response', 'notification', 'command'
    timestamp: datetime
    sender_bot: str  # 'main_bot', 'admin_bot'
    original_message_id: Optional[int] = None  # Telegram message ID to reply to
    status: str = "pending"  # pending, processing, sent, failed
    retry_count: int = 0
    metadata: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        data = asdict(self)
        data['timestamp'] = self.timestamp.isoformat()
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'BotMessage':
        """Create from dictionary with datetime parsing."""
        data['timestamp'] = datetime.fromisoformat(data['timestamp'])
        return cls(**data)

class StorageBackend(ABC):
    """Abstract base class for storage backends."""

    @abstractmethod
    async def store_message(self, message: BotMessage) -> bool:
        """Store a bot message."""
        pass

    @abstractmethod
    async def get_pending_messages(self, bot_name: str) -> List[BotMessage]:
        """Get pending messages for a specific bot."""
        pass

    @abstractmethod
    async def update_message_status(self, message_id: str, status: str) -> bool:
        """Update message status."""
        pass

    @abstractmethod
    async def remove_message(self, message_id: str) -> bool:
        """Remove a message from storage."""
        pass

    @abstractmethod
    async def get_message(self, message_id: str) -> Optional[BotMessage]:
        """Get a specific message by ID."""
        pass

class InMemoryStorage(StorageBackend):
    """In-memory storage backend for development/testing."""

    def __init__(self):
        self.messages: Dict[str, BotMessage] = {}
        logger.info("🧠 InMemoryStorage initialized")

    async def store_message(self, message: BotMessage) -> bool:
        """Store a bot message in memory."""
        try:
            self.messages[message.message_id] = message
            logger.debug(f"💾 Message stored in memory: {message.message_id}")
            return True
        except Exception as e:
            logger.error(f"❌ Error storing message in memory: {e}")
            return False

    async def get_pending_messages(self, bot_name: str) -> List[BotMessage]:
        """Get pending messages for a specific bot."""
        try:
            pending = []
            for message in self.messages.values():
                if message.status == "pending":
                    # For main bot, get messages sent TO it (from admin bot)
                    # For admin bot, get messages sent TO it (from main bot)
                    if ((bot_name == "main_bot" and message.sender_bot == "admin_bot") or
                        (bot_name == "admin_bot" and message.sender_bot == "main_bot")):
                        pending.append(message)

            logger.debug(f"📥 Retrieved {len(pending)} pending messages for {bot_name}")
            return pending
        except Exception as e:
            logger.error(f"❌ Error getting pending messages: {e}")
            return []

    async def update_message_status(self, message_id: str, status: str) -> bool:
        """Update message status."""
        try:
            if message_id in self.messages:
                self.messages[message_id].status = status
                logger.debug(f"🔄 Message status updated: {message_id} → {status}")
                return True
            return False
        except Exception as e:
            logger.error(f"❌ Error updating message status: {e}")
            return False

    async def remove_message(self, message_id: str) -> bool:
        """Remove a message from memory."""
        try:
            if message_id in self.messages:
                del self.messages[message_id]
                logger.debug(f"🗑️ Message removed from memory: {message_id}")
                return True
            return False
        except Exception as e:
            logger.error(f"❌ Error removing message: {e}")
            return False

    async def get_message(self, message_id: str) -> Optional[BotMessage]:
        """Get a specific message by ID."""
        try:
            return self.messages.get(message_id)
        except Exception as e:
            logger.error(f"❌ Error getting message: {e}")
            return None

class RedisStorage(StorageBackend):
    """Redis storage backend for production use."""

    def __init__(self, redis_url: str = "redis://localhost:6379", prefix: str = "bot_comm:"):
        self.redis_url = redis_url
        self.prefix = prefix
        self.redis_client = None
        logger.info(f"🔴 RedisStorage initialized with URL: {redis_url}")

    async def _get_redis(self):
        """Get Redis client (lazy initialization)."""
        if self.redis_client is None:
            try:
                import redis.asyncio as redis
                self.redis_client = redis.from_url(self.redis_url)
                await self.redis_client.ping()
                logger.info("✅ Redis connection established")
            except ImportError:
                logger.error("❌ Redis library not installed. Use: pip install redis")
                raise
            except Exception as e:
                logger.error(f"❌ Redis connection failed: {e}")
                raise
        return self.redis_client

    async def store_message(self, message: BotMessage) -> bool:
        """Store a bot message in Redis."""
        try:
            redis_client = await self._get_redis()
            key = f"{self.prefix}message:{message.message_id}"
            value = json.dumps(message.to_dict())

            await redis_client.set(key, value, ex=3600)  # 1 hour expiry

            # Add to pending queue for target bot
            target_bot = "main_bot" if message.sender_bot == "admin_bot" else "admin_bot"
            queue_key = f"{self.prefix}pending:{target_bot}"
            await redis_client.lpush(queue_key, message.message_id)

            logger.debug(f"💾 Message stored in Redis: {message.message_id}")
            return True
        except Exception as e:
            logger.error(f"❌ Error storing message in Redis: {e}")
            return False

    async def get_pending_messages(self, bot_name: str) -> List[BotMessage]:
        """Get pending messages for a specific bot."""
        try:
            redis_client = await self._get_redis()
            queue_key = f"{self.prefix}pending:{bot_name}"

            # Get all pending message IDs
            message_ids = await redis_client.lrange(queue_key, 0, -1)

            messages = []
            for message_id in message_ids:
                message_id = message_id.decode('utf-8')
                message = await self.get_message(message_id)
                if message and message.status == "pending":
                    messages.append(message)

            logger.debug(f"📥 Retrieved {len(messages)} pending messages for {bot_name}")
            return messages
        except Exception as e:
            logger.error(f"❌ Error getting pending messages from Redis: {e}")
            return []

    async def update_message_status(self, message_id: str, status: str) -> bool:
        """Update message status in Redis."""
        try:
            redis_client = await self._get_redis()
            key = f"{self.prefix}message:{message_id}"

            # Get existing message
            data = await redis_client.get(key)
            if data:
                message_data = json.loads(data.decode('utf-8'))
                message_data['status'] = status

                # Update in Redis
                await redis_client.set(key, json.dumps(message_data), ex=3600)
                logger.debug(f"🔄 Message status updated in Redis: {message_id} → {status}")
                return True
            return False
        except Exception as e:
            logger.error(f"❌ Error updating message status in Redis: {e}")
            return False

    async def remove_message(self, message_id: str) -> bool:
        """Remove a message from Redis."""
        try:
            redis_client = await self._get_redis()
            key = f"{self.prefix}message:{message_id}"

            # Remove from storage
            deleted = await redis_client.delete(key)

            # Remove from all pending queues
            for bot_name in ["main_bot", "admin_bot"]:
                queue_key = f"{self.prefix}pending:{bot_name}"
                await redis_client.lrem(queue_key, 0, message_id)

            logger.debug(f"🗑️ Message removed from Redis: {message_id}")
            return deleted > 0
        except Exception as e:
            logger.error(f"❌ Error removing message from Redis: {e}")
            return False

    async def get_message(self, message_id: str) -> Optional[BotMessage]:
        """Get a specific message by ID from Redis."""
        try:
            redis_client = await self._get_redis()
            key = f"{self.prefix}message:{message_id}"

            data = await redis_client.get(key)
            if data:
                message_data = json.loads(data.decode('utf-8'))
                return BotMessage.from_dict(message_data)
            return None
        except Exception as e:
            logger.error(f"❌ Error getting message from Redis: {e}")
            return None

class BotMessenger:
    """Main bot communication service."""

    def __init__(self, storage_backend: Optional[StorageBackend] = None,
                 use_redis: bool = False, redis_url: str = "redis://localhost:6379"):
        """
        Initialize BotMessenger with storage backend.

        Args:
            storage_backend: Custom storage backend
            use_redis: Whether to use Redis storage
            redis_url: Redis connection URL
        """
        if storage_backend:
            self.storage = storage_backend
        elif use_redis:
            self.storage = RedisStorage(redis_url)
        else:
            self.storage = InMemoryStorage()

        logger.info(f"🤖 BotMessenger initialized with {type(self.storage).__name__}")

    async def send_final_response(self, chat_id: int, user_id: int, text: str,
                                 original_message_id: Optional[int] = None,
                                 metadata: Optional[Dict[str, Any]] = None) -> str:
        """
        Send final response from admin bot to main bot for delivery to user.

        Args:
            chat_id: Target chat ID for message delivery
            user_id: Target user ID
            text: Message text to send
            original_message_id: Telegram message ID to reply to (for group chats)
            metadata: Optional metadata

        Returns:
            Message ID for tracking
        """
        try:
            message_id = str(uuid.uuid4())[:8]  # Short unique ID

            message = BotMessage(
                message_id=message_id,
                chat_id=chat_id,
                user_id=user_id,
                text=text,
                message_type="final_response",
                timestamp=datetime.now(timezone.utc),
                sender_bot="admin_bot",
                original_message_id=original_message_id,
                metadata=metadata or {}
            )

            success = await self.storage.store_message(message)

            if success:
                # Detailed logging as requested
                logger.info(f"📤 Отправка сообщения в чат {chat_id}")
                logger.info(f"📝 Текст: {text[:50]}{'...' if len(text) > 50 else ''}")
                logger.info(f"📤 Final response queued for delivery:")
                logger.info(f"   🆔 Message ID: {message_id}")
                logger.info(f"   👤 User: {user_id}")
                logger.info(f"   💬 Chat: {chat_id}")
                logger.info(f"   📄 Text length: {len(text)} chars")
                logger.info(f"✅ Результат отправки: успех (сообщение добавлено в очередь)")
                return message_id
            else:
                logger.error(f"❌ Результат отправки: ошибка (не удалось добавить в очередь)")
                logger.error(f"❌ Failed to queue final response")
                raise Exception("Failed to store message")

        except Exception as e:
            logger.error(f"❌ Error sending final response: {e}")
            raise

    async def get_pending_responses(self, bot_name: str = "main_bot") -> List[BotMessage]:
        """
        Get pending messages for a bot to process.

        Args:
            bot_name: Name of the bot requesting messages

        Returns:
            List of pending messages
        """
        try:
            messages = await self.storage.get_pending_messages(bot_name)

            if messages:
                logger.info(f"📥 Retrieved {len(messages)} pending messages for {bot_name}")
                for msg in messages:
                    logger.debug(f"   📄 {msg.message_id}: {msg.message_type} → chat {msg.chat_id}")

            return messages
        except Exception as e:
            logger.error(f"❌ Error getting pending responses: {e}")
            return []

    async def mark_message_sent(self, message_id: str) -> bool:
        """
        Mark a message as successfully sent.

        Args:
            message_id: ID of the message that was sent

        Returns:
            True if successfully marked, False otherwise
        """
        try:
            success = await self.storage.update_message_status(message_id, "sent")
            if success:
                logger.info(f"✅ Message marked as sent: {message_id}")
                # Optionally remove sent messages after some time
                await self.storage.remove_message(message_id)
            return success
        except Exception as e:
            logger.error(f"❌ Error marking message as sent: {e}")
            return False

    async def mark_message_failed(self, message_id: str, error: str = None) -> bool:
        """
        Mark a message as failed to send.

        Args:
            message_id: ID of the message that failed
            error: Error description

        Returns:
            True if successfully marked, False otherwise
        """
        try:
            # Get message to increment retry count
            message = await self.storage.get_message(message_id)
            if message:
                message.retry_count += 1
                message.metadata = message.metadata or {}
                message.metadata['last_error'] = error

                # If too many retries, mark as permanently failed
                if message.retry_count >= 3:
                    success = await self.storage.update_message_status(message_id, "failed")
                    logger.warning(f"❌ Message permanently failed after {message.retry_count} retries: {message_id}")
                else:
                    success = await self.storage.update_message_status(message_id, "pending")
                    logger.warning(f"⚠️ Message failed, will retry (attempt {message.retry_count}): {message_id}")

                return success
            return False
        except Exception as e:
            logger.error(f"❌ Error marking message as failed: {e}")
            return False

    async def send_notification(self, target_bot: str, notification_text: str,
                               metadata: Optional[Dict[str, Any]] = None) -> str:
        """
        Send a notification between bots.

        Args:
            target_bot: Target bot name ('main_bot' or 'admin_bot')
            notification_text: Notification message
            metadata: Optional metadata

        Returns:
            Message ID for tracking
        """
        try:
            message_id = str(uuid.uuid4())[:8]

            message = BotMessage(
                message_id=message_id,
                chat_id=0,  # Not applicable for notifications
                user_id=0,  # Not applicable for notifications
                text=notification_text,
                message_type="notification",
                timestamp=datetime.now(timezone.utc),
                sender_bot="admin_bot" if target_bot == "main_bot" else "main_bot",
                metadata=metadata or {}
            )

            success = await self.storage.store_message(message)

            if success:
                logger.info(f"🔔 Notification sent to {target_bot}: {notification_text[:50]}...")
                return message_id
            else:
                raise Exception("Failed to store notification")

        except Exception as e:
            logger.error(f"❌ Error sending notification: {e}")
            raise

    async def cleanup_old_messages(self, max_age_hours: int = 24) -> int:
        """
        Clean up old messages from storage.

        Args:
            max_age_hours: Maximum age in hours for messages to keep

        Returns:
            Number of messages cleaned up
        """
        # This would need to be implemented per storage backend
        # For now, return 0 as cleanup is handled by TTL in Redis
        # and manual cleanup in InMemoryStorage if needed
        logger.debug(f"🧹 Cleanup requested for messages older than {max_age_hours} hours")
        return 0

# Global shared instance
_bot_messenger = None

def get_bot_messenger(use_redis: bool = False, redis_url: str = "redis://localhost:6379") -> BotMessenger:
    """Get the global bot messenger instance."""
    global _bot_messenger
    if _bot_messenger is None:
        _bot_messenger = BotMessenger(use_redis=use_redis, redis_url=redis_url)
    return _bot_messenger