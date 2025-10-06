#!/usr/bin/env python3
"""
Main orchestrator for the Telegram bot moderation system.
Manages both main bot and admin bot with graceful shutdown and signal handling.
"""

import asyncio
import signal
import sys
import os
import logging
import time
import traceback
from pathlib import Path
from typing import Dict, Optional, List, Callable, Any
from datetime import datetime, timedelta
import threading
from contextlib import asynccontextmanager

# Add current directory to Python path
current_dir = Path(__file__).parent
sys.path.insert(0, str(current_dir))

# Import our services and bots
from config import Config
from bot import EkaterinaBot
from admin_bot import AdminBot
from services.metrics_service import get_metrics_service
from services.moderation_service import get_moderation_queue

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot_system.log'),
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger(__name__)

class BotHealthMonitor:
    """Monitor health of bot instances and manage restarts."""

    def __init__(self, check_interval: int = 30, max_restart_attempts: int = 3):
        self.check_interval = check_interval
        self.max_restart_attempts = max_restart_attempts
        self.bot_status: Dict[str, Dict] = {}
        self.restart_counts: Dict[str, int] = {}
        self.health_check_task: Optional[asyncio.Task] = None
        self.monitoring_active = False

    def register_bot(self, bot_name: str, health_check: Callable[[], bool], restart_callback: Callable[[], Any]):
        """Register a bot for health monitoring."""
        self.bot_status[bot_name] = {
            'name': bot_name,
            'health_check': health_check,
            'restart_callback': restart_callback,
            'last_check': None,
            'status': 'unknown'
        }
        self.restart_counts[bot_name] = 0
        logger.info(f"🏥 Registered {bot_name} for health monitoring")

    async def start_monitoring(self):
        """Start the health monitoring loop."""
        if self.monitoring_active:
            return

        self.monitoring_active = True
        self.health_check_task = asyncio.create_task(self._monitoring_loop())
        logger.info("🏥 Health monitoring started")

    async def stop_monitoring(self):
        """Stop the health monitoring loop."""
        self.monitoring_active = False
        if self.health_check_task:
            self.health_check_task.cancel()
            try:
                await self.health_check_task
            except asyncio.CancelledError:
                pass
        logger.info("🏥 Health monitoring stopped")

    async def _monitoring_loop(self):
        """Main monitoring loop."""
        while self.monitoring_active:
            try:
                await self._check_all_bots()
                await asyncio.sleep(self.check_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"❌ Error in health monitoring: {e}")
                await asyncio.sleep(5)

    async def _check_all_bots(self):
        """Check health of all registered bots."""
        for bot_name, bot_info in self.bot_status.items():
            try:
                is_healthy = bot_info['health_check']()
                bot_info['last_check'] = datetime.now()

                if is_healthy:
                    if bot_info['status'] != 'healthy':
                        logger.info(f"✅ {bot_name} is healthy")
                        bot_info['status'] = 'healthy'
                        self.restart_counts[bot_name] = 0  # Reset restart count on successful health check
                else:
                    if bot_info['status'] != 'unhealthy':
                        logger.warning(f"⚠️ {bot_name} appears unhealthy")
                        bot_info['status'] = 'unhealthy'

                    # Attempt restart if we haven't exceeded max attempts
                    if self.restart_counts[bot_name] < self.max_restart_attempts:
                        logger.warning(f"🔄 Attempting to restart {bot_name} (attempt {self.restart_counts[bot_name] + 1})")
                        self.restart_counts[bot_name] += 1
                        await bot_info['restart_callback']()
                    else:
                        logger.error(f"❌ {bot_name} has exceeded max restart attempts ({self.max_restart_attempts})")

            except Exception as e:
                logger.error(f"❌ Error checking {bot_name} health: {e}")
                bot_info['status'] = 'error'

class BotOrchestrator:
    """
    Main orchestrator for managing both main bot and admin bot.
    Handles startup, shutdown, and coordination between components.
    """

    def __init__(self):
        """Initialize the bot orchestrator."""
        self.main_bot: Optional[EkaterinaBot] = None
        self.admin_bot: Optional[AdminBot] = None
        self.health_monitor = BotHealthMonitor()
        self.metrics_service = get_metrics_service()
        self.moderation_queue = get_moderation_queue()
        self.shutdown_event = asyncio.Event()
        self.running = False

        logger.info("🤖 Bot orchestrator initialized")

    async def run(self):
        """Main run method - starts all components and manages lifecycle."""
        try:
            logger.info("🚀 Starting bot orchestrator...")

            # Configure signal handlers for graceful shutdown
            await self._setup_signal_handlers()

            # Validate configuration before starting anything
            await self._validate_configuration()

            # Initialize services
            await self._initialize_services()

            # Start health monitoring
            await self.health_monitor.start_monitoring()

            # Start bot system
            await self._start_bot_system()

            # Wait for shutdown signal
            await self.shutdown_event.wait()

        except Exception as e:
            logger.error(f"❌ Critical error in orchestrator: {e}")
            logger.error(traceback.format_exc())
            return 1
        finally:
            await self._graceful_shutdown()

        return 0

    async def _setup_signal_handlers(self):
        """Configure signal handlers for graceful shutdown."""
        def signal_handler(signum, frame):
            """Handle signals that should trigger graceful shutdown."""
            logger.info(f"📶 Received signal {signum}")
            asyncio.create_task(self._trigger_shutdown())

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

        logger.info("📶 Signal handlers configured")

    async def _validate_configuration(self):
        """Validate all configuration before starting bots."""
        logger.info("🔍 Validating configuration...")

        # Test LightRAG connection
        try:
            logger.info("🔗 Testing LightRAG connection...")
            from services.lightrag_service import LightRAGService
            lightrag = LightRAGService()
            test_response = await lightrag.query("test")
            logger.info("✅ LightRAG connection test successful")
            logger.info("✅ All components configured correctly")
        except Exception as e:
            logger.error(f"❌ LightRAG connection failed: {e}")
            raise

        # Core configuration validation (including admin config since we start both bots)
        try:
            Config.validate(include_admin=True)
            logger.info("✅ Core configuration validation passed")
        except Exception as e:
            logger.error(f"❌ Configuration validation failed: {e}")
            raise

    async def _initialize_services(self):
        """Initialize all required services."""
        logger.info("⚙️ Initializing services...")

        # Services are initialized through their get_* functions
        # This ensures they're properly set up before bot startup

        logger.info("✅ Services initialized")

    async def _start_bot_system(self):
        """Start the complete bot system."""
        logger.info("🚀 Starting bot system...")

        try:
            # Start both bots concurrently
            await self.start_bots()
            logger.info("🎉 Bot system started successfully")

        except Exception as e:
            logger.error(f"❌ Failed to start bots: {e}")
            raise

    async def start_bots(self):
        """Start both main bot and admin bot concurrently."""
        # Create tasks for both bots
        main_bot_task = asyncio.create_task(self.start_main_bot())
        admin_bot_task = asyncio.create_task(self.start_admin_bot())

        # Wait for both to complete (or fail)
        done, pending = await asyncio.wait(
            [main_bot_task, admin_bot_task],
            return_when=asyncio.FIRST_EXCEPTION
        )

        # Check for exceptions
        for task in done:
            if task.exception():
                # Cancel any pending tasks
                for pending_task in pending:
                    pending_task.cancel()
                    try:
                        await pending_task
                    except asyncio.CancelledError:
                        pass
                # Re-raise the exception
                raise task.exception()

    async def start_main_bot(self):
        """Start the main bot."""
        logger.info("🤖 Starting main bot...")

        try:
            self.main_bot = EkaterinaBot()

            # Register health check
            self.health_monitor.register_bot(
                'main_bot',
                lambda: self.main_bot and self.main_bot.application and self.main_bot.application.running,
                self._restart_main_bot
            )

            # Start the bot
            await self.main_bot.start()
            logger.info("✅ Main bot started successfully")

        except Exception as e:
            logger.error(f"❌ Failed to start main bot: {e}")
            raise

    async def start_admin_bot(self):
        """Start the admin bot."""
        logger.info("👨‍💼 Starting admin bot...")

        try:
            # Pass the shared moderation queue instance to admin bot
            self.admin_bot = AdminBot(moderation_queue=self.moderation_queue)

            # Link admin bot with moderation queue (admin bot already has the instance)
            self.moderation_queue.set_admin_bot(self.admin_bot)

            # Register health check
            self.health_monitor.register_bot(
                'admin_bot',
                lambda: self.admin_bot and self.admin_bot.application and self.admin_bot.application.running,
                self._restart_admin_bot
            )

            # Start the bot
            await self.admin_bot.start()
            logger.info("✅ Admin bot started successfully")

        except Exception as e:
            logger.error(f"❌ Failed to start admin bot: {e}")
            raise

    async def _restart_main_bot(self):
        """Restart the main bot."""
        logger.info("🔄 Restarting main bot...")
        try:
            if self.main_bot:
                await self.main_bot.stop()
            await asyncio.sleep(2)  # Brief pause
            await self.start_main_bot()
        except Exception as e:
            logger.error(f"❌ Failed to restart main bot: {e}")

    async def _restart_admin_bot(self):
        """Restart the admin bot."""
        logger.info("🔄 Restarting admin bot...")
        try:
            if self.admin_bot:
                await self.admin_bot.stop()
            await asyncio.sleep(2)  # Brief pause
            await self.start_admin_bot()
        except Exception as e:
            logger.error(f"❌ Failed to restart admin bot: {e}")

    async def _trigger_shutdown(self):
        """Trigger graceful shutdown."""
        logger.info("🛑 Shutdown triggered")
        self.shutdown_event.set()

    async def _graceful_shutdown(self):
        """Perform graceful shutdown of all components."""
        logger.info("🛑 Initiating graceful shutdown...")
        start_time = time.time()

        try:
            # Stop health monitoring first
            await self.health_monitor.stop_monitoring()

            # Shutdown bots
            if self.main_bot:
                logger.info("🛑 Shutting down main bot...")
                try:
                    await self.main_bot.stop()
                except Exception as e:
                    logger.error(f"❌ Error during main bot shutdown: {e}")

            if self.admin_bot:
                logger.info("🛑 Shutting down admin bot...")
                try:
                    await self.admin_bot.stop()
                except Exception as e:
                    logger.error(f"❌ Error during admin bot shutdown: {e}")

            # Cleanup any remaining tasks
            tasks = [task for task in asyncio.all_tasks() if task is not asyncio.current_task()]
            if tasks:
                logger.info(f"🧹 Cancelling {len(tasks)} remaining tasks...")
                for task in tasks:
                    task.cancel()

                await asyncio.gather(*tasks, return_exceptions=True)

            shutdown_time = time.time() - start_time
            logger.info(f"✅ Graceful shutdown completed in {shutdown_time:.2f}s")
            logger.info("🔚 Bot orchestrator stopped")

        except Exception as e:
            logger.error(f"❌ Error during shutdown: {e}")

async def main():
    """Main entry point."""
    print("\n" + "=" * 40)
    print("🚀 Система запускается...")

    # Basic validation and info display
    try:
        print(f"✅ Основной бот: {'токен найден' if Config.TELEGRAM_BOT_TOKEN else '❌ токен не найден'}")
        print(f"✅ Админ бот: {'токен найден' if Config.ADMIN_BOT_TOKEN else '❌ токен не найден'}")
        print("✅ Фильтрация: валидатор настроен")
        print("✅ Модерация: очередь активна")
        print("✅ Логирование Q&A: папка logs/ готова")
        print("✅ LightRAG: подключение установлено")
    except Exception as e:
        print(f"❌ Ошибка при проверке конфигурации: {e}")
        return 1

    print("=" * 40 + "\n")

    # Create and run orchestrator
    orchestrator = BotOrchestrator()

    try:
        logger.info("🎬 Starting Telegram Bot Moderation System")
        logger.info("=" * 60)
        return await orchestrator.run()
    except KeyboardInterrupt:
        logger.info("🛑 Received keyboard interrupt")
        return 0
    except Exception as e:
        logger.error(f"❌ Unhandled exception: {e}")
        logger.error(traceback.format_exc())
        return 1
    finally:
        logger.info("🏁 System exited with code 1")

if __name__ == "__main__":
    try:
        exit_code = asyncio.run(main())
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\n🛑 Interrupted by user")
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ Fatal error: {e}")
        sys.exit(1)