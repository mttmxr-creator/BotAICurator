import logging
import time
import asyncio
from typing import Optional, Dict, Any
from telegram import Update
from telegram.ext import ContextTypes

from config import Config
from services.openai_service import OpenAIService
from services.lightrag_service import LightRAGService
from services.moderation_service import add_to_moderation_queue
from services.message_filter import get_message_filter
from services.qa_logger import log_qa_interaction
from utils.text_utils import strip_markdown

logger = logging.getLogger(__name__)

class PriorityMessageQueue:
    """Smart priority queue for message processing with user-based prioritization."""

    def __init__(self, max_workers=3):
        self.queue = asyncio.PriorityQueue()
        self.user_last_processed = {}  # Когда последний раз обработали user_id
        self.workers = []
        self.max_workers = max_workers
        self.is_running = False
        self.handler_instance = None  # Reference to MessageHandlers instance

    def set_handler(self, handler):
        """Set reference to MessageHandlers instance for message processing."""
        self.handler_instance = handler

    async def add_message(self, message_data: Dict[str, Any], user_id: int):
        """Add message to priority queue with intelligent prioritization."""
        current_time = time.time()

        # Рассчитываем приоритет (чем меньше число, тем выше приоритет)
        if user_id not in self.user_last_processed:
            priority = 0  # Новый пользователь - высокий приоритет
            logger.debug(f"🔝 New user {user_id} - priority 0")
        else:
            # Чем дольше не обрабатывали - тем выше приоритет
            time_since_last = current_time - self.user_last_processed[user_id]
            if time_since_last > 300:  # Больше 5 минут назад
                priority = 1
                logger.debug(f"⏰ User {user_id} last seen {time_since_last:.0f}s ago - priority 1")
            elif time_since_last > 60:  # Больше минуты назад
                priority = 2
                logger.debug(f"⏰ User {user_id} last seen {time_since_last:.0f}s ago - priority 2")
            else:
                priority = 3  # Недавно обрабатывали - низкий приоритет
                logger.debug(f"⏰ User {user_id} processed recently - priority 3")

        # Добавляем timestamp как tie-breaker для одинаковых приоритетов
        await self.queue.put((priority, current_time, message_data))
        queue_size = self.queue.qsize()

        logger.info(f"📥 Message queued: priority={priority}, user={user_id}, queue_size={queue_size}")

    async def process_messages(self):
        """Main worker loop for processing messages from the queue."""
        worker_id = len(self.workers)
        logger.info(f"🏃‍♂️ Worker {worker_id} started")

        while self.is_running:
            try:
                # Get message from queue with timeout to allow clean shutdown
                try:
                    priority, timestamp, message_data = await asyncio.wait_for(
                        self.queue.get(), timeout=1.0
                    )
                except asyncio.TimeoutError:
                    continue  # Check if still running

                user_id = message_data['user_id']
                queue_size = self.queue.qsize()

                logger.info(f"⚡ Worker {worker_id} processing: priority={priority}, user={user_id}, remaining={queue_size}")

                # Обновляем время последней обработки
                self.user_last_processed[user_id] = time.time()

                # Обрабатываем сообщение через handler instance
                if self.handler_instance:
                    await self.process_single_message(message_data)
                else:
                    logger.error("❌ No handler instance set for queue processing")

                # Mark task as done
                self.queue.task_done()

            except Exception as e:
                logger.error(f"❌ Worker {worker_id} error: {e}")
                # Continue processing other messages

        logger.info(f"⏹️ Worker {worker_id} stopped")

    async def process_single_message(self, message_data: Dict[str, Any]):
        """Process a single message using the handler instance."""
        try:
            update = message_data['update']
            context = message_data['context']

            # Call the original message processing logic
            await self.handler_instance._process_message_internal(update, context)

        except Exception as e:
            logger.error(f"❌ Error processing queued message: {e}")

    async def start_workers(self):
        """Start worker tasks for processing the queue."""
        if self.is_running:
            logger.warning("⚠️ Workers already running")
            return

        self.is_running = True
        self.workers = []

        for i in range(self.max_workers):
            worker = asyncio.create_task(self.process_messages())
            self.workers.append(worker)

        logger.info(f"🚀 Started {self.max_workers} queue workers")

    async def stop_workers(self):
        """Stop all worker tasks gracefully."""
        if not self.is_running:
            return

        logger.info("⏹️ Stopping queue workers...")
        self.is_running = False

        # Wait for workers to finish
        if self.workers:
            await asyncio.gather(*self.workers, return_exceptions=True)

        self.workers = []
        logger.info("✅ All queue workers stopped")

    def get_stats(self) -> Dict[str, Any]:
        """Get queue statistics."""
        return {
            'queue_size': self.queue.qsize(),
            'active_workers': len(self.workers),
            'is_running': self.is_running,
            'total_users_processed': len(self.user_last_processed),
            'max_workers': self.max_workers
        }

class MessageHandlers:
    """Message handlers for the Telegram bot."""

    def __init__(self, main_bot=None, queue_workers=3, auto_start_queue=True):
        """Initialize message handlers with OpenAI and LightRAG services."""
        self.openai_service = OpenAIService()
        self.lightrag_service = LightRAGService()
        self.message_filter = get_message_filter()
        self.main_bot = main_bot  # Reference to main bot for storing message references

        # Initialize priority queue for smart message processing
        self.priority_queue = PriorityMessageQueue(max_workers=queue_workers)
        self.priority_queue.set_handler(self)
        self.auto_start_queue = auto_start_queue

        logger.info(f"📋 Message handlers initialized with {queue_workers} queue workers")

    async def initialize(self):
        """Initialize async components (call this after creating the handler)."""
        if self.auto_start_queue:
            await self.start_queue()

    def send_to_moderation_queue(self, response: str, user_info: dict, original_message: str,
                                original_message_id: Optional[int] = None) -> str:
        """
        Send AI response to moderation queue instead of directly to user.

        Args:
            response: AI-generated response
            user_info: Dictionary containing user context (chat_id, user_id, username)
            original_message: Original user message text
            original_message_id: Telegram message ID to reply to (for group chats)

        Returns:
            Message ID for tracking in moderation queue
        """
        try:
            # Extract user context
            chat_id = user_info.get('chat_id')
            user_id = user_info.get('user_id')
            username = user_info.get('username')

            # Send to moderation queue
            message_id = add_to_moderation_queue(
                chat_id=chat_id,
                user_id=user_id,
                username=username,
                original_message=original_message,
                ai_response=response,
                original_message_id=original_message_id
            )

            logger.info(f"📤 Response sent to moderation queue:")
            logger.info(f"   🆔 Moderation ID: {message_id}")
            logger.info(f"   👤 User: {username} ({user_id})")
            logger.info(f"   💬 Chat: {chat_id}")
            logger.info(f"   📄 Response length: {len(response)} chars")

            return message_id

        except Exception as e:
            logger.error(f"❌ Failed to send response to moderation: {e}")
            raise

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        Handle incoming messages by adding them to the priority queue for processing.

        COMPREHENSIVE DIAGNOSTIC LOGGING ADDED to capture ALL message reception.

        Args:
            update: Telegram update object
            context: Telegram context object
        """
        # ==========================================
        # CRITICAL DIAGNOSTIC LOGGING - CAPTURES ALL MESSAGES BOT RECEIVES
        # ==========================================

        logger.info("🔥🔥🔥 ========== MESSAGE RECEPTION DIAGNOSTIC ========== 🔥🔥🔥")

        # Log EVERY update that reaches this handler
        if update:
            logger.info(f"📨 UPDATE RECEIVED: update_id={getattr(update, 'update_id', 'UNKNOWN')}")

            if update.message:
                user = update.message.from_user
                chat = update.message.chat

                logger.info(f"👤 USER INFO:")
                logger.info(f"   📋 User ID: {user.id}")
                logger.info(f"   📛 Username: {user.username}")
                logger.info(f"   📝 First Name: {user.first_name}")
                logger.info(f"   📝 Last Name: {user.last_name}")
                logger.info(f"   🤖 Is Bot: {user.is_bot}")

                logger.info(f"💬 CHAT INFO:")
                logger.info(f"   📋 Chat ID: {chat.id}")
                logger.info(f"   🏷️ Chat Type: {chat.type}")
                logger.info(f"   📛 Chat Title: {getattr(chat, 'title', 'N/A')}")

                logger.info(f"📄 MESSAGE INFO:")
                logger.info(f"   📋 Message ID: {update.message.message_id}")
                logger.info(f"   📝 Text: '{update.message.text}'")
                logger.info(f"   📏 Text Length: {len(update.message.text) if update.message.text else 0}")
                logger.info(f"   📅 Date: {update.message.date}")

                # Check admin status for this user
                is_admin = Config.is_admin(user.id)
                logger.info(f"🔑 ADMIN STATUS: {is_admin}")
                logger.info(f"🔑 ADMIN LIST: {Config.ADMIN_CHAT_IDS}")

            else:
                logger.info("❌ UPDATE HAS NO MESSAGE OBJECT")
        else:
            logger.info("❌ NO UPDATE OBJECT RECEIVED")

        logger.info("🔥🔥🔥 ================================================== 🔥🔥🔥")

        # Original filtering logic continues here...
        if not update.message or not update.message.text:
            logger.info("❌ EARLY EXIT: No message or no text")
            return

        # Basic chat type filtering before queueing
        if update.message.chat.type == 'private':
            logger.info("❌ EARLY EXIT: Private message ignored")
            return  # Игнорируем личные сообщения полностью

        if update.message.chat.type not in ['group', 'supergroup']:
            logger.info(f"❌ EARLY EXIT: Unsupported chat type: {update.message.chat.type}")
            return  # Работаем только в группах

        user_id = update.message.from_user.id

        # Ignore messages from admins to prevent processing admin replies as questions
        if Config.is_admin(user_id):
            logger.info(f"⛔ ADMIN MESSAGE IGNORED: Admin {user_id} message skipped in group chat")
            return

        message_data = {
            'update': update,
            'context': context,
            'user_id': user_id,
            'message_text': update.message.text.strip(),
            'timestamp': time.time()
        }

        logger.info(f"✅ MESSAGE PASSED INITIAL FILTERING - Adding to queue for user {user_id}")

        # Add to priority queue for processing
        await self.priority_queue.add_message(message_data, user_id)

    async def _process_message_internal(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        Internal message processing logic - called by queue workers:
        1. Length check (< 10 chars → ignore)
        2. Relevance check (filter → ignore if irrelevant)
        3. Process through RAG → send to moderation silently

        Args:
            update: Telegram update object
            context: Telegram context object
        """
        if not update.message or not update.message.text:
            return

        message_text = update.message.text.strip()

        logger.info(f"📥 ПОЛУЧЕН ВОПРОС: '{message_text[:100]}{'...' if len(message_text) > 100 else ''}', длина: {len(message_text)}, от пользователя: {update.message.from_user.id}")

        # Step 1: Length check - ignore short messages
        if len(message_text) < 10:
            logger.info(f"❌ ОТКЛОНЕНО ПО ДЛИНЕ: Получен вопрос: '{message_text}', длина: {len(message_text)}, релевантность: не_проверялось (слишком_короткий)")
            return

        # Step 2: Basic relevance check using filter
        try:
            should_process = await self.message_filter.should_process(
                message_text,
                update.message.from_user.id,
                update.effective_chat.id
            )
        except Exception as e:
            logger.error(f"❌ Error in message filtering: {e}")
            # Default to not processing on filter error
            should_process = False

        if not should_process:
            logger.info(f"❌ ОТКЛОНЕНО ПО РЕЛЕВАНТНОСТИ: Получен вопрос: '{message_text[:100]}...', длина: {len(message_text)}, релевантность: НЕТ")
            return

        # Log successful processing start
        logger.info(f"✅ ПРИНЯТО К ОБРАБОТКЕ: Получен вопрос: '{message_text[:100]}...', длина: {len(message_text)}, релевантность: ДА")

        # Step 3: Process relevant message through RAG pipeline
        logger.info("✅ Message relevant - processing through RAG pipeline")

        # Store original message reference for later reply
        if self.main_bot:
            self.main_bot.store_original_message_reference(
                chat_id=update.effective_chat.id,
                user_id=update.message.from_user.id,
                message_id=update.message.message_id
            )

        try:
            processing_start_time = time.time()

            logger.info("="*80)
            logger.info("🔍 STARTING REQUEST PROCESSING")
            logger.info(f"📝 Original user query: '{message_text}'")
            logger.info("="*80)

            # Search for relevant information in LightRAG
            logger.info("🔍 STEP 1: Searching LightRAG...")
            rag_context = await self.lightrag_service.query(message_text)

            if rag_context and rag_context.strip():
                logger.info(f"✅ LightRAG Response Found:")
                logger.info(f"📊 Length: {len(rag_context)} chars")
                logger.info(f"📄 First 500 chars: {rag_context[:500]}{'...' if len(rag_context) > 500 else ''}")
                context_message = f"Вопрос пользователя: {message_text}\n\nИнформация из базы знаний:\n{rag_context}"
            else:
                logger.warning("❌ No relevant information found in LightRAG")
                context_message = f"Вопрос пользователя: {message_text}\n\nИнформация из базы знаний: null"

            # Send combined query to OpenAI Assistant
            logger.info("🔍 STEP 2: Sending to OpenAI Assistant...")
            assistant_response = await self.openai_service.process_query(context_message)

            if not assistant_response:
                logger.error("❌ No response from OpenAI Assistant")
                return

            logger.info(f"✅ OpenAI Assistant Response:")
            logger.info(f"📊 Response length: {len(assistant_response)} chars")

            # Strip markdown formatting before moderation
            clean_response = strip_markdown(assistant_response)

            # Prepare user context for moderation
            user_info = {
                'chat_id': update.effective_chat.id,
                'user_id': update.message.from_user.id,
                'username': update.message.from_user.username or update.message.from_user.first_name
            }

            # Log successful QA interaction (only if valid context was found)
            if rag_context and rag_context.strip() and "null" not in context_message.lower():
                try:
                    processing_duration = int((time.time() - processing_start_time) * 1000)
                    log_qa_interaction(
                        question=message_text,
                        answer=clean_response,
                        context=rag_context,
                        user_info=user_info,
                        processing_time_ms=processing_duration,
                        original_message_length=len(message_text),
                        cleaned_response_length=len(clean_response),
                        lightrag_context_length=len(rag_context)
                    )
                    logger.info(f"📝 QA interaction logged successfully (duration: {processing_duration}ms)")
                except Exception as qa_log_error:
                    logger.error(f"❌ Failed to log QA interaction: {qa_log_error}")

            # Send to moderation queue silently (no user notification)
            try:
                moderation_id = self.send_to_moderation_queue(
                    response=clean_response,
                    user_info=user_info,
                    original_message=message_text,
                    original_message_id=update.message.message_id
                )
                logger.info(f"🔄 RESPONSE SENT TO MODERATION (ID: {moderation_id})")
                logger.info("="*80)
            except Exception as moderation_error:
                logger.error(f"❌ Moderation failed: {moderation_error}")

        except Exception as e:
            logger.error(f"❌ Error processing request: {e}")
            # No error message to user - just log the error

    @staticmethod
    async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        Handle the /start command.

        Args:
            update: Telegram update object
            context: Telegram context object
        """
        welcome_message = (
            "Привет! Я бот-куратор Екатерина.\n"
            "Просто задавайте мне рабочие вопросы - я автоматически определяю, "
            "какие сообщения относятся к работе и документации!"
        )

        try:
            await update.message.reply_text(welcome_message)
            logger.info(f"Start command handled for user {update.message.from_user.id}")
        except Exception as e:
            logger.error(f"Error handling start command: {e}")

    @staticmethod
    async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        Handle errors that occur during bot operation.

        Args:
            update: Telegram update object
            context: Telegram context object
        """
        logger.error(f"Update {update} caused error {context.error}")

        # Don't send error messages to users for now
        # In production, you might want to send a generic error message

    async def start_queue(self):
        """Start the priority queue workers."""
        await self.priority_queue.start_workers()
        logger.info("🚀 Message processing queue started")

    async def stop_queue(self):
        """Stop the priority queue workers gracefully."""
        await self.priority_queue.stop_workers()
        logger.info("⏹️ Message processing queue stopped")

    def get_queue_stats(self) -> Dict[str, Any]:
        """Get statistics about the message processing queue."""
        return self.priority_queue.get_stats()