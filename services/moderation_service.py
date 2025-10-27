"""
Enhanced moderation service with admin notification and inline button functionality.
"""

import logging
import uuid
import json
import os
import sqlite3
import asyncio
import shutil
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Dict, Optional, Any, List
from dataclasses import dataclass, asdict
from pathlib import Path
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from config import Config

logger = logging.getLogger(__name__)

def get_moscow_time() -> str:
    """Get current time in Moscow timezone (MSK)."""
    try:
        moscow_tz = ZoneInfo("Europe/Moscow")
        moscow_time = datetime.now(moscow_tz)
        return moscow_time.strftime("%H:%M MSK")
    except Exception:
        # Fallback to UTC if Moscow timezone not available
        return datetime.utcnow().strftime("%H:%M UTC")

class SmartReminder:
    """Smart reminder system with escalating urgency levels."""

    def __init__(self):
        self.reminder_schedule = {
            1: 3600,    # Первое напоминание через час
            2: 7200,    # Второе через 2 часа после первого
            3: 14400,   # Третье через 4 часа
            4: 28800,   # Четвертое через 8 часов
        }

    def should_send_reminder(self, msg: 'ModerationMessage') -> bool:
        """Check if reminder should be sent based on smart schedule."""
        current_time = time.time()

        # Convert datetime to timestamp for calculations
        timestamp = msg.timestamp.timestamp() if hasattr(msg.timestamp, 'timestamp') else time.mktime(msg.timestamp.timetuple())
        time_in_queue = current_time - timestamp
        reminder_count = getattr(msg, 'reminder_count', 0)

        # Если сообщение редактируется - не напоминаем
        if getattr(msg, 'editing_admin_id', None):
            return False

        # Проверяем по расписанию
        if reminder_count < 4:
            next_reminder_time = self.reminder_schedule.get(reminder_count + 1, 3600)
            last_reminder_timestamp = getattr(msg, 'last_reminder_time', None)
            if last_reminder_timestamp is None:
                last_reminder_timestamp = timestamp

            if current_time - last_reminder_timestamp >= next_reminder_time:
                return True

        return False

    def get_urgency_text(self, reminder_count: int) -> str:
        """Get urgency text based on reminder count."""
        if reminder_count == 1:
            return "📝 Новое сообщение ждет модерации"
        elif reminder_count == 2:
            return "⚠️ Сообщение ждет уже 2+ часа"
        elif reminder_count == 3:
            return "🔴 Срочно! Сообщение ждет более 4 часов"
        else:
            return "🚨 Критично! Сообщение в очереди более 8 часов"

    def format_queue_time(self, time_in_queue: float) -> str:
        """Format time in queue as hours and minutes."""
        hours = int(time_in_queue / 3600)
        minutes = int((time_in_queue % 3600) / 60)
        return f"{hours}ч {minutes}м"

    async def send_smart_reminder(self, msg: 'ModerationMessage', admin_bot) -> bool:
        """Send smart reminder to all available admins."""
        try:
            from config import Config

            # Update reminder tracking
            if not hasattr(msg, 'reminder_count'):
                msg.reminder_count = 0
            msg.reminder_count += 1
            msg.last_reminder_time = time.time()

            # Calculate time in queue
            current_time = time.time()
            timestamp = msg.timestamp.timestamp() if hasattr(msg.timestamp, 'timestamp') else time.mktime(msg.timestamp.timetuple())
            time_in_queue = current_time - timestamp

            # Generate urgency and reminder text
            urgency = self.get_urgency_text(msg.reminder_count)
            queue_time_str = self.format_queue_time(time_in_queue)

            # Format chat title display
            chat_display = f"📱 Чат: {msg.chat_title}\n" if msg.chat_title else ""

            reminder_text = (
                f"{urgency}\n"
                f"🆔 ID: {msg.message_id}\n"
                f"⏳ В очереди: {queue_time_str}\n"
                f"🔄 Напоминание: {msg.reminder_count}/4\n\n"
                f"{chat_display}"
                f"💬 От: {msg.username}\n"
                f"📝 Вопрос: {msg.original_message[:100]}..."
            )

            # Create moderation keyboard
            from telegram import InlineKeyboardButton, InlineKeyboardMarkup
            keyboard = [
                [
                    InlineKeyboardButton("✅ Отправить", callback_data=f"send_{msg.message_id}"),
                    InlineKeyboardButton("❌ Отклонить", callback_data=f"reject_{msg.message_id}"),
                    InlineKeyboardButton("✏️ Редактировать", callback_data=f"edit_{msg.message_id}")
                ],
                [
                    InlineKeyboardButton("📖 Показать полное сообщение", callback_data=f"show_full_{msg.message_id}")
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            # Send to all available admins (exclude editing admin)
            sent_count = 0
            editing_admin_id = getattr(msg, 'editing_admin_id', None)

            for admin_id in Config.ADMIN_CHAT_IDS:
                admin_id_int = int(admin_id)

                # Skip admin who is editing
                if editing_admin_id and str(admin_id) == str(editing_admin_id):
                    continue

                # Check if admin has disabled reminders
                if hasattr(admin_bot, 'disabled_reminders') and admin_id_int in admin_bot.disabled_reminders:
                    continue

                try:
                    sent_message = await admin_bot.application.bot.send_message(
                        chat_id=int(admin_id),
                        text=reminder_text,
                        reply_markup=reply_markup
                    )

                    # Store admin message for synchronization
                    if hasattr(admin_bot, 'store_admin_message'):
                        admin_bot.store_admin_message(msg.message_id, int(admin_id), sent_message.message_id)

                    sent_count += 1

                except Exception as send_error:
                    logger.error(f"❌ Failed to send smart reminder to admin {admin_id}: {send_error}")

            logger.info(f"📨 Sent smart reminder #{msg.reminder_count} for message {msg.message_id} to {sent_count} admins")
            return sent_count > 0

        except Exception as e:
            logger.error(f"❌ Error sending smart reminder: {e}")
            return False

@dataclass
class ModerationMessage:
    """Data class for messages in moderation queue."""
    message_id: str
    chat_id: int
    user_id: int
    username: str
    original_message: str
    ai_response: str
    timestamp: datetime
    chat_title: Optional[str] = None  # Title of the group chat where message came from
    original_message_id: Optional[int] = None  # Telegram message ID to reply to
    status: str = "pending"  # pending, processing, approved, rejected, expired
    rejection_reason: Optional[str] = None
    moderated_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    retry_count: int = 0
    last_notification: Optional[datetime] = None
    admin_processing: Optional[int] = None  # ID админа который взял в работу
    admin_name: Optional[str] = None  # Имя админа для отображения
    editing_admin_id: Optional[int] = None  # ID админа который редактирует
    editing_admin_name: Optional[str] = None  # Имя админа
    editing_started_at: Optional[float] = None  # Время начала редактирования

    # Smart reminder tracking
    reminder_count: int = 0  # Количество отправленных напоминаний
    last_reminder_time: Optional[float] = None  # Время последнего напоминания (timestamp)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        data = asdict(self)
        # Convert datetime objects to ISO format strings
        data['timestamp'] = self.timestamp.isoformat()
        if self.moderated_at:
            data['moderated_at'] = self.moderated_at.isoformat()
        if self.expires_at:
            data['expires_at'] = self.expires_at.isoformat()
        if self.last_notification:
            data['last_notification'] = self.last_notification.isoformat()
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ModerationMessage':
        """Create from dictionary with datetime parsing."""
        # Parse datetime strings back to datetime objects
        data['timestamp'] = datetime.fromisoformat(data['timestamp'])
        if data.get('moderated_at'):
            data['moderated_at'] = datetime.fromisoformat(data['moderated_at'])
        if data.get('expires_at'):
            data['expires_at'] = datetime.fromisoformat(data['expires_at'])
        if data.get('last_notification'):
            data['last_notification'] = datetime.fromisoformat(data['last_notification'])
        # Handle missing fields for backward compatibility
        data.setdefault('retry_count', 0)
        data.setdefault('admin_processing', None)
        data.setdefault('admin_name', None)
        data.setdefault('editing_admin_id', None)
        data.setdefault('editing_admin_name', None)
        data.setdefault('editing_started_at', None)
        data.setdefault('chat_title', None)  # For backward compatibility
        data.setdefault('reminder_count', 0)  # For backward compatibility with SmartReminder
        data.setdefault('last_reminder_time', None)  # For backward compatibility with SmartReminder
        return cls(**data)

    def is_expired(self) -> bool:
        """Check if message has expired."""
        return self.expires_at is not None and datetime.now() > self.expires_at

    def needs_reminder(self, reminder_interval: timedelta = timedelta(hours=1)) -> bool:
        """Check if message needs a reminder notification."""
        if self.last_notification is None:
            return True
        return datetime.now() - self.last_notification > reminder_interval

    def lock_for_editing(self, admin_id: int, admin_name: str) -> None:
        """Блокирует сообщение для редактирования админом."""
        self.admin_processing = admin_id
        self.admin_name = admin_name
        self.status = "processing"

    def unlock_editing(self) -> None:
        """Снимает блокировку редактирования."""
        self.admin_processing = None
        self.admin_name = None
        self.status = "pending"

    def is_locked(self) -> bool:
        """Проверяет заблокировано ли сообщение для редактирования."""
        return self.admin_processing is not None

class ModerationQueue:
    """Enhanced moderation queue with admin notification functionality."""

    def __init__(self, storage_file: str = "moderation_queue.json",
                 use_database: bool = False, db_file: str = "moderation.db",
                 default_timeout_hours: int = 24, reminder_hours: int = 1):
        """Initialize the moderation queue."""
        self.storage_file = storage_file
        self.db_file = db_file
        self.use_database = use_database
        self.default_timeout = timedelta(hours=default_timeout_hours)
        self.reminder_interval = timedelta(hours=reminder_hours)
        self.admin_bot = None  # Will be set when admin bot is available

        # Initialize smart reminder system
        self.smart_reminder = SmartReminder()

        # Initialize storage
        if self.use_database:
            self._init_database()
        self._load_data()

        # Start cleanup task
        self._start_cleanup_task()

        logger.info(f"🗄️ Moderation queue initialized with storage: {storage_file if not use_database else db_file}")

    def set_admin_bot(self, admin_bot):
        """Set the admin bot instance for sending notifications."""
        self.admin_bot = admin_bot
        logger.info("🔗 Admin bot linked to moderation queue")

    def _init_database(self):
        """Initialize SQLite database for persistent storage."""
        try:
            conn = sqlite3.connect(self.db_file)
            cursor = conn.cursor()

            cursor.execute('''
                CREATE TABLE IF NOT EXISTS moderation_messages (
                    message_id TEXT PRIMARY KEY,
                    chat_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    username TEXT NOT NULL,
                    original_message TEXT NOT NULL,
                    ai_response TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    original_message_id INTEGER,
                    status TEXT NOT NULL DEFAULT 'pending',
                    rejection_reason TEXT,
                    moderated_at TEXT,
                    expires_at TEXT,
                    retry_count INTEGER DEFAULT 0,
                    last_notification TEXT,
                    admin_processing INTEGER,
                    admin_name TEXT
                )
            ''')

            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_status ON moderation_messages(status)
            ''')

            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_timestamp ON moderation_messages(timestamp)
            ''')

            conn.commit()
            conn.close()
            logger.info(f"🗄️ Database initialized: {self.db_file}")
        except Exception as e:
            logger.error(f"❌ Failed to initialize database: {e}")
            self.use_database = False

    def _load_data(self):
        """Load moderation data from file or database."""
        if self.use_database:
            self._load_from_database()
        else:
            self._load_from_file()

        # Clean expired messages on startup
        self._cleanup_expired_messages()

    def _load_from_database(self):
        """Load data from SQLite database."""
        try:
            conn = sqlite3.connect(self.db_file)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            cursor.execute('SELECT * FROM moderation_messages')
            rows = cursor.fetchall()

            self.pending_messages = {}
            self.approved_messages = []
            self.rejected_messages = []

            for row in rows:
                msg_data = dict(row)
                msg = ModerationMessage.from_dict(msg_data)

                if msg.status == 'pending':
                    self.pending_messages[msg.message_id] = msg
                elif msg.status == 'approved':
                    self.approved_messages.append(msg)
                elif msg.status in ['rejected', 'expired']:
                    self.rejected_messages.append(msg)

            conn.close()
            logger.info(f"📂 Loaded from database: {len(self.pending_messages)} pending")

        except Exception as e:
            logger.error(f"❌ Failed to load from database: {e}")
            self._initialize_empty_storage()

    def _load_from_file(self):
        """Load moderation data from JSON file."""
        try:
            if os.path.exists(self.storage_file):
                # Create backup before loading
                self._create_backup()

                with open(self.storage_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)

                # Validate data integrity
                if not self._validate_data_integrity(data):
                    logger.warning("⚠️ Data integrity issues found, attempting recovery")
                    data = self._recover_data()

                self.pending_messages = {
                    msg_id: ModerationMessage.from_dict(msg_data)
                    for msg_id, msg_data in data.get('pending_messages', {}).items()
                }
                self.approved_messages = [
                    ModerationMessage.from_dict(msg_data)
                    for msg_data in data.get('approved_messages', [])
                ]
                self.rejected_messages = [
                    ModerationMessage.from_dict(msg_data)
                    for msg_data in data.get('rejected_messages', [])
                ]
                logger.info(f"📂 Loaded moderation data: {len(self.pending_messages)} pending")
            else:
                self._initialize_empty_storage()
        except Exception as e:
            logger.error(f"❌ Failed to load moderation data: {e}")
            self._attempt_recovery_from_backup()

    def _validate_data_integrity(self, data: Dict[str, Any]) -> bool:
        """Validate data structure integrity."""
        try:
            required_keys = ['pending_messages', 'approved_messages', 'rejected_messages']
            if not all(key in data for key in required_keys):
                return False

            # Check if pending_messages is a dict
            if not isinstance(data['pending_messages'], dict):
                return False

            # Check if other lists are actually lists
            if not isinstance(data['approved_messages'], list):
                return False
            if not isinstance(data['rejected_messages'], list):
                return False

            return True
        except Exception:
            return False

    def _create_backup(self):
        """Create backup of current data file."""
        try:
            if os.path.exists(self.storage_file):
                backup_file = f"{self.storage_file}.backup.{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                shutil.copy2(self.storage_file, backup_file)

                # Keep only last 5 backups
                backup_pattern = f"{self.storage_file}.backup.*"
                backup_files = sorted([f for f in os.listdir('.') if f.startswith(f"{os.path.basename(self.storage_file)}.backup.")])
                if len(backup_files) > 5:
                    for old_backup in backup_files[:-5]:
                        try:
                            os.remove(old_backup)
                        except Exception:
                            pass

        except Exception as e:
            logger.warning(f"⚠️ Failed to create backup: {e}")

    def _recover_data(self) -> Dict[str, Any]:
        """Attempt to recover corrupted data."""
        return {
            'pending_messages': {},
            'approved_messages': [],
            'rejected_messages': []
        }

    def _attempt_recovery_from_backup(self):
        """Attempt to recover from backup files."""
        try:
            backup_files = sorted([f for f in os.listdir('.') if f.startswith(f"{os.path.basename(self.storage_file)}.backup.")], reverse=True)

            for backup_file in backup_files[:3]:  # Try last 3 backups
                try:
                    with open(backup_file, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    if self._validate_data_integrity(data):
                        logger.info(f"✅ Recovered from backup: {backup_file}")
                        self.pending_messages = {
                            msg_id: ModerationMessage.from_dict(msg_data)
                            for msg_id, msg_data in data.get('pending_messages', {}).items()
                        }
                        self.approved_messages = [
                            ModerationMessage.from_dict(msg_data)
                            for msg_data in data.get('approved_messages', [])
                        ]
                        self.rejected_messages = [
                            ModerationMessage.from_dict(msg_data)
                            for msg_data in data.get('rejected_messages', [])
                        ]
                        return
                except Exception as e:
                    logger.warning(f"⚠️ Failed to recover from {backup_file}: {e}")
                    continue

        except Exception as e:
            logger.error(f"❌ Recovery attempt failed: {e}")

        # If all recovery attempts fail, initialize empty storage
        self._initialize_empty_storage()

    def _initialize_empty_storage(self):
        """Initialize empty storage."""
        self.pending_messages: Dict[str, ModerationMessage] = {}
        self.approved_messages: list[ModerationMessage] = []
        self.rejected_messages: list[ModerationMessage] = []

    def _save_data(self):
        """Save moderation data to file or database."""
        if self.use_database:
            self._save_to_database()
        else:
            self._save_to_file()

    def _save_to_database(self):
        """Save data to SQLite database."""
        try:
            conn = sqlite3.connect(self.db_file)
            cursor = conn.cursor()

            # Clear existing data
            cursor.execute('DELETE FROM moderation_messages')

            # Insert all messages
            all_messages = list(self.pending_messages.values()) + self.approved_messages + self.rejected_messages

            for msg in all_messages:
                cursor.execute('''
                    INSERT INTO moderation_messages
                    (message_id, chat_id, user_id, username, original_message, ai_response,
                     timestamp, original_message_id, status, rejection_reason, moderated_at, expires_at, retry_count, last_notification, admin_processing, admin_name)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    msg.message_id, msg.chat_id, msg.user_id, msg.username,
                    msg.original_message, msg.ai_response, msg.timestamp.isoformat(),
                    msg.original_message_id, msg.status, msg.rejection_reason,
                    msg.moderated_at.isoformat() if msg.moderated_at else None,
                    msg.expires_at.isoformat() if msg.expires_at else None,
                    msg.retry_count,
                    msg.last_notification.isoformat() if msg.last_notification else None,
                    msg.admin_processing,
                    msg.admin_name
                ))

            conn.commit()
            conn.close()
            logger.debug(f"💾 Moderation data saved to database")

        except Exception as e:
            logger.error(f"❌ Failed to save to database: {e}")

    def _save_to_file(self):
        """Save moderation data to JSON file."""
        try:
            data = {
                'pending_messages': {
                    msg_id: msg.to_dict()
                    for msg_id, msg in self.pending_messages.items()
                },
                'approved_messages': [msg.to_dict() for msg in self.approved_messages],
                'rejected_messages': [msg.to_dict() for msg in self.rejected_messages],
                'metadata': {
                    'last_saved': datetime.now().isoformat(),
                    'version': '2.0',
                    'total_messages': len(self.pending_messages) + len(self.approved_messages) + len(self.rejected_messages)
                }
            }

            # Write to temporary file first, then rename for atomic operation
            temp_file = f"{self.storage_file}.tmp"
            with open(temp_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.rename(temp_file, self.storage_file)

            logger.debug(f"💾 Moderation data saved to {self.storage_file}")
        except Exception as e:
            logger.error(f"❌ Failed to save moderation data: {e}")

    def add_to_queue(self, message_data: Dict[str, Any], timeout_hours: Optional[int] = None) -> str:
        """
        Add a message to the moderation queue.

        Args:
            message_data: Dictionary containing message information
            timeout_hours: Hours until message expires (uses default if None)

        Returns:
            Message ID for tracking
        """
        message_id = str(uuid.uuid4())[:8]  # Short unique ID
        now = datetime.now()
        timeout = timedelta(hours=timeout_hours) if timeout_hours else self.default_timeout

        moderation_message = ModerationMessage(
            message_id=message_id,
            chat_id=message_data['chat_id'],
            user_id=message_data['user_id'],
            username=message_data.get('username', 'Unknown'),
            original_message=message_data['original_message'],
            ai_response=message_data['ai_response'],
            timestamp=now,
            chat_title=message_data.get('chat_title'),
            original_message_id=message_data.get('original_message_id'),
            expires_at=now + timeout
        )

        self.pending_messages[message_id] = moderation_message
        self._save_data()

        logger.info(f"📝 Добавлено в очередь с ID: {message_id}")
        logger.info(f"📝 Added message to moderation queue:")
        logger.info(f"   🆔 ID: {message_id} (type: {type(message_id).__name__})")
        logger.info(f"   👤 User: {moderation_message.username} ({moderation_message.user_id})")
        logger.info(f"   💬 Chat: {moderation_message.chat_id}")
        logger.info(f"   ⏰ Expires: {moderation_message.expires_at.strftime('%Y-%m-%d %H:%M')}")
        logger.info(f"   📄 Original: {moderation_message.original_message[:100]}...")
        logger.info(f"   🤖 Response: {moderation_message.ai_response[:100]}...")

        # Debug logging: show all current message_ids in queue
        all_message_ids = list(self.pending_messages.keys())
        logger.debug(f"🔍 All message_ids in queue after addition ({len(all_message_ids)}): {all_message_ids}")
        logger.debug(f"🔍 Message ID types: {[type(mid).__name__ for mid in all_message_ids]}")

        # Send to admin with buttons
        if Config.has_admin_config():
            import asyncio
            try:
                loop = asyncio.get_event_loop()
                asyncio.create_task(self.send_to_admin(moderation_message, {
                    'queue_size': len(self.pending_messages),
                    'user_info': f"{moderation_message.username} (ID: {moderation_message.user_id})"
                }))
            except Exception as e:
                logger.error(f"❌ Error sending admin notification: {e}")

        return message_id

    def get_from_queue(self, message_id: str) -> Optional[ModerationMessage]:
        """
        Get a message from the queue by ID.

        Args:
            message_id: The message ID to retrieve

        Returns:
            ModerationMessage if found, None otherwise
        """
        # Debug logging for search operations
        all_message_ids = list(self.pending_messages.keys())
        logger.debug(f"🔍 Searching for message_id: '{message_id}' (type: {type(message_id).__name__})")
        logger.debug(f"🔍 Available message_ids in queue ({len(all_message_ids)}): {all_message_ids}")
        logger.debug(f"🔍 Available ID types: {[type(mid).__name__ for mid in all_message_ids]}")

        result = self.pending_messages.get(message_id)

        if result:
            logger.debug(f"✅ Found message {message_id} in queue")
        else:
            logger.warning(f"❌ Message {message_id} NOT found in queue")
            # Additional debugging: check for similar IDs
            similar_ids = [mid for mid in all_message_ids if str(message_id) in str(mid) or str(mid) in str(message_id)]
            if similar_ids:
                logger.warning(f"🔍 Similar message_ids found: {similar_ids}")

        return result

    async def send_to_admin(self, message: ModerationMessage, metadata: Dict[str, Any]) -> bool:
        """
        Send message to admin chat with inline buttons for approval/rejection.

        Args:
            message: The moderation message
            metadata: Additional metadata about the message

        Returns:
            True if sent successfully, False otherwise
        """
        try:
            if not Config.ADMIN_BOT_TOKEN or not Config.ADMIN_CHAT_IDS:
                logger.warning("⚠️ Admin configuration not available for notification")
                return False

            # Format compact admin notification message (like /pending command)
            moscow_time = get_moscow_time()
            username = message.username or "Unknown"
            text_preview = message.original_message[:100] + "..." if len(message.original_message) > 100 else message.original_message
            ai_response_preview = message.ai_response[:100] + "..." if len(message.ai_response) > 100 else message.ai_response

            chat_title = message.chat_title or "Личные сообщения"

            admin_text = (
                f"🔔 Новое сообщение на модерации\n"
                f"📊 В очереди: {metadata.get('queue_size', '?')}\n\n"
                f"🆔 ID: {message.message_id}\n"
                f"📱 Чат: {chat_title}\n"
                f"👤 Пользователь: {username}\n"
                f"⏰ Время: {moscow_time}\n"
                f"💬 Вопрос: {text_preview}\n"
                f"🤖 Ответ: {ai_response_preview}"
            )

            # Create inline keyboard with ALL moderation buttons
            keyboard = [
                [
                    InlineKeyboardButton("✅ Отправить", callback_data=f"send_{message.message_id}"),
                    InlineKeyboardButton("❌ Отклонить", callback_data=f"reject_{message.message_id}")
                ],
                [
                    InlineKeyboardButton("🤖 ИИ-редактирование", callback_data=f"edit_{message.message_id}"),
                    InlineKeyboardButton("✍️ Ручное редактирование", callback_data=f"manual_edit_{message.message_id}")
                ],
                [
                    InlineKeyboardButton("📋 Копировать", callback_data=f"copy_{message.message_id}"),
                    InlineKeyboardButton("📖 Показать полное сообщение", callback_data=f"show_full_{message.message_id}")
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            # Send notification to all admins using the admin bot
            if self.admin_bot and hasattr(self.admin_bot, 'application'):
                # Use asyncio to send the message and track telegram message IDs
                import asyncio
                try:
                    loop = asyncio.get_event_loop()

                    # Create async task to send messages and capture telegram message IDs
                    async def send_and_track_admin_messages():
                        sent_count = 0
                        for admin_id in Config.ADMIN_CHAT_IDS:
                            try:
                                sent_message = await self.admin_bot.application.bot.send_message(
                                    chat_id=int(admin_id),
                                    text=admin_text,
                                    reply_markup=reply_markup
                                )
                                # Store the telegram message ID for tracking
                                self.admin_bot.store_admin_message(
                                    message.message_id,
                                    int(admin_id),
                                    sent_message.message_id
                                )
                                sent_count += 1
                                logger.debug(f"📨 Sent to admin {admin_id}, telegram msg ID: {sent_message.message_id}")
                            except Exception as send_error:
                                logger.error(f"❌ Failed to send to admin {admin_id}: {send_error}")

                        logger.info(f"📨 Admin messages sent and tracked: {sent_count}/{len(Config.ADMIN_CHAT_IDS)}")
                        return sent_count > 0

                    # Execute the task and wait for completion
                    await send_and_track_admin_messages()

                except Exception as e:
                    logger.error(f"❌ Failed to send admin notification: {e}")
                    return False

            logger.info(f"📨 Admin notification sent for message {message.message_id}")
            return True

        except Exception as e:
            logger.error(f"❌ Error sending admin notification: {e}")
            return False

    def approve_message(self, message_id: str) -> Optional[ModerationMessage]:
        """Approve a pending message."""
        # Debug logging before approval
        all_message_ids = list(self.pending_messages.keys())
        logger.debug(f"🔍 Attempting to approve message_id: '{message_id}' (type: {type(message_id).__name__})")
        logger.debug(f"🔍 Available message_ids for approval ({len(all_message_ids)}): {all_message_ids}")

        if message_id in self.pending_messages:
            message = self.pending_messages.pop(message_id)
            message.status = "approved"
            message.moderated_at = datetime.now()
            self.approved_messages.append(message)
            self._save_data()

            logger.info(f"✅ Message approved: {message_id}")
            return message

        logger.warning(f"❌ Message not found for approval: {message_id}")
        # Additional debugging for not found case
        similar_ids = [mid for mid in all_message_ids if str(message_id) in str(mid) or str(mid) in str(message_id)]
        if similar_ids:
            logger.warning(f"🔍 Similar message_ids found during approval: {similar_ids}")
        return None

    def reject_message(self, message_id: str, reason: str = None) -> Optional[ModerationMessage]:
        """Reject a pending message."""
        # Debug logging before rejection
        all_message_ids = list(self.pending_messages.keys())
        logger.debug(f"🔍 Attempting to reject message_id: '{message_id}' (type: {type(message_id).__name__})")
        logger.debug(f"🔍 Available message_ids for rejection ({len(all_message_ids)}): {all_message_ids}")

        if message_id in self.pending_messages:
            message = self.pending_messages.pop(message_id)
            message.status = "rejected"
            message.rejection_reason = reason
            message.moderated_at = datetime.now()
            self.rejected_messages.append(message)
            self._save_data()

            logger.info(f"❌ Message rejected: {message_id}, reason: {reason}")
            return message

        logger.warning(f"❌ Message not found for rejection: {message_id}")
        # Additional debugging for not found case
        similar_ids = [mid for mid in all_message_ids if str(message_id) in str(mid) or str(mid) in str(message_id)]
        if similar_ids:
            logger.warning(f"🔍 Similar message_ids found during rejection: {similar_ids}")
        return None

    def get_pending_count(self) -> int:
        """Get count of pending messages."""
        return len(self.pending_messages)

    def get_pending_messages(self) -> Dict[str, ModerationMessage]:
        """Get all pending messages."""
        return self.pending_messages.copy()

    def _cleanup_expired_messages(self) -> int:
        """Clean up expired messages and return count of cleaned messages."""
        now = datetime.now()
        expired_ids = []

        for msg_id, msg in self.pending_messages.items():
            if msg.is_expired():
                expired_ids.append(msg_id)

        for msg_id in expired_ids:
            msg = self.pending_messages.pop(msg_id)
            msg.status = "expired"
            msg.moderated_at = now
            self.rejected_messages.append(msg)
            logger.info(f"⏰ Message expired: {msg_id}")

        if expired_ids:
            self._save_data()

        return len(expired_ids)

    def _start_cleanup_task(self):
        """Start background task for cleanup and reminders."""
        try:
            loop = asyncio.get_event_loop()
            loop.create_task(self._periodic_cleanup())
        except Exception as e:
            logger.warning(f"⚠️ Could not start cleanup task: {e}")

    async def _periodic_cleanup(self):
        """Periodic cleanup and reminder task."""
        while True:
            try:
                # Clean expired messages
                expired_count = self._cleanup_expired_messages()
                if expired_count > 0:
                    logger.info(f"🧹 Cleaned {expired_count} expired messages")

                # Send reminders for overdue messages
                await self._send_reminders()

                # Sleep for 1 hour
                await asyncio.sleep(3600)

            except Exception as e:
                logger.error(f"❌ Error in periodic cleanup: {e}")
                await asyncio.sleep(60)  # Short sleep on error

    async def _send_reminders(self):
        """Send smart reminder notifications using escalating urgency system."""
        try:
            reminder_count = 0

            for msg in self.pending_messages.values():
                # Use smart reminder system to check if reminder should be sent
                if self.smart_reminder.should_send_reminder(msg):
                    if self.admin_bot and hasattr(self.admin_bot, 'application'):
                        # Send smart reminder
                        success = await self.smart_reminder.send_smart_reminder(msg, self.admin_bot)
                        if success:
                            reminder_count += 1

            if reminder_count > 0:
                self._save_data()
                logger.info(f"🧠 Smart reminder system sent {reminder_count} escalated notifications")
            else:
                logger.debug("🤖 Smart reminder system: no reminders needed at this time")

        except Exception as e:
            logger.error(f"❌ Error in smart reminder system: {e}")

    def get_overdue_messages(self, hours: int = 2) -> List[ModerationMessage]:
        """Get messages that are overdue for more than specified hours."""
        threshold = datetime.now() - timedelta(hours=hours)
        return [
            msg for msg in self.pending_messages.values()
            if msg.timestamp < threshold
        ]

    def get_expiring_soon(self, hours: int = 2) -> List[ModerationMessage]:
        """Get messages that will expire within specified hours."""
        threshold = datetime.now() + timedelta(hours=hours)
        return [
            msg for msg in self.pending_messages.values()
            if msg.expires_at and msg.expires_at < threshold
        ]

    def extend_timeout(self, message_id: str, additional_hours: int = 24) -> bool:
        """Extend timeout for a specific message."""
        if message_id in self.pending_messages:
            msg = self.pending_messages[message_id]
            if msg.expires_at:
                msg.expires_at += timedelta(hours=additional_hours)
                self._save_data()
                logger.info(f"⏰ Extended timeout for {message_id} by {additional_hours} hours")
                return True
        return False

    def get_health_status(self) -> Dict[str, Any]:
        """Get system health status."""
        now = datetime.now()
        overdue = self.get_overdue_messages()
        expiring = self.get_expiring_soon()

        return {
            'storage_type': 'database' if self.use_database else 'file',
            'pending_count': len(self.pending_messages),
            'overdue_count': len(overdue),
            'expiring_soon_count': len(expiring),
            'total_processed': len(self.approved_messages) + len(self.rejected_messages),
            'oldest_pending': min([msg.timestamp for msg in self.pending_messages.values()], default=now),
            'storage_file_exists': os.path.exists(self.storage_file if not self.use_database else self.db_file),
            'admin_bot_connected': self.admin_bot is not None
        }

    def get_statistics(self) -> Dict[str, int]:
        """Get moderation statistics."""
        return {
            'pending': len(self.pending_messages),
            'approved': len(self.approved_messages),
            'rejected': len(self.rejected_messages),
            'overdue': len(self.get_overdue_messages()),
            'expiring_soon': len(self.get_expiring_soon())
        }

    def clear_all_pending(self) -> int:
        """
        Clear all pending messages and remove the queue file.

        Returns:
            Number of pending messages that were cleared
        """
        cleared_count = len(self.pending_messages)

        # Clear the pending messages dictionary
        self.pending_messages.clear()

        # Remove the moderation queue file if it exists
        try:
            if os.path.exists(self.storage_file):
                os.remove(self.storage_file)
                logger.info(f"🗑️ Removed moderation queue file: {self.storage_file}")
            else:
                logger.info(f"📁 Moderation queue file does not exist: {self.storage_file}")
        except Exception as e:
            logger.error(f"❌ Failed to remove moderation queue file: {e}")

        # If using database, clear the database as well
        if self.use_database:
            try:
                conn = sqlite3.connect(self.db_file)
                cursor = conn.cursor()
                cursor.execute('DELETE FROM moderation_messages WHERE status = "pending"')
                conn.commit()
                conn.close()
                logger.info(f"🗑️ Cleared pending messages from database: {self.db_file}")
            except Exception as e:
                logger.error(f"❌ Failed to clear database pending messages: {e}")

        logger.info(f"🧹 Cleared all pending messages: {cleared_count} messages removed")

        return cleared_count

# Global shared instance
_moderation_queue = None

def get_moderation_queue() -> ModerationQueue:
    """Get the global moderation queue instance."""
    global _moderation_queue
    if _moderation_queue is None:
        _moderation_queue = ModerationQueue()
    return _moderation_queue

def add_to_moderation_queue(chat_id: int, user_id: int, username: str,
                           original_message: str, ai_response: str,
                           original_message_id: Optional[int] = None,
                           chat_title: Optional[str] = None) -> str:
    """
    Convenience function to add a message to moderation queue.

    Args:
        chat_id: Chat ID where message was sent
        user_id: User ID who sent the message
        username: Username of the sender
        original_message: Original user message text
        ai_response: AI-generated response
        original_message_id: Telegram message ID to reply to (for group chats)
        chat_title: Title of the group chat where message came from

    Returns:
        Message ID for tracking
    """
    queue = get_moderation_queue()
    message_data = {
        'chat_id': chat_id,
        'user_id': user_id,
        'username': username,
        'original_message': original_message,
        'ai_response': ai_response,
        'original_message_id': original_message_id,
        'chat_title': chat_title
    }
    return queue.add_to_queue(message_data)

# Backward compatibility function
def send_to_moderation(chat_id: int, user_id: int, username: str,
                      original_message: str, ai_response: str) -> str:
    """Backward compatibility wrapper."""
    return add_to_moderation_queue(chat_id, user_id, username, original_message, ai_response)