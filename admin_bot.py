#!/usr/bin/env python3
"""
Admin Telegram bot for moderation and administrative functions.
"""

import logging
import asyncio
import time
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Dict, List, Optional
from telegram.ext import Application, MessageHandler, CommandHandler, CallbackQueryHandler, filters
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from openai import AsyncOpenAI
import re

from config import Config
from services.moderation_service import get_moderation_queue, ModerationQueue
from services.correction_service import CorrectionService
from services.whisper_service import get_whisper_service

def escape_markdown_v2(text: str) -> str:
    """
    Escape special characters for Telegram MarkdownV2.

    MarkdownV2 requires escaping these characters:
    _ * [ ] ( ) ~ ` > # + - = | { } . !
    """
    if not text:
        return ""

    # List of characters that need to be escaped in MarkdownV2
    escape_chars = r'_*[]()~`>#+-=|{}.!'

    # Escape each special character with backslash
    return re.sub(f'([{re.escape(escape_chars)}])', r'\\\1', str(text))

def get_moscow_time() -> str:
    """Get current time in Moscow timezone (MSK)."""
    try:
        moscow_tz = ZoneInfo("Europe/Moscow")
        moscow_time = datetime.now(moscow_tz)
        return moscow_time.strftime("%H:%M MSK")
    except Exception:
        # Fallback to UTC if Moscow timezone not available
        return datetime.utcnow().strftime("%H:%M UTC")

# Configure detailed logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.DEBUG
)
logger = logging.getLogger(__name__)

class AdminHandlers:
    """Admin message and command handlers."""

    def __init__(self, moderation_queue: ModerationQueue, bot_application, admin_bot=None):
        """Initialize admin handlers."""
        self.moderation_queue = moderation_queue
        self.bot_application = bot_application
        self.admin_bot = admin_bot  # Reference to AdminBot for multi-admin synchronization

        # State management for corrections
        self.correction_states: Dict[int, Dict] = {}  # user_id -> {message_id, step}

        # OpenAI client for Whisper transcription
        self.openai_client = AsyncOpenAI(api_key=Config.OPENAI_API_KEY) if Config.OPENAI_API_KEY else None

        # Correction service for message corrections
        self.correction_service = CorrectionService()

        # Whisper service for voice message transcription
        self.whisper_service = get_whisper_service()

        logger.info("🔧 Admin handlers initialized")

    def create_moderation_keyboard(self, message_id: str) -> InlineKeyboardMarkup:
        """
        Create inline keyboard for moderation actions.

        Args:
            message_id: The message ID for callback data

        Returns:
            InlineKeyboardMarkup with moderation buttons
        """
        keyboard = [
            [
                InlineKeyboardButton("✅ Отправить", callback_data=f"send_{message_id}"),
                InlineKeyboardButton("❌ Отклонить", callback_data=f"reject_{message_id}")
            ],
            [
                InlineKeyboardButton("🤖 ИИ-редактирование", callback_data=f"edit_{message_id}"),
                InlineKeyboardButton("✍️ Ручное редактирование", callback_data=f"manual_edit_{message_id}")
            ],
            [
                InlineKeyboardButton("📋 Копировать", callback_data=f"copy_{message_id}"),
                InlineKeyboardButton("📖 Показать полное сообщение", callback_data=f"show_full_{message_id}")
            ]
        ]
        return InlineKeyboardMarkup(keyboard)

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle the /start command for admin bot."""
        admin_welcome = (
            "🔧 Админ-бот Екатерина активирован!\n\n"
            "Доступные команды:\n"
            "/pending - список ожидающих сообщений\n"
            "/stats - статистика модерации\n"
            "/clear - очистить очередь модерации\n"
            "/notification_off - отключить напоминания\n"
            "/notification_on - включить напоминания"
        )

        try:
            await update.message.reply_text(admin_welcome)
            logger.info(f"🚀 Admin start command handled for user {update.message.from_user.id}")
        except Exception as e:
            logger.error(f"❌ Error handling admin start command: {e}")

    async def status_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show detailed moderation statistics."""
        try:
            # Check if user is authorized admin
            if not Config.is_admin(update.effective_user.id):
                await update.message.reply_text("🚫 У вас нет прав администратора")
                return

            # Gather comprehensive statistics
            stats = self.moderation_queue.get_statistics()
            pending_messages = self.moderation_queue.get_pending_messages()

            # Basic counts
            pending_count = stats['pending']
            approved_count = stats['approved']
            rejected_count = stats['rejected']

            # Count in-progress items (being edited)
            in_progress_count = 0
            in_progress_details = []

            for msg_id, message in pending_messages.items():
                if message.is_locked():
                    in_progress_count += 1
                    admin_name = message.admin_name or "Unknown"
                    in_progress_details.append((msg_id, admin_name))

            # Calculate totals and percentages
            total_processed = approved_count + rejected_count
            approval_percentage = (approved_count / total_processed * 100) if total_processed > 0 else 0

            # Build main statistics display
            status_message = (
                "📈 Детальная статистика модерации:\n\n"
                f"⏳ В ожидании: {pending_count - in_progress_count}\n"
                f"✍️ В работе: {in_progress_count}"
            )

            # Add admin names for in-progress items
            if in_progress_details:
                admin_names = [f"@{admin}" for _, admin in in_progress_details]
                status_message += f" ({', '.join(admin_names)})"

            status_message += (
                f"\n✅ Одобрено: {approved_count}\n"
                f"❌ Отклонено: {rejected_count}\n"
                f"📊 Всего обработано: {total_processed}\n"
                f"📊 Процент одобрения: {approval_percentage:.1f}%\n"
            )

            # Add detailed message list
            if pending_messages or in_progress_details:
                status_message += "\nДетали:\n"
                counter = 1

                # Show in-progress items first
                for msg_id, admin_name in in_progress_details:
                    status_message += f"{counter}. ID: {msg_id[:8]}... - Редактирует @{admin_name}\n"
                    counter += 1

                # Show pending items
                pending_only = {mid: msg for mid, msg in pending_messages.items() if not msg.is_locked()}
                for msg_id in list(pending_only.keys())[:10]:  # Limit to 10 total items
                    if counter > 15:  # Don't exceed reasonable message length
                        status_message += f"... и еще {len(pending_only) - (counter - len(in_progress_details) - 1)} сообщений\n"
                        break
                    status_message += f"{counter}. ID: {msg_id[:8]}... - Ожидает\n"
                    counter += 1

            await update.message.reply_text(status_message)
            logger.info(f"📊 Enhanced stats command executed: pending={pending_count}, in_progress={in_progress_count}, approved={approved_count}, rejected={rejected_count}")

        except Exception as e:
            logger.error(f"❌ Error in enhanced status command: {e}")
            # Fallback to basic stats if enhanced version fails
            try:
                stats = self.moderation_queue.get_statistics()
                fallback_message = (
                    f"📊 Статус модерации (базовый):\n\n"
                    f"⏳ В ожидании: {stats['pending']}\n"
                    f"✅ Одобрено: {stats['approved']}\n"
                    f"❌ Отклонено: {stats['rejected']}"
                )
                await update.message.reply_text(fallback_message)
            except Exception as fallback_error:
                logger.error(f"❌ Fallback stats also failed: {fallback_error}")
                await update.message.reply_text("❌ Ошибка при получении статистики")

    async def pending_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show pending messages with moderation buttons."""
        try:
            # Check if user is authorized admin
            if not Config.is_admin(update.effective_user.id):
                await update.message.reply_text("🚫 У вас нет прав администратора")
                return

            pending_messages = self.moderation_queue.get_pending_messages()

            if not pending_messages:
                await update.message.reply_text("📭 Нет сообщений в ожидании модерации")
                return

            # Send messages to ONLY the requesting admin
            requesting_admin_id = update.effective_user.id

            for msg_id, msg_data in list(pending_messages.items())[:5]:  # Show max 5 with buttons
                moscow_time = get_moscow_time()
                username = msg_data.username or "Unknown"
                text_preview = msg_data.original_message[:100] + "..." if len(msg_data.original_message) > 100 else msg_data.original_message
                ai_response_preview = msg_data.ai_response[:100] + "..." if len(msg_data.ai_response) > 100 else msg_data.ai_response

                # CRITICAL FIX: Check if message is locked and show appropriate status
                if msg_data.is_locked():
                    # Message is being edited - show lock status and no buttons
                    lock_admin_name = msg_data.admin_name or "неизвестным админом"
                    message_text = (
                        f"🔒 В РАБОТЕ - {msg_id}\n"
                        f"👤 Пользователь: {username}\n"
                        f"⏰ Время: {moscow_time}\n"
                        f"🔧 Редактируется: {lock_admin_name}\n"
                        f"💬 Вопрос: {text_preview}\n"
                        f"🤖 Ответ: {ai_response_preview}\n"
                    )
                    keyboard = None  # No buttons when locked
                else:
                    # Message is available - show normal status with buttons
                    message_text = (
                        f"🆔 ID: {msg_id}\n"
                        f"👤 Пользователь: {username}\n"
                        f"⏰ Время: {moscow_time}\n"
                        f"💬 Вопрос: {text_preview}\n"
                        f"🤖 Ответ: {ai_response_preview}\n"
                    )
                    keyboard = self.create_moderation_keyboard(msg_id)

                try:
                    sent_message = await self.bot_application.bot.send_message(
                        chat_id=requesting_admin_id,
                        text=message_text,
                        reply_markup=keyboard
                    )

                    # Store telegram message ID for synchronization
                    if self.admin_bot:
                        self.admin_bot.store_admin_message(msg_id, requesting_admin_id, sent_message.message_id)
                        logger.debug(f"📝 Stored admin message: mod_id={msg_id}, admin={requesting_admin_id}, tg_msg={sent_message.message_id}")

                except Exception as send_error:
                    logger.error(f"❌ Failed to send message to requesting admin {requesting_admin_id}: {send_error}")

            if len(pending_messages) > 5:
                # Send additional info message to the requesting admin only
                await update.message.reply_text(f"... и еще {len(pending_messages) - 5} сообщений")

            logger.info(f"📝 Pending command executed: sent {len(list(pending_messages.items())[:5])} messages to requesting admin {requesting_admin_id}")
        except Exception as e:
            logger.error(f"❌ Error in pending command: {e}")

    async def approve_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Approve a message by ID and send it to the user."""
        try:
            # Check if user is authorized admin
            if not Config.is_admin(update.effective_user.id):
                await update.message.reply_text("🚫 У вас нет прав администратора")
                return

            if not context.args:
                await update.message.reply_text("❗ Укажите ID сообщения: /approve <id>")
                return

            message_id = context.args[0]
            approved_message = self.moderation_queue.approve_message(message_id)

            if approved_message:
                # Send the approved response to the original user
                logger.info(f"📤 ОТПРАВКА ФИНАЛЬНОГО ОТВЕТА: подготовка к отправке сообщения {message_id} через команду")
                logger.info(f"   🎯 Получатель: {approved_message.username} (ID: {approved_message.user_id})")
                logger.info(f"   💬 Чат: {approved_message.chat_id}")
                logger.info(f"   📊 Размер ответа: {len(approved_message.ai_response)} символов")
                logger.info(f"   👤 Одобрено админом: {update.message.from_user.username or update.message.from_user.first_name}")
                try:
                    await self.bot_application.bot.send_message(
                        chat_id=approved_message.chat_id,
                        text=approved_message.ai_response
                    )
                    logger.info(f"✅ ФИНАЛЬНЫЙ ОТВЕТ ДОСТАВЛЕН: сообщение {message_id} успешно отправлено пользователю {approved_message.username} через команду")

                    await update.message.reply_text(
                        f"✅ Сообщение {message_id} одобрено и отправлено пользователю {approved_message.username}"
                    )
                    logger.info(f"✅ Message approved and sent: {message_id} → user {approved_message.username}")

                except Exception as send_error:
                    logger.error(f"❌ ОШИБКА ОТПРАВКИ ФИНАЛЬНОГО ОТВЕТА: сообщение {message_id} не доставлено через команду")
                    logger.error(f"❌ Failed to send approved message to user: {send_error}")
                    await update.message.reply_text(
                        f"✅ Сообщение {message_id} одобрено, но не удалось отправить пользователю: {send_error}"
                    )
            else:
                await update.message.reply_text(f"❌ Сообщение {message_id} не найдено")
        except Exception as e:
            logger.error(f"❌ Error in approve command: {e}")

    async def reject_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Reject a message by ID."""
        try:
            # Check if user is authorized admin
            if not Config.is_admin(update.effective_user.id):
                await update.message.reply_text("🚫 У вас нет прав администратора")
                return

            if not context.args:
                await update.message.reply_text("❗ Укажите ID сообщения: /reject <id> [причина]")
                return

            message_id = context.args[0]
            reason = " ".join(context.args[1:]) if len(context.args) > 1 else "Не указана"

            rejected_message = self.moderation_queue.reject_message(message_id, reason)

            if rejected_message:
                await update.message.reply_text(f"❌ Сообщение {message_id} отклонено\nПричина: {reason}")
                logger.info(f"❌ Message rejected by admin: {message_id}, reason: {reason}")
            else:
                await update.message.reply_text(f"❌ Сообщение {message_id} не найдено")
        except Exception as e:
            logger.error(f"❌ Error in reject command: {e}")

    async def stats_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show detailed moderation statistics."""
        try:
            # Check if user is authorized admin
            if not Config.is_admin(update.effective_user.id):
                await update.message.reply_text("🚫 У вас нет прав администратора")
                return

            # Gather comprehensive statistics
            stats = self.moderation_queue.get_statistics()
            pending_messages = self.moderation_queue.get_pending_messages()

            # Basic counts
            pending_count = stats['pending']
            approved_count = stats['approved']
            rejected_count = stats['rejected']

            # Count in-progress items (being edited)
            in_progress_count = 0
            in_progress_details = []

            for msg_id, message in pending_messages.items():
                if message.is_locked():
                    in_progress_count += 1
                    admin_name = message.admin_name or "Unknown"
                    in_progress_details.append((msg_id, admin_name))

            # Calculate totals and percentages
            total_processed = approved_count + rejected_count
            approval_percentage = (approved_count / total_processed * 100) if total_processed > 0 else 0

            # Build main statistics display
            status_message = (
                "📈 Детальная статистика модерации:\n\n"
                f"⏳ В ожидании: {pending_count - in_progress_count}\n"
                f"✍️ В работе: {in_progress_count}"
            )

            # Add admin names for in-progress items
            if in_progress_details:
                admin_names = [f"@{admin}" for _, admin in in_progress_details]
                status_message += f" ({', '.join(admin_names)})"

            status_message += (
                f"\n✅ Одобрено: {approved_count}\n"
                f"❌ Отклонено: {rejected_count}\n"
                f"📊 Всего обработано: {total_processed}\n"
                f"📊 Процент одобрения: {approval_percentage:.1f}%\n"
            )

            # Add detailed message list
            if pending_messages or in_progress_details:
                status_message += "\nДетали:\n"
                counter = 1

                # Show in-progress items first
                for msg_id, admin_name in in_progress_details:
                    status_message += f"{counter}. ID: {msg_id[:8]}... - Редактирует @{admin_name}\n"
                    counter += 1

                # Show pending items
                pending_only = {mid: msg for mid, msg in pending_messages.items() if not msg.is_locked()}
                for msg_id in list(pending_only.keys())[:10]:  # Limit to 10 total items
                    if counter > 15:  # Don't exceed reasonable message length
                        status_message += f"... и еще {len(pending_only) - (counter - len(in_progress_details) - 1)} сообщений\n"
                        break
                    status_message += f"{counter}. ID: {msg_id[:8]}... - Ожидает\n"
                    counter += 1

            await update.message.reply_text(status_message)
            logger.info(f"📊 Enhanced stats command executed: pending={pending_count}, in_progress={in_progress_count}, approved={approved_count}, rejected={rejected_count}")

        except Exception as e:
            logger.error(f"❌ Error in enhanced stats command: {e}")
            # Fallback to basic stats if enhanced version fails
            try:
                stats = self.moderation_queue.get_statistics()
                fallback_message = (
                    f"📊 Статус модерации (базовый):\n\n"
                    f"⏳ В ожидании: {stats['pending']}\n"
                    f"✅ Одобрено: {stats['approved']}\n"
                    f"❌ Отклонено: {stats['rejected']}"
                )
                await update.message.reply_text(fallback_message)
            except Exception as fallback_error:
                logger.error(f"❌ Fallback stats also failed: {fallback_error}")

    async def clear_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Clear all pending messages from moderation queue with confirmation."""
        try:
            # Check if user is authorized admin
            if not Config.is_admin(update.effective_user.id):
                await update.message.reply_text("🚫 У вас нет прав администратора")
                return

            # Get count before clearing
            pending_count = self.moderation_queue.get_pending_count()

            if pending_count == 0:
                await update.message.reply_text("📭 Очередь модерации уже пуста")
                logger.info("🧹 Clear command executed: queue already empty")
                return

            # Show confirmation dialog with buttons
            from telegram import InlineKeyboardButton, InlineKeyboardMarkup

            confirmation_text = (
                f"⚠️ **ПОДТВЕРЖДЕНИЕ ОЧИСТКИ ОЧЕРЕДИ**\n\n"
                f"📊 В очереди сейчас: **{pending_count}** сообщений\n"
                f"🗑️ Все сообщения будут удалены без возможности восстановления\n\n"
                f"❓ Вы уверены, что хотите очистить всю очередь модерации?"
            )

            keyboard = [
                [
                    InlineKeyboardButton("✅ Да, очистить", callback_data="clear_confirm_yes"),
                    InlineKeyboardButton("❌ Нет, отменить", callback_data="clear_confirm_no")
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await update.message.reply_text(
                confirmation_text,
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )

            logger.info(f"🧹 Clear confirmation shown to admin {update.message.from_user.username or update.message.from_user.first_name} (ID: {update.effective_user.id})")

        except Exception as e:
            logger.error(f"❌ Error in clear command: {e}")
            await update.message.reply_text(f"❌ Ошибка при показе подтверждения очистки: {e}")

    async def notification_off_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Turn off notifications for the requesting admin."""
        try:
            # Check if user is authorized admin
            if not Config.is_admin(update.effective_user.id):
                await update.message.reply_text("🚫 У вас нет прав администратора")
                return

            admin_user_id = update.effective_user.id

            # Disable reminders for this admin
            if self.admin_bot:
                self.admin_bot.disabled_reminders[admin_user_id] = True
                await update.message.reply_text("🔕 Напоминания отключены для вас")
                logger.info(f"🔕 Admin {admin_user_id} disabled reminders via /notification_off")
            else:
                await update.message.reply_text("❌ Ошибка: админ-бот не найден")

        except Exception as e:
            logger.error(f"❌ Error in notification_off command: {e}")
            await update.message.reply_text(f"❌ Ошибка при отключении напоминаний: {e}")

    async def notification_on_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Turn on notifications for the requesting admin."""
        try:
            # Check if user is authorized admin
            if not Config.is_admin(update.effective_user.id):
                await update.message.reply_text("🚫 У вас нет прав администратора")
                return

            admin_user_id = update.effective_user.id

            # Enable reminders for this admin
            if self.admin_bot:
                self.admin_bot.disabled_reminders.pop(admin_user_id, None)
                await update.message.reply_text("🔔 Напоминания включены")
                logger.info(f"🔔 Admin {admin_user_id} enabled reminders via /notification_on")
            else:
                await update.message.reply_text("❌ Ошибка: админ-бот не найден")

        except Exception as e:
            logger.error(f"❌ Error in notification_on command: {e}")
            await update.message.reply_text(f"❌ Ошибка при включении напоминаний: {e}")

    async def button_callback_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle callback queries from inline buttons."""
        query = update.callback_query
        await query.answer()

        try:
            callback_data = query.data
            admin_user = query.from_user

            # Check if user is authorized admin
            if not Config.is_admin(admin_user.id):
                logger.warning(f"🚫 Unauthorized callback attempt from user {admin_user.username or admin_user.first_name} (ID: {admin_user.id})")
                await query.edit_message_text("🚫 У вас нет прав администратора")
                return

            logger.info(f"🔘 АДМИН ДЕЙСТВИЕ: {callback_data} от пользователя {admin_user.username or admin_user.first_name} (ID: {admin_user.id})")
            logger.info(f"🔘 Callback received: {callback_data}")

            # Parse callback data: action_messageId or cancel_edit_messageId
            if '_' not in callback_data:
                await query.edit_message_text("❌ Неверные данные кнопки")
                return

            # Handle special cases for multi-word actions
            if callback_data.startswith('cancel_edit_'):
                action = 'cancel_edit'
                message_id = callback_data[12:]  # Remove 'cancel_edit_' prefix
                logger.info(f"🔄 CANCEL_EDIT parsed: callback_data='{callback_data}' → action='{action}', message_id='{message_id}'")
            elif callback_data.startswith('manual_edit_'):
                action = 'manual_edit'
                message_id = callback_data[12:]  # Remove 'manual_edit_' prefix
                logger.info(f"🔄 MANUAL_EDIT parsed: callback_data='{callback_data}' → action='{action}', message_id='{message_id}'")
            elif callback_data.startswith('show_full_'):
                action = 'show_full'
                message_id = callback_data[10:]  # Remove 'show_full_' prefix
                logger.info(f"🔄 SHOW_FULL parsed: callback_data='{callback_data}' → action='{action}', message_id='{message_id}'")
            elif callback_data.startswith('hide_full_'):
                action = 'hide_full'
                message_id = callback_data[10:]  # Remove 'hide_full_' prefix
                logger.info(f"🔄 HIDE_FULL parsed: callback_data='{callback_data}' → action='{action}', message_id='{message_id}'")
            elif callback_data.startswith('return_to_manual_edit_'):
                action = 'return_to_manual_edit'
                message_id = callback_data[22:]  # Remove 'return_to_manual_edit_' prefix (22 chars)
                logger.info(f"🔄 RETURN_TO_MANUAL_EDIT parsed: callback_data='{callback_data}' → action='{action}', message_id='{message_id}'")
            elif callback_data.startswith('return_to_edit_'):
                action = 'return_to_edit'
                message_id = callback_data[15:]  # Remove 'return_to_edit_' prefix
                logger.info(f"🔄 RETURN_TO_EDIT parsed: callback_data='{callback_data}' → action='{action}', message_id='{message_id}'")
            elif callback_data.startswith('reset_question_'):
                action = 'reset_question'
                message_id = callback_data[15:]  # Remove 'reset_question_' prefix
                logger.info(f"🔄 RESET_QUESTION parsed: callback_data='{callback_data}' → action='{action}', message_id='{message_id}'")
            elif callback_data == 'clear_confirm_yes':
                action = 'clear_confirm_yes'
                message_id = None  # No message ID for clear confirmation
                logger.info(f"🔄 CLEAR_CONFIRM_YES parsed: callback_data='{callback_data}' → action='{action}'")
            elif callback_data == 'clear_confirm_no':
                action = 'clear_confirm_no'
                message_id = None  # No message ID for clear confirmation
                logger.info(f"🔄 CLEAR_CONFIRM_NO parsed: callback_data='{callback_data}' → action='{action}'")
            elif callback_data.startswith('copy_'):
                action = 'copy'
                message_id = callback_data[5:]  # Remove 'copy_' prefix
                logger.info(f"🔄 COPY parsed: callback_data='{callback_data}' → action='{action}', message_id='{message_id}'")
            else:
                action, message_id = callback_data.split('_', 1)
                logger.info(f"🔄 REGULAR parsed: callback_data='{callback_data}' → action='{action}', message_id='{message_id}'")

            if action == "edit":
                await self.handle_edit_callback(query, message_id)
            elif action == "manual_edit":
                await self.handle_manual_edit_callback(query, message_id)
            elif action == "copy":
                await self.handle_copy_callback(query, message_id)
            elif action == "send":
                await self.handle_send_callback(query, message_id)
            elif action == "reject":
                await self.handle_reject_callback(query, message_id)
            elif action == "cancel_edit":
                await self.handle_cancel_edit_callback(query, message_id)
            elif action == "show_full":
                await self.handle_show_full_callback(query, message_id)
            elif action == "hide_full":
                await self.handle_hide_full_callback(query, message_id)
            elif action == "return_to_manual_edit":
                await self.handle_return_to_manual_edit_callback(query, message_id)
            elif action == "return_to_edit":
                await self.handle_return_to_edit_callback(query, message_id)
            elif action == "reset_question":
                await self.handle_reset_question_callback(query, message_id)
            elif action == "clear_confirm_yes":
                await self.handle_clear_confirm_yes_callback(query)
            elif action == "clear_confirm_no":
                await self.handle_clear_confirm_no_callback(query)
            else:
                await query.edit_message_text(f"❌ Неизвестное действие: {action}")

        except Exception as e:
            logger.error(f"❌ Error in callback handler: {e}")
            await query.edit_message_text("❌ Ошибка при обработке действия")

    async def handle_edit_callback(self, query, message_id: str):
        """Handle edit button callback - set correction state."""
        try:
            admin_user_id = query.from_user.id
            admin_username = query.from_user.username or query.from_user.first_name

            logger.info(f"🔄 EDIT_CALLBACK_START: message_id='{message_id}', admin={admin_username} (ID: {admin_user_id})")
            logger.info(f"🔄 Current correction states: {list(self.correction_states.keys())}")

            # Check if admin already has an active correction session
            if admin_user_id in self.correction_states:
                active_msg_id = self.correction_states[admin_user_id].get('message_id')
                logger.warning(f"⚠️ Admin {admin_user_id} already has active correction for message {active_msg_id}")

                # Show warning about active correction session
                warning_text = (
                    f"⚠️ У вас уже есть активная сессия редактирования!\n\n"
                    f"📝 В процессе редактирования: сообщение **{active_msg_id}**\n\n"
                    f"🔄 Сначала завершите правки по текущему сообщению,\n"
                    f"а затем начните редактирование нового.\n\n"
                    f"💡 **Инструкции:**\n"
                    f"• Отправьте корректировку для сообщения **{active_msg_id}**\n"
                    f"• Или нажмите \"❌ Отменить\" в текущем сообщении\n"
                    f"• Для просмотра всех задач: /pending"
                )
                await query.edit_message_text(warning_text, parse_mode='Markdown')
                return

            # Get pending messages count for debugging
            pending_count = self.moderation_queue.get_pending_count()
            logger.info(f"📊 Current pending messages count: {pending_count}")

            # Force reload queue to ensure synchronization
            self.moderation_queue._load_data()
            logger.info(f"🔄 Queue reloaded, new pending count: {self.moderation_queue.get_pending_count()}")

            message = self.moderation_queue.get_from_queue(message_id)
            if not message:
                logger.error(f"❌ EDIT_CALLBACK_FAILED: message '{message_id}' not found in queue")
                await query.edit_message_text(f"❌ Сообщение {message_id} не найдено")
                return

            # Check editing lock with timeout
            if message.editing_admin_id and message.editing_admin_id != admin_user_id:
                # Check 10-minute timeout
                if time.time() - message.editing_started_at < 600:
                    await query.answer(f"⚠️ Редактирует @{message.editing_admin_name}")
                    return
                else:
                    # Remove expired lock
                    message.editing_admin_id = None
                    message.editing_admin_name = None
                    message.editing_started_at = None

            # Set editing lock
            message.editing_admin_id = admin_user_id
            message.editing_admin_name = admin_username
            message.editing_started_at = time.time()

            # Update all other admins' interfaces (remove buttons)
            for admin_id in Config.ADMIN_CHAT_IDS:
                if admin_id != str(admin_user_id):  # Skip the admin who is editing
                    try:
                        # Get stored message ID for this admin
                        if hasattr(self, 'admin_messages') and message_id in self.admin_messages and admin_id in self.admin_messages[message_id]:
                            telegram_msg_id = self.admin_messages[message_id][admin_id]
                            # Remove buttons from other admins
                            await self.bot_application.bot.edit_message_reply_markup(
                                chat_id=int(admin_id),
                                message_id=telegram_msg_id,
                                reply_markup=None
                            )
                    except Exception as e:
                        logger.error(f"Failed to update admin {admin_id}: {e}")

            # Send notification to ALL admins about edit start
            notification_count = 0
            moscow_time = get_moscow_time()

            for admin_id in Config.ADMIN_CHAT_IDS:
                # Skip notification to the admin who started editing (no self-notification)
                if admin_id == str(admin_user_id):
                    continue

                try:
                    edit_notification = (
                        f"🔔 **Уведомление о начале редактирования**\n\n"
                        f"📝 Сообщение: {message_id}\n"
                        f"👤 Админ: @{admin_username}\n"
                        f"🕐 Начато: {moscow_time}\n"
                        f"💬 Вопрос: {message.original_message[:100]}{'...' if len(message.original_message) > 100 else ''}\n\n"
                        f"ℹ️ Сообщение заблокировано для редактирования"
                    )

                    await self.bot_application.bot.send_message(
                        chat_id=int(admin_id),
                        text=edit_notification,
                        parse_mode='Markdown'
                    )
                    notification_count += 1
                    logger.info(f"🔔 Уведомление о начале редактирования отправлено админу {admin_id}")

                except Exception as e:
                    logger.error(f"❌ Failed to notify admin {admin_id} about edit start: {e}")

            logger.info(f"🔔 EDIT_START notifications sent to {notification_count} admins")

            # Lock message for editing by this admin (keeping existing functionality)
            message.lock_for_editing(admin_user_id, admin_username)

            # Save the updated message with editing lock
            self.moderation_queue._save_data()

            # Update all admin messages to show it's being edited
            if self.admin_bot:
                await self.admin_bot.update_all_admin_messages(message_id, "edit", admin_username)
                # Start edit timeout tracking
                self.admin_bot.start_edit_timeout(message_id, admin_user_id, admin_username)

            # Set correction state for this admin user
            self.correction_states[admin_user_id] = {
                'message_id': message_id,
                'step': 'waiting_correction',
                'original_message': message
            }

            chat_title = message.chat_title or "Личные сообщения"

            edit_text = (
                f"✏️ Режим корректировки активирован для сообщения {message_id}\n\n"
                f"📱 Чат: {chat_title}\n"
                f"👤 Пользователь: {message.username}\n"
                f"💬 Вопрос: {message.original_message}\n\n"
                f"🤖 Текущий ответ:\n{message.ai_response}\n\n"
                f"📝 Отправьте текстовое или голосовое сообщение с корректировками.\n"
                f"🎤 Голосовые сообщения будут обработаны через Whisper."
            )

            # Create specialized editing keyboard
            keyboard = [
                [
                    InlineKeyboardButton("❌ Отменить редактирование", callback_data=f"cancel_edit_{message_id}")
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await query.edit_message_text(edit_text, reply_markup=reply_markup)
            logger.info(f"✏️ КОРРЕКТИРОВКА АКТИВИРОВАНА: сообщение {message_id}, админ {query.from_user.username or query.from_user.first_name} (ID: {admin_user_id})")
            logger.info(f"✏️ Correction state activated for message {message_id} by admin {admin_user_id}")

        except Exception as e:
            logger.error(f"❌ Error in edit handler: {e}")
            logger.error(f"❌ Exception type: {type(e).__name__}")
            logger.error(f"❌ Exception details: {str(e)}")

            # Try to reload queue and provide better diagnostics
            try:
                self.moderation_queue._load_data()
                pending_count = self.moderation_queue.get_pending_count()
                pending_ids = list(self.moderation_queue.get_pending_messages().keys())
                logger.error(f"❌ After reload: {pending_count} pending messages, IDs: {pending_ids}")

                if message_id in pending_ids:
                    await query.edit_message_text(f"❌ Ошибка при подготовке редактирования: {str(e)}")
                else:
                    await query.edit_message_text(f"❌ Сообщение {message_id} больше не доступно для редактирования")
            except Exception as reload_error:
                logger.error(f"❌ Failed to reload queue during error recovery: {reload_error}")
                await query.edit_message_text("❌ Ошибка при подготовке редактирования")

    async def handle_copy_callback(self, query, message_id: str):
        """Handle copy button callback - show AI response in code block for instant copying."""
        try:
            admin_user_id = query.from_user.id
            message = self.moderation_queue.get_from_queue(message_id)
            if not message:
                await query.answer("❌ Сообщение не найдено", show_alert=True)
                return

            # Format text in code block for easy tap-to-copy in Telegram
            # Telegram allows up to 4096 characters, code block up to ~3800 characters works well
            max_copy_length = 3800
            ai_response_text = message.ai_response

            if len(ai_response_text) > max_copy_length:
                ai_response_text = ai_response_text[:max_copy_length] + "\n\n... (обрезано)"

            copy_display = (
                f"📋 **Текст для копирования** (ID: {message_id})\n\n"
                f"💡 *Нажмите на текст ниже для быстрого копирования*\n\n"
                f"```\n{ai_response_text}\n```\n\n"
                f"👆 Нажмите на блок текста выше чтобы скопировать"
            )

            # Check if user has active editing session to return to correct state
            has_editing_session = admin_user_id in self.correction_states
            editing_is_manual = has_editing_session and self.correction_states[admin_user_id].get('step') == 'waiting_manual_correction'

            # Create keyboard to return back - either to editing or to message
            if editing_is_manual:
                keyboard = [
                    [InlineKeyboardButton("🔙 Вернуться к ручному редактированию", callback_data=f"return_to_manual_edit_{message_id}")]
                ]
            elif has_editing_session:
                keyboard = [
                    [InlineKeyboardButton("🔙 Вернуться к ИИ редактированию", callback_data=f"return_to_edit_{message_id}")]
                ]
            else:
                keyboard = [
                    [InlineKeyboardButton("🔙 Вернуться к сообщению", callback_data=f"hide_full_{message_id}")]
                ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await query.edit_message_text(copy_display, reply_markup=reply_markup, parse_mode='Markdown')
            await query.answer("📋 Нажмите на текст для копирования", show_alert=False)
            logger.info(f"📋 Copy callback: showed AI response for message {message_id} to admin {admin_user_id}")

        except Exception as e:
            logger.error(f"❌ Error in copy callback: {e}")
            await query.answer("❌ Ошибка при копировании текста", show_alert=True)

    async def handle_manual_edit_callback(self, query, message_id: str):
        """Handle manual edit button callback - allow admin to send their own corrected text."""
        try:
            admin_user_id = query.from_user.id
            admin_username = query.from_user.username or query.from_user.first_name

            logger.info(f"✍️ MANUAL_EDIT_START: message_id='{message_id}', admin={admin_username} (ID: {admin_user_id})")

            # Check if admin already has an active correction session
            if admin_user_id in self.correction_states:
                active_msg_id = self.correction_states[admin_user_id].get('message_id')
                logger.warning(f"⚠️ Admin {admin_user_id} already has active correction for message {active_msg_id}")

                warning_text = (
                    f"⚠️ У вас уже есть активная сессия редактирования!\n\n"
                    f"📝 В процессе редактирования: сообщение **{active_msg_id}**\n\n"
                    f"🔄 Сначала завершите правки по текущему сообщению,\n"
                    f"а затем начните редактирование нового.\n\n"
                    f"💡 **Инструкции:**\n"
                    f"• Отправьте корректировку для сообщения **{active_msg_id}**\n"
                    f"• Или нажмите \"❌ Отменить\" в текущем сообщении\n"
                    f"• Для просмотра всех задач: /pending"
                )
                await query.edit_message_text(warning_text, parse_mode='Markdown')
                return

            # Get message from queue
            message = self.moderation_queue.get_from_queue(message_id)
            if not message:
                logger.error(f"❌ MANUAL_EDIT_FAILED: message '{message_id}' not found in queue")
                await query.edit_message_text(f"❌ Сообщение {message_id} не найдено")
                return

            # Check editing lock with timeout
            if message.editing_admin_id and message.editing_admin_id != admin_user_id:
                if time.time() - message.editing_started_at < 600:
                    await query.answer(f"⚠️ Редактирует @{message.editing_admin_name}")
                    return
                else:
                    # Remove expired lock
                    message.editing_admin_id = None
                    message.editing_admin_name = None
                    message.editing_started_at = None

            # Set editing lock
            message.editing_admin_id = admin_user_id
            message.editing_admin_name = admin_username
            message.editing_started_at = time.time()

            # Lock message for manual editing
            message.lock_for_editing(admin_user_id, admin_username)
            self.moderation_queue._save_data()

            # Update all other admins' interfaces (remove buttons)
            for admin_id in Config.ADMIN_CHAT_IDS:
                if admin_id != str(admin_user_id):  # Skip the admin who is editing
                    try:
                        # Get stored message ID for this admin
                        if hasattr(self, 'admin_messages') and message_id in self.admin_messages and admin_id in self.admin_messages[message_id]:
                            telegram_msg_id = self.admin_messages[message_id][admin_id]
                            # Remove buttons from other admins
                            await self.bot_application.bot.edit_message_reply_markup(
                                chat_id=int(admin_id),
                                message_id=telegram_msg_id,
                                reply_markup=None
                            )
                    except Exception as e:
                        logger.error(f"Failed to update admin {admin_id}: {e}")

            # Send notification to ALL admins about manual edit start
            notification_count = 0
            moscow_time = get_moscow_time()

            for admin_id in Config.ADMIN_CHAT_IDS:
                # Skip notification to the admin who started editing (no self-notification)
                if admin_id == str(admin_user_id):
                    continue

                try:
                    edit_notification = (
                        f"🔔 **Уведомление о начале ручного редактирования**\n\n"
                        f"📝 Сообщение: {message_id}\n"
                        f"👤 Админ: @{admin_username}\n"
                        f"🕐 Начато: {moscow_time}\n"
                        f"💬 Вопрос: {message.original_message[:100]}{'...' if len(message.original_message) > 100 else ''}\n\n"
                        f"ℹ️ Сообщение заблокировано для ручного редактирования"
                    )

                    await self.bot_application.bot.send_message(
                        chat_id=int(admin_id),
                        text=edit_notification,
                        parse_mode='Markdown'
                    )
                    notification_count += 1
                    logger.info(f"🔔 Уведомление о начале ручного редактирования отправлено админу {admin_id}")

                except Exception as e:
                    logger.error(f"❌ Failed to notify admin {admin_id} about manual edit start: {e}")

            logger.info(f"🔔 MANUAL_EDIT_START notifications sent to {notification_count} admins")

            # Update all admin messages to show it's being edited
            if self.admin_bot:
                await self.admin_bot.update_all_admin_messages(message_id, "manual_edit", admin_username)
                # Start edit timeout tracking
                self.admin_bot.start_edit_timeout(message_id, admin_user_id, admin_username)

            # Set correction state for manual editing
            self.correction_states[admin_user_id] = {
                'message_id': message_id,
                'step': 'waiting_manual_correction',  # Different step for manual editing
                'original_message': message
            }

            chat_title = message.chat_title or "Личные сообщения"

            edit_text = (
                f"✍️ **Режим ручного редактирования активирован** для сообщения {message_id}\n\n"
                f"📱 Чат: {chat_title}\n"
                f"👤 Пользователь: {message.username}\n"
                f"💬 Вопрос: {message.original_message}\n\n"
                f"🤖 Текущий ответ ИИ:\n{message.ai_response}\n\n"
                f"📝 **Отправьте ваш исправленный текст** в следующем сообщении.\n"
                f"После отправки вы увидите превью с возможностью:\n"
                f"• Отправить пользователю\n"
                f"• Продолжить редактирование\n"
                f"• Отклонить\n\n"
                f"💡 **Подсказка:** используйте кнопку \"📋 Копировать\" для получения текста ИИ"
            )

            # Create keyboard with copy and cancel buttons
            keyboard = [
                [
                    InlineKeyboardButton("📋 Копировать текст ИИ", callback_data=f"copy_{message_id}"),
                    InlineKeyboardButton("❌ Отменить", callback_data=f"cancel_edit_{message_id}")
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await query.edit_message_text(edit_text, reply_markup=reply_markup, parse_mode='Markdown')
            logger.info(f"✍️ Manual edit activated for message {message_id} by admin {admin_user_id}")

        except Exception as e:
            logger.error(f"❌ Error in manual edit handler: {e}")
            await query.edit_message_text("❌ Ошибка при активации ручного редактирования")

    async def handle_send_callback(self, query, message_id: str):
        """Handle send button callback - approve and send message to user."""
        try:
            message = self.moderation_queue.get_from_queue(message_id)
            if not message:
                await query.edit_message_text(f"❌ Сообщение {message_id} не найдено")
                return

            # Check if message is locked by another admin
            if message.is_locked() and message.admin_processing != query.from_user.id:
                admin_name = message.admin_name or "другим админом"
                await query.edit_message_text(
                    f"🔒 Сообщение {message_id} уже обрабатывается {admin_name}"
                )
                return

            # Lock message for processing
            admin_username = query.from_user.username or query.from_user.first_name
            message.lock_for_editing(query.from_user.id, admin_username)

            # Approve the message
            approved_message = self.moderation_queue.approve_message(message_id)

            if approved_message:
                # Send the approved response to the original user
                logger.info(f"📤 ОТПРАВКА ФИНАЛЬНОГО ОТВЕТА: подготовка к отправке сообщения {message_id} через кнопку")
                logger.info(f"   🎯 Получатель: {approved_message.username} (ID: {approved_message.user_id})")
                logger.info(f"   💬 Чат: {approved_message.chat_id}")
                logger.info(f"   📊 Размер ответа: {len(approved_message.ai_response)} символов")
                logger.info(f"   👤 Одобрено админом: {admin_username}")
                try:
                    # Use bot messenger service to queue message for main bot
                    from services.bot_communication import get_bot_messenger
                    bot_messenger = get_bot_messenger(use_redis=False)

                    logger.info(f"📤 Отправка сообщения в чат {approved_message.chat_id}")
                    logger.info(f"📝 Текст: {approved_message.ai_response[:50]}{'...' if len(approved_message.ai_response) > 50 else ''}")

                    # Queue message for main bot to send
                    message_queue_id = await bot_messenger.send_final_response(
                        chat_id=approved_message.chat_id,
                        user_id=approved_message.user_id,
                        text=approved_message.ai_response,
                        original_message_id=approved_message.original_message_id,
                        metadata={
                            'moderation_id': message_id,
                            'approved_by': admin_username,
                            'username': approved_message.username
                        }
                    )

                    logger.info(f"✅ Результат отправки: успех (добавлено в очередь {message_queue_id})")
                    logger.info(f"✅ ФИНАЛЬНЫЙ ОТВЕТ ДОБАВЛЕН В ОЧЕРЕДЬ: сообщение {message_id} будет отправлено основным ботом пользователю {approved_message.username}")
                    logger.info(f"✅ СООБЩЕНИЕ ОТПРАВЛЕНО: ID {message_id} → пользователю {approved_message.username}, админ {admin_username}")
                    logger.info(f"✅ Message approved and sent via button: {message_id} → user {approved_message.username}")

                    # Send notification to ALL admins about message approval
                    notification_count = 0
                    moscow_time = get_moscow_time()

                    for admin_id in Config.ADMIN_CHAT_IDS:
                        # Skip notification to the admin who sent the message (no self-notification)
                        if admin_id == str(query.from_user.id):
                            continue

                        try:
                            # Safely truncate and escape user message to prevent Markdown parsing errors
                            safe_message = approved_message.original_message[:100]
                            if len(approved_message.original_message) > 100:
                                safe_message += '...'
                            safe_message = escape_markdown_v2(safe_message)

                            send_notification = (
                                f"🔔 **Уведомление об отправке сообщения**\n\n"
                                f"📝 Сообщение: {escape_markdown_v2(message_id)}\n"
                                f"👤 Админ: @{escape_markdown_v2(admin_username)}\n"
                                f"👥 Пользователь: {escape_markdown_v2(approved_message.username)}\n"
                                f"🕐 Отправлено: {moscow_time}\n"
                                f"💬 Вопрос: {safe_message}\n\n"
                                f"✅ Сообщение одобрено и отправлено пользователю"
                            )

                            await self.bot_application.bot.send_message(
                                chat_id=int(admin_id),
                                text=send_notification,
                                parse_mode='MarkdownV2'
                            )
                            notification_count += 1
                            logger.info(f"🔔 Уведомление об отправке отправлено админу {admin_id}")

                        except Exception as e:
                            logger.error(f"❌ Failed to notify admin {admin_id} about message send: {e}")

                    logger.info(f"🔔 SEND notifications sent to {notification_count} admins")

                    # CRITICAL FIX: Clear all locks after successful send
                    if message:
                        # Clear System 1: admin_bot level locks
                        message.editing_admin_id = None
                        message.editing_admin_name = None
                        message.editing_started_at = None

                        # Clear System 2: moderation_service level locks
                        if message.is_locked():
                            message.unlock_editing()

                        # Save the changes
                        self.moderation_queue._save_data()
                        logger.info(f"🔓 All locks cleared after successful send of {message_id}")

                    # Update all admin messages to show success
                    if self.admin_bot:
                        await self.admin_bot.update_all_admin_messages(message_id, "send", admin_username)

                except Exception as send_error:
                    logger.error(f"❌ Результат отправки: ошибка ({send_error})")
                    logger.error(f"❌ ОШИБКА ДОБАВЛЕНИЯ В ОЧЕРЕДЬ: сообщение {message_id} не добавлено в очередь")
                    logger.error(f"❌ Failed to queue approved message: {send_error}")

                    # CRITICAL FIX: Clear locks even on send error to prevent persistence
                    if message:
                        # Clear System 1: admin_bot level locks
                        message.editing_admin_id = None
                        message.editing_admin_name = None
                        message.editing_started_at = None

                        # Clear System 2: moderation_service level locks
                        if message.is_locked():
                            message.unlock_editing()

                        # Save the changes
                        self.moderation_queue._save_data()
                        logger.info(f"🔓 Locks cleared after send error for {message_id}")

                    # Update all admin messages with error status
                    if self.admin_bot:
                        await self.admin_bot.update_all_admin_messages(message_id, "send_error", admin_username)
            else:
                # Update all admin messages with error status
                if self.admin_bot:
                    await self.admin_bot.update_all_admin_messages(message_id, "send_error", admin_username)

        except Exception as e:
            logger.error(f"❌ Error in send handler: {e}")
            # If we have admin_bot reference and message was locked, update all admin messages
            if hasattr(self, 'admin_bot') and self.admin_bot:
                admin_username = query.from_user.username or query.from_user.first_name
                await self.admin_bot.update_all_admin_messages(message_id, "send_error", admin_username)

    async def handle_reject_callback(self, query, message_id: str):
        """Handle reject button callback."""
        try:
            message = self.moderation_queue.get_from_queue(message_id)
            if not message:
                await query.edit_message_text(f"❌ Сообщение {message_id} не найдено")
                return

            # Check if message is locked by another admin
            if message.is_locked() and message.admin_processing != query.from_user.id:
                admin_name = message.admin_name or "другим админом"
                await query.edit_message_text(
                    f"🔒 Сообщение {message_id} уже обрабатывается {admin_name}"
                )
                return

            # Lock message for processing
            admin_username = query.from_user.username or query.from_user.first_name
            message.lock_for_editing(query.from_user.id, admin_username)

            rejected_message = self.moderation_queue.reject_message(message_id, "Отклонено через кнопку")

            if rejected_message:
                logger.info(f"❌ СООБЩЕНИЕ ОТКЛОНЕНО: ID {message_id} от пользователя {rejected_message.username}, админ {admin_username}")
                logger.info(f"❌ Message rejected via button: {message_id}")

                # Send notification to ALL admins about message rejection
                notification_count = 0
                moscow_time = get_moscow_time()

                for admin_id in Config.ADMIN_CHAT_IDS:
                    # Skip notification to the admin who performed the action (no self-notification)
                    if admin_id == str(query.from_user.id):
                        continue
                    try:
                        # Safely truncate and escape user message to prevent Markdown parsing errors
                        safe_message = rejected_message.original_message[:100]
                        if len(rejected_message.original_message) > 100:
                            safe_message += '...'
                        safe_message = escape_markdown_v2(safe_message)

                        reject_notification = (
                            f"🔔 **Уведомление об отклонении сообщения**\n\n"
                            f"📝 Сообщение: {escape_markdown_v2(message_id)}\n"
                            f"👤 Админ: @{escape_markdown_v2(admin_username)}\n"
                            f"👥 Пользователь: {escape_markdown_v2(rejected_message.username)}\n"
                            f"🕐 Отклонено: {moscow_time}\n"
                            f"💬 Вопрос: {safe_message}\n\n"
                            f"❌ Сообщение отклонено и не будет отправлено пользователю"
                        )

                        await self.bot_application.bot.send_message(
                            chat_id=int(admin_id),
                            text=reject_notification,
                            parse_mode='MarkdownV2'
                        )
                        notification_count += 1
                        logger.info(f"🔔 Уведомление об отклонении отправлено админу {admin_id}")

                    except Exception as e:
                        logger.error(f"❌ Failed to notify admin {admin_id} about message rejection: {e}")

                logger.info(f"🔔 REJECT notifications sent to {notification_count} admins")

                # Update all admin messages to show rejection
                if self.admin_bot:
                    await self.admin_bot.update_all_admin_messages(message_id, "reject", admin_username)
            else:
                # Update all admin messages with error status
                if self.admin_bot:
                    await self.admin_bot.update_all_admin_messages(message_id, "reject_error", admin_username)

        except Exception as e:
            logger.error(f"❌ Error in reject handler: {e}")
            # If we have admin_bot reference, update all admin messages with error
            if hasattr(self, 'admin_bot') and self.admin_bot:
                admin_username = query.from_user.username or query.from_user.first_name
                await self.admin_bot.update_all_admin_messages(message_id, "reject_error", admin_username)


    async def handle_cancel_edit_callback(self, query, message_id: str):
        """Handle cancel edit button callback."""
        try:
            admin_user_id = query.from_user.id
            admin_username = query.from_user.username or query.from_user.first_name

            logger.info(f"❌ CANCEL_EDIT_START: message_id='{message_id}', admin={admin_username} (ID: {admin_user_id})")
            logger.info(f"❌ Current correction states before cleanup: {list(self.correction_states.keys())}")

            # Remove correction state if exists
            if admin_user_id in self.correction_states:
                active_msg_id = self.correction_states[admin_user_id].get('message_id')
                logger.info(f"🗑️ Clearing correction state: admin {admin_user_id}, active message {active_msg_id}")
                del self.correction_states[admin_user_id]
                logger.info(f"✅ Correction cancelled via button for message {message_id} by admin {admin_user_id}")
            else:
                logger.warning(f"⚠️ No active correction state found for admin {admin_user_id}")

            logger.info(f"❌ Correction states after cleanup: {list(self.correction_states.keys())}")

            # Force reload queue to ensure synchronization
            self.moderation_queue._load_data()
            logger.info(f"🔄 Queue reloaded for cancel edit")

            # Show original message with main keyboard
            message = self.moderation_queue.get_from_queue(message_id)
            if not message:
                logger.error(f"❌ CANCEL_EDIT_FAILED: message '{message_id}' not found in queue")
                await query.edit_message_text(f"❌ Сообщение {message_id} не найдено")
                return

            # CRITICAL FIX: Clear BOTH locking systems and always notify all admins
            lock_was_active = False
            current_admin_name = admin_username

            # Clear System 1: admin_bot level locks
            if message.editing_admin_id == admin_user_id:
                current_admin_name = message.editing_admin_name or admin_username
                message.editing_admin_id = None
                message.editing_admin_name = None
                message.editing_started_at = None
                lock_was_active = True
                logger.info(f"🔓 System 1 lock cleared (admin_bot level)")

            # Clear System 2: moderation_service level locks
            if message.is_locked() and message.admin_processing == admin_user_id:
                message.unlock_editing()  # This clears admin_processing, admin_name, and status
                lock_was_active = True
                logger.info(f"🔓 System 2 lock cleared (moderation_service level)")

            # Force save after clearing both lock systems
            self.moderation_queue._save_data()
            logger.info(f"🔓 All editing locks cleared for message {message_id}")

            # ALWAYS send notifications to ALL admins (not conditional)
            notification_count = 0
            for admin_id in Config.ADMIN_CHAT_IDS:
                # Skip notification to the admin who performed the action (no self-notification)
                if admin_id == str(admin_user_id):
                    continue
                try:
                    # Get stored message ID for this admin
                    if hasattr(self, 'admin_messages') and message_id in self.admin_messages and admin_id in self.admin_messages[message_id]:
                        telegram_msg_id = self.admin_messages[message_id][admin_id]
                        # Restore standard moderation keyboard
                        keyboard = self.create_moderation_keyboard(message_id)
                        await self.bot_application.bot.edit_message_reply_markup(
                            chat_id=int(admin_id),
                            message_id=telegram_msg_id,
                            reply_markup=keyboard
                        )
                        logger.debug(f"✅ Restored buttons for admin {admin_id}")

                    # Send notification to ALL admins
                    await self.bot_application.bot.send_message(
                        chat_id=int(admin_id),
                        text=f"✅ @{current_admin_name} отменил редактирование {message_id}. Сообщение снова доступно для обработки."
                    )
                    notification_count += 1
                    logger.debug(f"✅ Sent cancel notification to admin {admin_id}")
                except Exception as e:
                    logger.error(f"❌ Failed to notify admin {admin_id}: {e}")

            logger.info(f"📢 Cancel notifications sent to {notification_count}/{len(Config.ADMIN_CHAT_IDS)} admins")

            chat_title = message.chat_title or "Личные сообщения"

            cancel_text = (
                f"❌ Редактирование отменено для сообщения {message_id}\n\n"
                f"📱 Чат: {chat_title}\n"
                f"👤 Пользователь: {message.username}\n"
                f"💬 Вопрос: {message.original_message[:200]}...\n\n"
                f"🤖 Ответ:\n{message.ai_response[:300]}..."
            )

            # Show main moderation keyboard
            keyboard = self.create_moderation_keyboard(message_id)
            await query.edit_message_text(cancel_text, reply_markup=keyboard)

        except Exception as e:
            logger.error(f"❌ Error in cancel edit handler: {e}")
            await query.edit_message_text("❌ Ошибка при отмене редактирования")

    async def handle_show_full_callback(self, query, message_id: str):
        """Handle show full message button callback."""
        try:
            admin_user_id = query.from_user.id
            admin_username = query.from_user.username or query.from_user.first_name

            logger.info(f"📖 SHOW_FULL_START: message_id='{message_id}', admin={admin_username} (ID: {admin_user_id})")

            # Force reload queue to ensure synchronization
            self.moderation_queue._load_data()
            logger.info(f"🔄 Queue reloaded for show full message")

            # Get message from queue
            message = self.moderation_queue.get_from_queue(message_id)
            if not message:
                logger.error(f"❌ SHOW_FULL_FAILED: message '{message_id}' not found in queue")
                await query.edit_message_text(f"❌ Сообщение {message_id} не найдено")
                return

            moscow_time = get_moscow_time()
            username = message.username or "Unknown"
            chat_title = message.chat_title or "Личные сообщения"

            # Create full message display (with length limits for Telegram)
            max_length = 3500  # Safe limit for Telegram messages

            full_text = (
                f"📖 Полное сообщение (ID: {message_id})\n\n"
                f"📱 Чат: {chat_title}\n"
                f"👤 Пользователь: {username}\n"
                f"⏰ Время: {moscow_time}\n\n"
                f"💬 ВОПРОС:\n{message.original_message}\n\n"
                f"🤖 ПОЛНЫЙ ОТВЕТ ИИ:\n{message.ai_response}"
            )

            # Truncate if too long for Telegram
            if len(full_text) > max_length:
                truncate_at = max_length - 200  # Leave space for truncation message
                full_text = full_text[:truncate_at] + "\n\n⚠️ (Сообщение обрезано из-за ограничений Telegram)"

            # Create keyboard with ALL moderation actions and hide button
            keyboard = [
                [
                    InlineKeyboardButton("✅ Отправить", callback_data=f"send_{message_id}"),
                    InlineKeyboardButton("❌ Отклонить", callback_data=f"reject_{message_id}")
                ],
                [
                    InlineKeyboardButton("🤖 ИИ-редактирование", callback_data=f"edit_{message_id}"),
                    InlineKeyboardButton("✍️ Ручное редактирование", callback_data=f"manual_edit_{message_id}")
                ],
                [
                    InlineKeyboardButton("📋 Копировать", callback_data=f"copy_{message_id}"),
                    InlineKeyboardButton("🔙 Скрыть полное сообщение", callback_data=f"hide_full_{message_id}")
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await query.edit_message_text(full_text, reply_markup=reply_markup)

            logger.info(f"📖 Show full message completed for {message_id}")

        except Exception as e:
            logger.error(f"❌ Error in show full message handler: {e}")
            await query.edit_message_text("❌ Ошибка при показе полного сообщения")

    async def handle_hide_full_callback(self, query, message_id: str):
        """Handle hide full message button callback - return to compact format."""
        try:
            admin_user_id = query.from_user.id
            admin_username = query.from_user.username or query.from_user.first_name

            logger.info(f"🔙 HIDE_FULL_START: message_id='{message_id}', admin={admin_username} (ID: {admin_user_id})")

            # Force reload queue to ensure synchronization
            self.moderation_queue._load_data()
            logger.info(f"🔄 Queue reloaded for hide full message")

            # Get message from queue
            message = self.moderation_queue.get_from_queue(message_id)
            if not message:
                logger.error(f"❌ HIDE_FULL_FAILED: message '{message_id}' not found in queue")
                await query.edit_message_text(f"❌ Сообщение {message_id} не найдено")
                return

            # Create compact format (like in pending_command)
            moscow_time = get_moscow_time()
            username = message.username or "Unknown"
            chat_title = message.chat_title or "Личные сообщения"
            text_preview = message.original_message[:100] + "..." if len(message.original_message) > 100 else message.original_message
            ai_response_preview = message.ai_response[:100] + "..." if len(message.ai_response) > 100 else message.ai_response

            compact_text = (
                f"🆔 ID: {message_id}\n"
                f"📱 Чат: {chat_title}\n"
                f"👤 Пользователь: {username}\n"
                f"⏰ Время: {moscow_time}\n"
                f"💬 Вопрос: {text_preview}\n"
                f"🤖 Ответ: {ai_response_preview}"
            )

            # Create keyboard with ALL moderation actions and show full button
            keyboard = [
                [
                    InlineKeyboardButton("✅ Отправить", callback_data=f"send_{message_id}"),
                    InlineKeyboardButton("❌ Отклонить", callback_data=f"reject_{message_id}")
                ],
                [
                    InlineKeyboardButton("🤖 ИИ-редактирование", callback_data=f"edit_{message_id}"),
                    InlineKeyboardButton("✍️ Ручное редактирование", callback_data=f"manual_edit_{message_id}")
                ],
                [
                    InlineKeyboardButton("📋 Копировать", callback_data=f"copy_{message_id}"),
                    InlineKeyboardButton("📖 Показать полное сообщение", callback_data=f"show_full_{message_id}")
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await query.edit_message_text(compact_text, reply_markup=reply_markup)

            logger.info(f"🔙 Hide full message completed for {message_id}")

        except Exception as e:
            logger.error(f"❌ Error in hide full message handler: {e}")
            await query.edit_message_text("❌ Ошибка при скрытии полного сообщения")

    async def handle_reset_question_callback(self, query, message_id: str):
        """Handle reset question button callback - save changes and release for other admins."""
        try:
            admin_user_id = query.from_user.id
            admin_username = query.from_user.username or query.from_user.first_name

            logger.info(f"🔄 RESET_QUESTION_START: message_id='{message_id}', admin={admin_username} (ID: {admin_user_id})")

            # Force reload queue to ensure synchronization
            self.moderation_queue._load_data()
            logger.info(f"🔄 Queue reloaded for reset question")

            # Get message from queue
            message = self.moderation_queue.get_from_queue(message_id)
            if not message:
                logger.error(f"❌ RESET_QUESTION_FAILED: message '{message_id}' not found in queue")
                await query.edit_message_text(f"❌ Сообщение {message_id} не найдено")
                return

            # Check if current admin is the one who has the lock
            if message.is_locked() and message.admin_processing != admin_user_id:
                admin_name = message.admin_name or "другим админом"
                await query.edit_message_text(
                    f"🔒 Сообщение {message_id} уже обрабатывается {admin_name}"
                )
                return

            # CRITICAL: The corrected message is ALREADY saved in moderation queue
            # (this happens in the correction processing flow before this callback)
            # So we just need to unlock the message and notify admins

            # 1. Clear all locks and states for this message
            message.unlock_editing()  # Clear moderation_service level lock

            # Clear admin_bot level locks if present
            if message.editing_admin_id == admin_user_id:
                message.editing_admin_id = None
                message.editing_admin_name = None
                message.editing_started_at = None

            # 2. Clear timeout tracking
            if self.admin_bot:
                self.admin_bot.clear_edit_timeout(message_id)
                logger.info(f"⏰ Cleared edit timeout for reset question: {message_id}")

            # 3. Clear correction state for this admin
            if admin_user_id in self.correction_states:
                del self.correction_states[admin_user_id]
                logger.info(f"🧹 Cleared correction state for admin {admin_user_id}")

            # 4. Save the updated message state
            self.moderation_queue._save_data()

            # 5. Send notification to ALL admins about reset
            notification_count = 0
            moscow_time = get_moscow_time()

            for admin_id in Config.ADMIN_CHAT_IDS:
                # Skip notification to the admin who performed the action (no self-notification)
                if admin_id == str(admin_user_id):
                    continue
                try:
                    reset_notification = (
                        f"🔄 **Сообщение возвращено в очередь модерации** {moscow_time}\n\n"
                        f"📝 Сообщение: {message_id}\n"
                        f"👤 Освободил: @{admin_username}\n"
                        f"💬 Вопрос: {message.original_message[:100]}{'...' if len(message.original_message) > 100 else ''}\n\n"
                        f"✨ **Сообщение отредактировано и готово к модерации**\n"
                        f"🔓 Теперь доступно для всех администраторов"
                    )

                    await self.bot_application.bot.send_message(
                        chat_id=int(admin_id),
                        text=reset_notification,
                        parse_mode='Markdown'
                    )
                    notification_count += 1
                    logger.info(f"🔔 Reset notification sent to admin {admin_id}")

                except Exception as e:
                    logger.error(f"❌ Failed to notify admin {admin_id} about reset: {e}")

            logger.info(f"🔔 RESET notifications sent to {notification_count} admins")

            # 6. Update current admin's interface to show success
            reset_success_text = (
                f"✅ Сообщение сброшено в очередь модерации {moscow_time}\n\n"
                f"📝 ID: {message_id}\n"
                f"💾 Отредактированная версия сохранена\n"
                f"🔓 Сообщение разблокировано\n"
                f"📢 Уведомления отправлены всем админам\n\n"
                f"ℹ️ Другие администраторы теперь могут модерировать этот вопрос"
            )

            await query.edit_message_text(reset_success_text)

            # 7. Clean up old admin messages to avoid UI confusion
            if self.admin_bot:
                # Delete old admin messages from chat to clean up interface
                await self.admin_bot.delete_admin_messages_from_chat(message_id)
                # Note: New messages will be sent automatically when someone queries /pending

            logger.info(f"🔄 QUESTION RESET COMPLETED: message {message_id} by admin {admin_username}")

        except Exception as e:
            logger.error(f"❌ Error in reset question handler: {e}")
            await query.edit_message_text("❌ Ошибка при сбросе вопроса")

    async def handle_clear_confirm_yes_callback(self, query):
        """Handle clear confirmation YES button callback - execute the clear operation."""
        try:
            admin_user_id = query.from_user.id
            admin_username = query.from_user.username or query.from_user.first_name

            logger.info(f"🧹 CLEAR_CONFIRM_YES: admin={admin_username} (ID: {admin_user_id})")

            # Check admin authorization
            if not Config.is_admin(admin_user_id):
                await query.edit_message_text("🚫 У вас нет прав администратора")
                return

            # Get count before clearing for confirmation message
            pending_count = self.moderation_queue.get_pending_count()

            if pending_count == 0:
                await query.edit_message_text("📭 Очередь модерации уже пуста")
                logger.info("🧹 Clear confirmed but queue already empty")
                return

            # Execute the clear operation
            cleared_count = self.moderation_queue.clear_all_pending()

            # Clear all active editing sessions
            sessions_cleared = len(self.correction_states)
            self.correction_states.clear()

            moscow_time = get_moscow_time()

            # Show success message
            success_text = (
                f"✅ **ОЧЕРЕДЬ МОДЕРАЦИИ ОЧИЩЕНА** {moscow_time}\n\n"
                f"🗑️ Удалено сообщений: **{cleared_count}**\n"
                f"🧹 Очищено активных сессий редактирования: **{sessions_cleared}**\n"
                f"👤 Выполнил: @{admin_username}\n\n"
                f"📭 Очередь модерации теперь пуста"
            )

            await query.edit_message_text(success_text, parse_mode='Markdown')

            # Send notification to ALL other admins about clear operation
            notification_count = 0
            for admin_id in Config.ADMIN_CHAT_IDS:
                # Skip notification to the admin who performed the action (no self-notification)
                if admin_id == str(admin_user_id):
                    continue
                try:
                    clear_notification = (
                        f"🧹 **Очередь модерации очищена** {moscow_time}\n\n"
                        f"🗑️ Удалено: **{cleared_count}** сообщений\n"
                        f"🧹 Очищено сессий редактирования: **{sessions_cleared}**\n"
                        f"👤 Выполнил: @{admin_username}\n\n"
                        f"📭 Очередь модерации пуста"
                    )

                    await self.bot_application.bot.send_message(
                        chat_id=int(admin_id),
                        text=clear_notification,
                        parse_mode='Markdown'
                    )
                    notification_count += 1
                    logger.info(f"🔔 Clear notification sent to admin {admin_id}")

                except Exception as e:
                    logger.error(f"❌ Failed to notify admin {admin_id} about clear: {e}")

            logger.info(f"🧹 CLEAR COMPLETED: {cleared_count} messages removed by admin {admin_username}")
            logger.info(f"🔔 Clear notifications sent to {notification_count} admins")

        except Exception as e:
            logger.error(f"❌ Error in clear confirm yes handler: {e}")
            await query.edit_message_text(f"❌ Ошибка при очистке очереди: {e}")

    async def handle_clear_confirm_no_callback(self, query):
        """Handle clear confirmation NO button callback - cancel the clear operation."""
        try:
            admin_user_id = query.from_user.id
            admin_username = query.from_user.username or query.from_user.first_name
            moscow_time = get_moscow_time()

            logger.info(f"🚫 CLEAR_CONFIRM_NO: admin={admin_username} (ID: {admin_user_id})")

            # Show cancellation message
            cancel_text = (
                f"❌ **ОЧИСТКА ОЧЕРЕДИ ОТМЕНЕНА** {moscow_time}\n\n"
                f"👤 Отменил: @{admin_username}\n"
                f"📋 Очередь модерации осталась без изменений\n\n"
                f"ℹ️ Для просмотра текущей очереди используйте /pending"
            )

            await query.edit_message_text(cancel_text, parse_mode='Markdown')

            logger.info(f"🚫 Clear operation cancelled by admin {admin_username}")

        except Exception as e:
            logger.error(f"❌ Error in clear confirm no handler: {e}")
            await query.edit_message_text("❌ Ошибка при отмене операции")


    async def process_with_correction_assistant(self, original_response: str, correction_text: str) -> Optional[str]:
        """Process correction using the correction service."""
        try:
            logger.info("🔧 Processing correction with CorrectionService...")

            # Use the dedicated correction service
            corrected_response = await self.correction_service.correct_message(
                original_text=original_response,
                correction_request=correction_text
            )

            if corrected_response:
                logger.info(f"✨ Correction completed: {corrected_response[:100]}...")
            else:
                logger.warning("❌ No corrected response received")

            return corrected_response

        except Exception as e:
            logger.error(f"❌ Error processing correction: {e}")
            return None

    async def process_correction(self, admin_user_id: int, correction_text: str, update: Update):
        """Process the correction input from admin."""
        try:
            if admin_user_id not in self.correction_states:
                await update.message.reply_text("❌ Нет активной корректировки")
                return

            correction_state = self.correction_states[admin_user_id]
            message_id = correction_state['message_id']
            original_message = correction_state['original_message']

            # Show processing message
            processing_msg = await update.message.reply_text("🔄 Обрабатываю корректировку через Correction Assistant...")

            # Process with correction assistant
            corrected_response = await self.process_with_correction_assistant(
                original_response=original_message.ai_response,
                correction_text=correction_text
            )

            if corrected_response:
                # Update the message in moderation queue
                message = self.moderation_queue.get_from_queue(message_id)
                if message:
                    message.ai_response = corrected_response
                    # Save the updated message to persistent storage
                    self.moderation_queue._save_data()
                    logger.info(f"💾 Updated message {message_id} saved to moderation queue")

                # Create keyboard for final decision
                keyboard = [
                    [
                        InlineKeyboardButton("✅ Отправить исправленный", callback_data=f"send_{message_id}"),
                        InlineKeyboardButton("✏️ Доработать еще", callback_data=f"edit_{message_id}")
                    ],
                    [
                        InlineKeyboardButton("❌ Отклонить", callback_data=f"reject_{message_id}")
                    ],
                    [
                        InlineKeyboardButton("🔄 Сбросить вопрос", callback_data=f"reset_question_{message_id}")
                    ]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)

                correction_result = (
                    f"✨ Корректировка завершена для сообщения {message_id}\n\n"
                    f"📝 Ваши корректировки:\n{correction_text}\n\n"
                    f"🤖 Исправленный ответ:\n{corrected_response[:1000]}{'...' if len(corrected_response) > 1000 else ''}"
                )

                await processing_msg.edit_text(correction_result, reply_markup=reply_markup)
                logger.info(f"✨ Correction completed for message {message_id}")

                # Clear correction state
                del self.correction_states[admin_user_id]

                # CRITICAL FIX: Clear edit timeout after correction completion
                # Without this, timeout continues and message auto-unlocks in 10 minutes
                if self.admin_bot:
                    self.admin_bot.clear_edit_timeout(message_id)
                    logger.info(f"⏰ Cleared edit timeout for completed correction: {message_id}")
                else:
                    logger.warning(f"⚠️ Could not clear edit timeout - admin_bot reference not available")

            else:
                await processing_msg.edit_text("❌ Не удалось обработать корректировку через Correction Assistant")

        except Exception as e:
            logger.error(f"❌ Error processing correction: {e}")
            await update.message.reply_text("❌ Ошибка при обработке корректировки")

    async def process_manual_correction(self, admin_user_id: int, correction_text: str, update: Update):
        """Process manual correction input from admin (direct text replacement without AI)."""
        try:
            if admin_user_id not in self.correction_states:
                await update.message.reply_text("❌ Нет активной корректировки")
                return

            correction_state = self.correction_states[admin_user_id]
            message_id = correction_state['message_id']
            original_message = correction_state['original_message']

            logger.info(f"✍️ MANUAL_CORRECTION processing for message {message_id}")
            logger.info(f"   📏 Original length: {len(original_message.ai_response)} chars")
            logger.info(f"   📏 New length: {len(correction_text)} chars")

            # Update the message in moderation queue with manual correction
            message = self.moderation_queue.get_from_queue(message_id)
            if message:
                message.ai_response = correction_text
                # Save the updated message to persistent storage
                self.moderation_queue._save_data()
                logger.info(f"💾 Updated message {message_id} with manual correction saved to queue")

            # Create comprehensive keyboard with all options (as per requirements)
            keyboard = [
                [
                    InlineKeyboardButton("✅ Отправить", callback_data=f"send_{message_id}"),
                    InlineKeyboardButton("❌ Отклонить", callback_data=f"reject_{message_id}")
                ],
                [
                    InlineKeyboardButton("🤖 ИИ-редактирование", callback_data=f"edit_{message_id}"),
                    InlineKeyboardButton("✍️ Ручное редактирование", callback_data=f"manual_edit_{message_id}")
                ],
                [
                    InlineKeyboardButton("📋 Копировать", callback_data=f"copy_{message_id}"),
                    InlineKeyboardButton("📖 Показать полное сообщение", callback_data=f"show_full_{message_id}")
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            chat_title = message.chat_title or "Личные сообщения"

            correction_result = (
                f"✅ **Ручное редактирование завершено** для сообщения {message_id}\n\n"
                f"📱 Чат: {chat_title}\n"
                f"👤 Пользователь: {message.username}\n"
                f"💬 Вопрос: {message.original_message}\n\n"
                f"📝 **Ваш исправленный текст:**\n{correction_text[:1000]}{'...' if len(correction_text) > 1000 else ''}\n\n"
                f"🎯 **Выберите действие:**\n"
                f"• Отправить пользователю\n"
                f"• Продолжить редактирование (ИИ или ручное)\n"
                f"• Отклонить сообщение"
            )

            await update.message.reply_text(correction_result, reply_markup=reply_markup, parse_mode='Markdown')
            logger.info(f"✍️ Manual correction completed for message {message_id}")

            # Clear correction state
            del self.correction_states[admin_user_id]

            # Clear edit timeout after correction completion
            if self.admin_bot:
                self.admin_bot.clear_edit_timeout(message_id)
                logger.info(f"⏰ Cleared edit timeout for completed manual correction: {message_id}")
            else:
                logger.warning(f"⚠️ Could not clear edit timeout - admin_bot reference not available")

        except Exception as e:
            logger.error(f"❌ Error processing manual correction: {e}")
            await update.message.reply_text("❌ Ошибка при обработке ручной корректировки")

    async def handle_return_to_manual_edit_callback(self, query, message_id: str):
        """Return from copy to manual editing mode."""
        try:
            admin_user_id = query.from_user.id
            message = self.moderation_queue.get_from_queue(message_id)
            if not message:
                await query.answer("❌ Сообщение не найдено", show_alert=True)
                return

            chat_title = message.chat_title or "Личные сообщения"

            edit_text = (
                f"✍️ **Режим ручного редактирования активирован** для сообщения {message_id}\n\n"
                f"📱 Чат: {chat_title}\n"
                f"👤 Пользователь: {message.username}\n"
                f"💬 Вопрос: {message.original_message}\n\n"
                f"🤖 Текущий ответ ИИ:\n{message.ai_response}\n\n"
                f"📝 **Отправьте ваш исправленный текст** в следующем сообщении.\n"
                f"После отправки вы увидите превью с возможностью:\n"
                f"• Отправить пользователю\n"
                f"• Продолжить редактирование\n"
                f"• Отклонить\n\n"
                f"💡 **Подсказка:** используйте кнопку \"📋 Копировать\" для получения текста ИИ"
            )

            keyboard = [
                [
                    InlineKeyboardButton("📋 Копировать текст ИИ", callback_data=f"copy_{message_id}"),
                    InlineKeyboardButton("❌ Отменить", callback_data=f"cancel_edit_{message_id}")
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await query.edit_message_text(edit_text, reply_markup=reply_markup, parse_mode='Markdown')
            await query.answer("✍️ Возврат к ручному редактированию", show_alert=False)
            logger.info(f"🔙 Returned to manual edit mode for message {message_id}")

        except Exception as e:
            logger.error(f"❌ Error returning to manual edit: {e}")
            await query.answer("❌ Ошибка при возврате к редактированию", show_alert=True)

    async def handle_return_to_edit_callback(self, query, message_id: str):
        """Return from copy to AI editing mode."""
        try:
            admin_user_id = query.from_user.id
            message = self.moderation_queue.get_from_queue(message_id)
            if not message:
                await query.answer("❌ Сообщение не найдено", show_alert=True)
                return

            chat_title = message.chat_title or "Личные сообщения"

            edit_text = (
                f"✏️ Режим корректировки активирован для сообщения {message_id}\n\n"
                f"📱 Чат: {chat_title}\n"
                f"👤 Пользователь: {message.username}\n"
                f"💬 Вопрос: {message.original_message}\n\n"
                f"🤖 Текущий ответ:\n{message.ai_response}\n\n"
                f"📝 Отправьте текстовое или голосовое сообщение с корректировками.\n"
                f"🎤 Голосовые сообщения будут обработаны через Whisper."
            )

            keyboard = [
                [
                    InlineKeyboardButton("❌ Отменить редактирование", callback_data=f"cancel_edit_{message_id}")
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await query.edit_message_text(edit_text, reply_markup=reply_markup)
            await query.answer("✏️ Возврат к ИИ редактированию", show_alert=False)
            logger.info(f"🔙 Returned to AI edit mode for message {message_id}")

        except Exception as e:
            logger.error(f"❌ Error returning to AI edit: {e}")
            await query.answer("❌ Ошибка при возврате к редактированию", show_alert=True)

    async def handle_voice_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle voice messages for corrections using WhisperService."""
        try:
            admin_user_id = update.message.from_user.id

            # Check if user is in correction state
            if admin_user_id not in self.correction_states:
                return  # Not in correction mode, ignore

            if not update.message.voice:
                return

            logger.info(f"🎤 Processing voice message from admin {admin_user_id}")

            # Show processing message
            processing_msg = await update.message.reply_text("🎤 Распознаю голосовое сообщение через Whisper...")

            try:
                # Transcribe voice message using WhisperService
                transcribed_text = await self.whisper_service.transcribe_voice(
                    voice_file=update.message.voice,
                    bot_context=context,
                    language='ru'
                )

                if transcribed_text and transcribed_text.strip():
                    logger.info(f"✅ Voice transcribed successfully: {transcribed_text[:100]}...")

                    # Show transcription result to admin
                    await processing_msg.edit_text(
                        f"🎤 Распознано: {transcribed_text}\n\n"
                        f"🔄 Обрабатываю как корректировку..."
                    )

                    # Process the transcribed text as regular correction
                    await self.process_correction(admin_user_id, transcribed_text, update)

                else:
                    logger.warning(f"❌ Voice transcription failed or returned empty text")
                    await processing_msg.edit_text(
                        "❌ Не удалось распознать голосовое сообщение.\n"
                        "Попробуйте еще раз или отправьте текстовое сообщение."
                    )

            except Exception as transcription_error:
                logger.error(f"❌ Voice transcription error: {transcription_error}")
                await processing_msg.edit_text(
                    "❌ Ошибка при распознавании голосового сообщения.\n"
                    "Попробуйте отправить текстовую корректировку."
                )

        except Exception as e:
            logger.error(f"❌ Error handling voice message: {e}")
            await update.message.reply_text("❌ Ошибка при обработке голосового сообщения")

    async def admin_message_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle general messages to admin bot."""
        if not update.message or not update.message.text:
            return

        admin_user_id = update.message.from_user.id
        message_text = update.message.text.strip()

        logger.info(f"💬 Admin message received from {admin_user_id}: {message_text[:100]}")

        # Check if admin is in correction state
        if admin_user_id in self.correction_states:
            correction_state = self.correction_states[admin_user_id]

            # Handle cancel command
            if message_text.lower() in ['/cancel', 'отмена', 'cancel']:
                message_id = correction_state['message_id']
                del self.correction_states[admin_user_id]
                await update.message.reply_text(f"❌ Корректировка для сообщения {message_id} отменена")
                logger.info(f"❌ Correction cancelled for message {message_id} by admin {admin_user_id}")
                return

            # Process text as AI-powered correction
            if correction_state['step'] == 'waiting_correction':
                await self.process_correction(admin_user_id, message_text, update)
                return

            # Process text as manual correction (direct text replacement)
            if correction_state['step'] == 'waiting_manual_correction':
                await self.process_manual_correction(admin_user_id, message_text, update)
                return


        # For regular messages not in correction state
        await update.message.reply_text("📝 Сообщение получено. Используйте команды для управления модерацией.")


    @staticmethod
    async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle errors in admin bot."""
        logger.error(f"❌ Admin bot error: {context.error}")

class AdminBot:
    """Main admin bot class."""

    def __init__(self, moderation_queue: Optional[ModerationQueue] = None):
        """Initialize the admin bot."""
        try:
            # Validate admin configuration
            Config.validate_admin_config()
            logger.info("✅ Admin configuration validated successfully")
        except ValueError as e:
            logger.error(f"❌ Admin configuration validation failed: {e}")
            raise

        self.application = Application.builder().token(Config.ADMIN_BOT_TOKEN).build()

        # Use provided moderation queue or get singleton instance
        if moderation_queue is not None:
            self.moderation_queue = moderation_queue
            logger.info("🔗 Using provided moderation queue instance")
        else:
            self.moderation_queue = get_moderation_queue()
            logger.info("🔗 Using singleton moderation queue instance")

        # Link this admin bot instance to the moderation queue for notifications
        self.moderation_queue.set_admin_bot(self)
        logger.info("🔗 Admin bot linked to moderation queue for notifications")

        # Admin message tracking for multi-admin synchronization
        # Format: admin_messages[message_id] = {admin_id_1: telegram_message_id_1, admin_id_2: telegram_message_id_2, ...}
        self.admin_messages: Dict[str, Dict[int, int]] = {}

        # Reminder settings for individual admins
        # Format: disabled_reminders[admin_id] = True (if reminders disabled)
        self.disabled_reminders: Dict[int, bool] = {}

        # Edit timeout tracking system
        # Format: edit_timeouts[message_id] = {'admin_id': int, 'admin_name': str, 'start_time': datetime}
        from datetime import datetime
        from typing import Dict, Optional
        self.edit_timeouts: Dict[str, Dict] = {}
        self.edit_timeout_duration = 600  # 10 minutes in seconds
        self.timeout_monitor_task: Optional[asyncio.Task] = None
        self.editing_timeout_task: Optional[asyncio.Task] = None

        self.setup_handlers()

    def setup_handlers(self):
        """Set up admin bot handlers."""
        # Initialize admin handlers
        self.admin_handlers = AdminHandlers(self.moderation_queue, self.application, self)

        # Command handlers
        self.application.add_handler(
            CommandHandler("start", self.admin_handlers.start_command)
        )
        self.application.add_handler(
            CommandHandler("status", self.admin_handlers.status_command)
        )
        self.application.add_handler(
            CommandHandler("pending", self.admin_handlers.pending_command)
        )
        self.application.add_handler(
            CommandHandler("approve", self.admin_handlers.approve_command)
        )
        self.application.add_handler(
            CommandHandler("reject", self.admin_handlers.reject_command)
        )
        self.application.add_handler(
            CommandHandler("stats", self.admin_handlers.stats_command)
        )
        self.application.add_handler(
            CommandHandler("clear", self.admin_handlers.clear_command)
        )

        self.application.add_handler(
            CommandHandler("notification_off", self.admin_handlers.notification_off_command)
        )
        self.application.add_handler(
            CommandHandler("notification_on", self.admin_handlers.notification_on_command)
        )
        # Callback query handler for inline buttons
        self.application.add_handler(
            CallbackQueryHandler(self.admin_handlers.button_callback_handler)
        )

        # General message handler
        self.application.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, self.admin_handlers.admin_message_handler)
        )

        # Voice message handler for corrections
        self.application.add_handler(
            MessageHandler(filters.VOICE, self.admin_handlers.handle_voice_message)
        )

        # Error handler
        self.application.add_error_handler(AdminHandlers.error_handler)

        logger.info("🔧 Admin handlers configured successfully")

    def get_moderation_queue(self) -> ModerationQueue:
        """Get access to moderation queue."""
        return self.moderation_queue

    async def notify_admin(self, message: str):
        """Send notification to all admin chats."""
        try:
            if Config.ADMIN_CHAT_IDS:
                for admin_id in Config.ADMIN_CHAT_IDS:
                    await self.application.bot.send_message(
                        chat_id=int(admin_id),
                        text=f"🔔 {message}"
                    )
                logger.info(f"🔔 Admin notification sent to {len(Config.ADMIN_CHAT_IDS)} admins: {message[:50]}...")
        except Exception as e:
            logger.error(f"❌ Failed to send admin notification: {e}")

    def store_admin_message(self, message_id: str, admin_id: int, telegram_message_id: int):
        """Store telegram message ID for admin message tracking."""
        if message_id not in self.admin_messages:
            self.admin_messages[message_id] = {}
        self.admin_messages[message_id][admin_id] = telegram_message_id
        logger.debug(f"📝 Stored admin message: mod_id={message_id}, admin={admin_id}, tg_msg={telegram_message_id}")

    def cleanup_admin_message(self, message_id: str):
        """Remove admin message tracking data after message is processed."""
        if message_id in self.admin_messages:
            del self.admin_messages[message_id]
            logger.debug(f"🗑️ Cleaned up admin message tracking for: {message_id}")

    async def delete_admin_messages_from_chat(self, message_id: str):
        """Delete all admin messages from Telegram chat to avoid UI confusion."""
        try:
            if message_id not in self.admin_messages:
                logger.debug(f"🗑️ No admin messages to delete for: {message_id}")
                return 0

            admin_message_ids = self.admin_messages[message_id]
            deleted_count = 0
            failed_count = 0

            logger.info(f"🗑️ Deleting {len(admin_message_ids)} admin messages for {message_id}")

            for admin_id, telegram_message_id in admin_message_ids.items():
                try:
                    await self.application.bot.delete_message(
                        chat_id=admin_id,
                        message_id=telegram_message_id
                    )
                    deleted_count += 1
                    logger.debug(f"✅ Deleted message {telegram_message_id} from admin {admin_id}")

                except Exception as delete_error:
                    failed_count += 1
                    # Don't log as error - message might already be deleted
                    logger.debug(f"⚠️ Could not delete message {telegram_message_id} from admin {admin_id}: {delete_error}")

            logger.info(f"🗑️ Message deletion results: {deleted_count} deleted, {failed_count} failed")
            return deleted_count

        except Exception as e:
            logger.error(f"❌ Error in delete_admin_messages_from_chat: {e}")
            return 0

    async def sync_message_status(self, message_id: str, new_status: str, admin_name: str):
        """
        Synchronize message status across all admin interfaces with enhanced button handling.

        Args:
            message_id: Moderation message ID
            new_status: Status action ('send', 'reject', 'edit')
            admin_name: Name of admin who performed the action
        """
        try:
            if message_id not in self.admin_messages:
                logger.warning(f"⚠️ No admin messages tracked for {message_id}")
                return

            admin_message_ids = self.admin_messages[message_id]
            logger.info(f"🔄 Syncing status '{new_status}' for {len(admin_message_ids)} admin messages")

            # Define status-specific text and button behavior
            if new_status == "send":
                status_text = f"✅ Отправлено админом @{admin_name}"
                reply_markup = None  # Remove buttons completely
            elif new_status == "reject":
                status_text = f"❌ Отклонено админом @{admin_name}"
                reply_markup = None  # Remove buttons completely
            elif new_status == "edit":
                status_text = f"✏️ Редактируется админом @{admin_name}"
                reply_markup = None  # Remove buttons completely
            else:
                logger.warning(f"⚠️ Unknown status: {new_status}")
                return

            # Update all admin messages
            successful_updates = 0
            for admin_id, telegram_message_id in admin_message_ids.items():
                try:
                    await self.application.bot.edit_message_text(
                        chat_id=admin_id,
                        message_id=telegram_message_id,
                        text=status_text,
                        reply_markup=reply_markup
                    )
                    successful_updates += 1
                    logger.debug(f"✅ Updated admin {admin_id} message {telegram_message_id}")

                except Exception as update_error:
                    logger.error(f"❌ Failed to update admin {admin_id} message {telegram_message_id}: {update_error}")

            logger.info(f"✅ Successfully updated {successful_updates}/{len(admin_message_ids)} admin messages")

            # Clean up tracking for completed actions (send/reject)
            if new_status in ["send", "reject"]:
                # Delete actual messages from chat to avoid UI confusion
                await self.delete_admin_messages_from_chat(message_id)
                # Then clean up tracking data
                self.cleanup_admin_message(message_id)

        except Exception as e:
            logger.error(f"❌ Error in sync_message_status: {e}")

    def start_edit_timeout(self, message_id: str, admin_id: int, admin_name: str):
        """Start timeout tracking for an edit operation."""
        from datetime import datetime
        self.edit_timeouts[message_id] = {
            'admin_id': admin_id,
            'admin_name': admin_name,
            'start_time': datetime.now()
        }
        logger.info(f"⏰ Started edit timeout for message {message_id} by admin {admin_name}")

    def clear_edit_timeout(self, message_id: str):
        """Clear timeout tracking for a message."""
        if message_id in self.edit_timeouts:
            del self.edit_timeouts[message_id]
            logger.debug(f"⏰ Cleared edit timeout for message {message_id}")

    async def check_edit_timeouts(self):
        """Check for expired edit timeouts and auto-unlock messages."""
        from datetime import datetime, timedelta

        current_time = datetime.now()
        expired_messages = []

        # Find expired timeouts
        for message_id, timeout_info in self.edit_timeouts.items():
            start_time = timeout_info['start_time']
            elapsed_seconds = (current_time - start_time).total_seconds()

            if elapsed_seconds >= self.edit_timeout_duration:
                expired_messages.append((message_id, timeout_info))

        # Process expired timeouts
        for message_id, timeout_info in expired_messages:
            await self.handle_edit_timeout_expiry(message_id, timeout_info)

    async def handle_edit_timeout_expiry(self, message_id: str, timeout_info: Dict):
        """Handle timeout expiry for an edit operation."""
        try:
            admin_id = timeout_info['admin_id']
            admin_name = timeout_info['admin_name']

            logger.warning(f"⏰ Edit timeout expired for message {message_id} (admin: {admin_name})")

            # 1. Get the message and unlock it
            message = self.moderation_queue.get_from_queue(message_id)
            if message and message.is_locked():
                message.unlock()
                logger.info(f"🔓 Auto-unlocked message {message_id} after timeout")

            # 2. Clear correction state for the admin
            if admin_id in self.admin_handlers.correction_states:
                del self.admin_handlers.correction_states[admin_id]
                logger.info(f"🧹 Cleared correction state for admin {admin_id}")

            # 3. Restore admin interface buttons with timeout notification
            await self.restore_admin_interface_after_timeout(message_id, admin_name)

            # 4. Clear timeout tracking
            self.clear_edit_timeout(message_id)

        except Exception as e:
            logger.error(f"❌ Error handling edit timeout expiry: {e}")

    async def restore_admin_interface_after_timeout(self, message_id: str, admin_name: str):
        """Restore admin interface buttons after edit timeout expiry."""
        try:
            if message_id not in self.admin_messages:
                logger.warning(f"⚠️ No admin messages tracked for {message_id} during timeout expiry")
                return

            admin_message_ids = self.admin_messages[message_id]
            timeout_text = f"⏰ Таймаут редактирования истек, сообщение снова доступно\n\n" \
                          f"Админ @{admin_name} не завершил редактирование в течение 10 минут."

            # Get original message for re-creating buttons
            message = self.moderation_queue.get_from_queue(message_id)
            if not message:
                logger.error(f"❌ Cannot restore interface: message {message_id} not found")
                return

            # Create original moderation keyboard
            keyboard = self.admin_handlers.create_moderation_keyboard(message_id)

            # Update all admin messages to restore functionality
            successful_updates = 0
            for admin_id, telegram_message_id in admin_message_ids.items():
                try:
                    await self.application.bot.edit_message_text(
                        chat_id=admin_id,
                        message_id=telegram_message_id,
                        text=timeout_text,
                        reply_markup=keyboard
                    )
                    successful_updates += 1
                    logger.debug(f"✅ Restored admin {admin_id} interface after timeout")

                except Exception as update_error:
                    logger.error(f"❌ Failed to restore admin {admin_id} interface: {update_error}")

            logger.info(f"✅ Restored {successful_updates}/{len(admin_message_ids)} admin interfaces after timeout")

        except Exception as e:
            logger.error(f"❌ Error restoring admin interface after timeout: {e}")

    async def start_timeout_monitor(self):
        """Start the background task for monitoring edit timeouts."""
        if self.timeout_monitor_task is not None:
            logger.warning("⚠️ Timeout monitor already running")
            return

        self.timeout_monitor_task = asyncio.create_task(self.timeout_monitor_loop())
        logger.info("⏰ Edit timeout monitor started")

    async def stop_timeout_monitor(self):
        """Stop the timeout monitoring task."""
        if self.timeout_monitor_task is not None:
            self.timeout_monitor_task.cancel()
            try:
                await self.timeout_monitor_task
            except asyncio.CancelledError:
                pass
            self.timeout_monitor_task = None
            logger.info("⏰ Edit timeout monitor stopped")

    async def timeout_monitor_loop(self):
        """Background loop for monitoring edit timeouts."""
        try:
            while True:
                await self.check_edit_timeouts()
                await asyncio.sleep(60)  # Check every minute
        except asyncio.CancelledError:
            logger.info("⏰ Timeout monitor loop cancelled")
        except Exception as e:
            logger.error(f"❌ Error in timeout monitor loop: {e}")

    async def check_editing_timeouts(self):
        """Проверяет таймауты редактирования каждую минуту"""
        try:
            while True:
                await asyncio.sleep(60)  # Проверка каждую минуту

                current_time = time.time()
                pending_messages = self.moderation_queue.get_pending_messages()

                for message_id, message in pending_messages.items():
                    if message.editing_admin_id:
                        # Если прошло больше 10 минут
                        if current_time - message.editing_started_at > 600:
                            # Снимаем блокировку
                            admin_name = message.editing_admin_name
                            message.editing_admin_id = None
                            message.editing_admin_name = None
                            message.editing_started_at = None

                            # Сохраняем изменения
                            self.moderation_queue._save_data()

                            logger.warning(f"⏰ Editing timeout expired for message {message_id} (admin: {admin_name})")

                            # Уведомляем всех админов (кроме тех, кто отключил напоминания)
                            for admin_id in Config.ADMIN_CHAT_IDS:
                                admin_id_int = int(admin_id)

                                # Skip if admin has disabled reminders
                                if admin_id_int in self.disabled_reminders:
                                    continue

                                try:
                                    await self.application.bot.send_message(
                                        chat_id=admin_id_int,
                                        text=f"⏰ Таймаут редактирования для @{admin_name}.\nСообщение {message_id} снова доступно."
                                    )
                                except Exception as e:
                                    logger.error(f"Failed to notify admin {admin_id} about timeout: {e}")

                            # Восстанавливаем кнопки
                            await self.restore_buttons_for_all(message_id)

        except asyncio.CancelledError:
            logger.info("⏰ Editing timeout monitor cancelled")
        except Exception as e:
            logger.error(f"❌ Error in editing timeout monitor: {e}")

    async def restore_buttons_for_all(self, message_id: str):
        """Восстанавливает кнопки для всех админов после таймаута"""
        try:
            if message_id not in self.admin_messages:
                logger.warning(f"⚠️ No admin messages tracked for {message_id}")
                return

            admin_message_ids = self.admin_messages[message_id]
            keyboard = self.admin_handlers.create_moderation_keyboard(message_id)

            # Получаем сообщение для отображения
            message = self.moderation_queue.get_from_queue(message_id)
            if not message:
                logger.error(f"❌ Message {message_id} not found for button restoration")
                return

            moscow_time = get_moscow_time()
            username = message.username or "Unknown"
            chat_title = message.chat_title or "Личные сообщения"
            text_preview = message.original_message[:100] + "..." if len(message.original_message) > 100 else message.original_message
            ai_response_preview = message.ai_response[:100] + "..." if len(message.ai_response) > 100 else message.ai_response

            restored_message_text = (
                f"🆔 ID: {message_id}\n"
                f"📱 Чат: {chat_title}\n"
                f"👤 Пользователь: {username}\n"
                f"⏰ Время: {moscow_time}\n"
                f"💬 Вопрос: {text_preview}\n"
                f"🤖 Ответ: {ai_response_preview}\n"
            )

            # Восстанавливаем кнопки для всех админов
            successful_updates = 0
            for admin_id, telegram_message_id in admin_message_ids.items():
                try:
                    await self.application.bot.edit_message_text(
                        chat_id=admin_id,
                        message_id=telegram_message_id,
                        text=restored_message_text,
                        reply_markup=keyboard
                    )
                    successful_updates += 1
                    logger.debug(f"✅ Restored buttons for admin {admin_id}")
                except Exception as e:
                    logger.error(f"❌ Failed to restore buttons for admin {admin_id}: {e}")

            logger.info(f"✅ Restored buttons for {successful_updates}/{len(admin_message_ids)} admins")

        except Exception as e:
            logger.error(f"❌ Error restoring buttons for all admins: {e}")

    async def update_all_admin_messages(self, message_id: str, action: str, admin_username: str):
        """
        Update all admin messages when one admin takes action.

        Args:
            message_id: Moderation message ID
            action: Action taken (send, reject, edit)
            admin_username: Username of admin who took action
        """
        try:
            if message_id not in self.admin_messages:
                logger.warning(f"⚠️ No admin messages tracked for {message_id}")
                logger.warning(f"🔍 Current tracked messages: {list(self.admin_messages.keys())}")
                return

            admin_message_ids = self.admin_messages[message_id]
            logger.info(f"🔄 Updating {len(admin_message_ids)} admin messages for {message_id}")
            logger.info(f"🎯 Admin IDs to update: {list(admin_message_ids.keys())}")

            # Create status text based on action
            if action == "send":
                status_text = f"✅ Отправлено админом @{admin_username} {get_moscow_time()}"
            elif action == "reject":
                status_text = f"❌ Отклонено админом @{admin_username} {get_moscow_time()}"
            elif action == "edit":
                status_text = f"🔒 Редактируется админом @{admin_username} (ИИ-редактирование)"
            elif action == "manual_edit":
                status_text = f"✍️ Редактируется админом @{admin_username} (ручное редактирование)"
            else:
                status_text = f"ℹ️ Обработано админом @{admin_username} {get_moscow_time()}"

            # Update all admin messages with individual error handling
            successful_updates = 0
            failed_updates = []

            for admin_id, telegram_message_id in admin_message_ids.items():
                try:
                    logger.debug(f"🔄 Updating admin {admin_id}, telegram msg {telegram_message_id}")

                    # For all actions, remove buttons entirely
                    reply_markup = None

                    await self.application.bot.edit_message_text(
                        chat_id=admin_id,
                        message_id=telegram_message_id,
                        text=status_text,
                        reply_markup=reply_markup
                    )
                    successful_updates += 1
                    logger.debug(f"✅ Successfully updated message for admin {admin_id}")

                except Exception as edit_error:
                    failed_updates.append(admin_id)
                    logger.error(f"❌ Failed to update message for admin {admin_id}: {edit_error}")
                    logger.error(f"❌ Admin ID type: {type(admin_id)}, Telegram msg ID: {telegram_message_id}")

            logger.info(f"✅ Admin message update results: {successful_updates} successful, {len(failed_updates)} failed")
            if failed_updates:
                logger.error(f"❌ Failed admin IDs: {failed_updates}")

            # Only clean up tracking if we successfully updated at least one admin
            # Keep tracking for edit actions to allow restoration later
            if action in ["send", "reject"] and successful_updates > 0:
                # Delete actual messages from chat to avoid UI confusion
                await self.delete_admin_messages_from_chat(message_id)
                # Then clean up tracking data
                self.cleanup_admin_message(message_id)
            elif action in ["send", "reject"] and successful_updates == 0:
                logger.warning(f"⚠️ Keeping tracking data for {message_id} due to update failures")

        except Exception as e:
            logger.error(f"❌ Critical error updating admin messages: {e}")
            logger.error(f"❌ Error type: {type(e).__name__}")
            import traceback
            logger.error(f"❌ Traceback: {traceback.format_exc()}")

    async def start(self):
        """Start the admin bot."""
        logger.info("🚀 Starting Admin Bot...")
        await self.application.initialize()
        await self.application.start()
        await self.application.updater.start_polling()

        # Start editing timeout monitor
        self.editing_timeout_task = asyncio.create_task(self.check_editing_timeouts())
        logger.info("⏰ Editing timeout monitor started")

        # Send startup notification
        await self.notify_admin("Админ-бот запущен и готов к работе!")

        logger.info("🔧 Admin Bot is running. Press Ctrl+C to stop.")

        try:
            # Keep the bot running
            await asyncio.Event().wait()
        except KeyboardInterrupt:
            logger.info("⏹️ Received interrupt signal")
        finally:
            await self.stop()

    async def stop(self):
        """Stop the admin bot."""
        logger.info("⏹️ Stopping admin bot...")

        # Stop editing timeout monitor
        if self.editing_timeout_task:
            self.editing_timeout_task.cancel()
            try:
                await self.editing_timeout_task
            except asyncio.CancelledError:
                pass
            logger.info("⏰ Editing timeout monitor stopped")

        # Send shutdown notification
        await self.notify_admin("Админ-бот остановлен")

        await self.application.updater.stop()
        await self.application.stop()
        await self.application.shutdown()
        logger.info("🔧 Admin bot stopped")

async def main():
    """Main function."""
    try:
        admin_bot = AdminBot()
        await admin_bot.start()
    except ValueError as e:
        logger.error(f"❌ Configuration error: {e}")
        logger.error("💡 Hint: Configure ADMIN_BOT_TOKEN and ADMIN_CHAT_IDS in .env file")
    except Exception as e:
        logger.error(f"❌ Unexpected admin bot error: {e}")
        raise

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("🔧 Admin bot stopped by user")
    except Exception as e:
        logger.error(f"❌ Fatal admin bot error: {e}")
        raise