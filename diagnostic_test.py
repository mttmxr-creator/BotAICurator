#!/usr/bin/env python3
"""
COMPREHENSIVE DIAGNOSTIC SCRIPT for Non-Admin Message Reception Issue

This script provides step-by-step diagnostic instructions and tools to identify
why messages from non-admin users are not being processed by the bot.

Based on the analysis:
- Bot has admin rights in group -1002746634729
- ValidationService returns YES for test messages
- ALL moderation queue entries are from mttMx (842335711) only
- Female participant's message was completely ignored

This suggests the issue is at the Telegram API/Bot configuration level,
not in the Python code logic.
"""

import logging
import asyncio
from telegram.ext import Application
from config import Config

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.DEBUG
)
logger = logging.getLogger(__name__)

class BotDiagnostic:
    """Comprehensive bot diagnostic tools."""

    def __init__(self):
        self.application = None

    async def initialize_bot(self):
        """Initialize bot application for diagnostics."""
        try:
            Config.validate()
            self.application = Application.builder().token(Config.TELEGRAM_BOT_TOKEN).build()
            await self.application.initialize()
            logger.info("✅ Bot initialized successfully")
            return True
        except Exception as e:
            logger.error(f"❌ Bot initialization failed: {e}")
            return False

    async def check_bot_info(self):
        """Get basic bot information from Telegram API."""
        try:
            bot = self.application.bot
            bot_info = await bot.get_me()

            print("\n" + "="*80)
            print("🤖 BOT INFORMATION")
            print("="*80)
            print(f"📋 Bot ID: {bot_info.id}")
            print(f"📛 Bot Username: @{bot_info.username}")
            print(f"📝 Bot Name: {bot_info.first_name}")
            print(f"🔗 Can Join Groups: {bot_info.can_join_groups}")
            print(f"👥 Can Read All Group Messages: {bot_info.can_read_all_group_messages}")
            print(f"💬 Supports Inline Queries: {bot_info.supports_inline_queries}")
            print("="*80)

            # This is the KEY diagnostic - can_read_all_group_messages
            if not bot_info.can_read_all_group_messages:
                print("🚨 CRITICAL ISSUE FOUND:")
                print("🚨 Bot has Privacy Mode ENABLED")
                print("🚨 This means the bot can only receive:")
                print("🚨   - Messages that mention the bot (@bot_username)")
                print("🚨   - Messages that reply to bot's messages")
                print("🚨   - Commands (/start, /help, etc.)")
                print("🚨   - Messages from bot admins (if configured)")
                print()
                print("🔧 SOLUTION:")
                print("🔧 1. Contact @BotFather")
                print("🔧 2. Send: /setprivacy")
                print("🔧 3. Select your bot")
                print("🔧 4. Send: Disable")
                print("🔧 5. Restart bot")
                return False
            else:
                print("✅ Privacy Mode is DISABLED - bot can read all group messages")
                return True

        except Exception as e:
            logger.error(f"❌ Failed to get bot info: {e}")
            return False

    async def check_chat_member_status(self, chat_id: int):
        """Check bot's status in specific chat."""
        try:
            bot = self.application.bot
            member = await bot.get_chat_member(chat_id, bot.id)

            print(f"\n🏢 CHAT MEMBER STATUS for chat {chat_id}:")
            print(f"📊 Status: {member.status}")
            print(f"👑 Is Administrator: {member.status == 'administrator'}")

            if hasattr(member, 'can_read_all_group_messages'):
                print(f"👁️ Can Read All Messages: {member.can_read_all_group_messages}")

            return member.status in ['administrator', 'member']

        except Exception as e:
            logger.error(f"❌ Failed to check chat member status: {e}")
            return False

    async def test_send_message(self, chat_id: int, test_message: str = "🔧 Diagnostic test message"):
        """Test if bot can send messages to chat."""
        try:
            bot = self.application.bot
            message = await bot.send_message(chat_id, test_message)
            print(f"✅ Successfully sent test message (ID: {message.message_id})")
            return True
        except Exception as e:
            logger.error(f"❌ Failed to send test message: {e}")
            return False

    def print_config_diagnostic(self):
        """Print configuration diagnostic information."""
        print("\n" + "="*80)
        print("⚙️ CONFIGURATION DIAGNOSTIC")
        print("="*80)
        print(f"🔑 Bot Token: {'✅ Set' if Config.TELEGRAM_BOT_TOKEN else '❌ Missing'}")
        print(f"👨‍💼 Admin Bot Token: {'✅ Set' if Config.ADMIN_BOT_TOKEN else '❌ Missing'}")
        print(f"👑 Admin Chat IDs: {Config.ADMIN_CHAT_IDS}")
        print(f"🧠 OpenAI Assistant: {'✅ Set' if Config.OPENAI_ASSISTANT_ID else '❌ Missing'}")
        print(f"✅ Validation Assistant: {'✅ Set' if Config.VALIDATION_ASSISTANT_ID else '❌ Missing'}")
        print("="*80)

    def print_analysis_summary(self):
        """Print analysis summary and recommendations."""
        print("\n" + "="*80)
        print("🔍 ROOT CAUSE ANALYSIS SUMMARY")
        print("="*80)
        print("📊 EVIDENCE:")
        print("   ✅ Bot has admin rights in group -1002746634729")
        print("   ✅ ValidationService consistently returns YES")
        print("   ✅ ALL moderation queue entries are from mttMx (842335711) only")
        print("   ❌ Female participant's message completely ignored")
        print()
        print("🎯 HYPOTHESIS:")
        print("   The bot is configured with Privacy Mode ENABLED at @BotFather level.")
        print("   This prevents the bot from receiving messages from non-admin users")
        print("   unless they mention the bot or reply to bot messages.")
        print()
        print("🔧 RECOMMENDED SOLUTION:")
        print("   1. Check bot privacy settings (run this diagnostic)")
        print("   2. If Privacy Mode is enabled, disable it via @BotFather")
        print("   3. Ask female participant to test again")
        print("   4. Monitor logs with comprehensive diagnostic logging")
        print("="*80)

    async def run_full_diagnostic(self, target_chat_id: int = -1002746634729):
        """Run complete diagnostic sequence."""
        print("🚀 STARTING COMPREHENSIVE BOT DIAGNOSTIC")
        print("="*80)

        # Step 1: Configuration
        self.print_config_diagnostic()

        # Step 2: Bot initialization
        if not await self.initialize_bot():
            print("❌ Cannot proceed - bot initialization failed")
            return

        # Step 3: Bot info and privacy settings
        privacy_ok = await self.check_bot_info()

        # Step 4: Chat member status
        member_ok = await self.check_chat_member_status(target_chat_id)

        # Step 5: Test message sending
        send_ok = await self.test_send_message(target_chat_id)

        # Step 6: Analysis summary
        self.print_analysis_summary()

        # Step 7: Next steps
        print("\n" + "="*80)
        print("📋 NEXT STEPS")
        print("="*80)

        if not privacy_ok:
            print("🚨 CRITICAL: Fix Privacy Mode settings first!")
            print("🔧 1. Contact @BotFather")
            print("🔧 2. Send: /setprivacy")
            print("🔧 3. Select your bot")
            print("🔧 4. Send: Disable")
            print("🔧 5. Restart bot and test again")
        else:
            print("✅ Privacy Mode is correctly disabled")
            print("🔍 Run bot with enhanced logging:")
            print("   python3 main.py")
            print("🧪 Ask female participant to send test message:")
            print("   'Тестовое сообщение для диагностики'")
            print("📊 Monitor logs for MESSAGE RECEPTION DIAGNOSTIC output")

        print("="*80)

        # Cleanup
        await self.application.shutdown()

def print_manual_instructions():
    """Print manual diagnostic instructions."""
    print("\n" + "="*80)
    print("📋 MANUAL DIAGNOSTIC INSTRUCTIONS")
    print("="*80)
    print()
    print("🔧 STEP 1: Check @BotFather Privacy Settings")
    print("   1. Open Telegram and message @BotFather")
    print("   2. Send: /setprivacy")
    print("   3. Select your bot from the list")
    print("   4. Current setting will be shown")
    print("   5. If 'Enable' is shown, Privacy Mode is ON (this is the problem)")
    print("   6. Send: Disable")
    print("   7. Confirm the change")
    print()
    print("🧪 STEP 2: Test Message Reception")
    print("   1. Start bot with: python3 main.py")
    print("   2. Ask female participant to send: 'Тестовое сообщение для диагностики'")
    print("   3. Check logs for 'MESSAGE RECEPTION DIAGNOSTIC' output")
    print("   4. Look for her user ID in the logs")
    print()
    print("🔍 STEP 3: Analyze Results")
    print("   ✅ If her message appears in logs: Code issue")
    print("   ❌ If her message doesn't appear: Telegram configuration issue")
    print()
    print("📞 STEP 4: Additional Tests")
    print("   - Ask her to mention bot: '@your_bot_name test'")
    print("   - Check if mentioned messages are received")
    print("   - Verify group membership and permissions")
    print("="*80)

async def main():
    """Main diagnostic function."""
    print("🔥 TELEGRAM BOT MESSAGE RECEPTION DIAGNOSTIC")
    print("🔥 Investigating why non-admin messages are ignored")
    print()

    # Print manual instructions first
    print_manual_instructions()

    # Ask user what they want to do
    print("\n📋 DIAGNOSTIC OPTIONS:")
    print("1. Run automated diagnostic (requires bot to be working)")
    print("2. Show manual instructions only")
    print("3. Show analysis summary")

    try:
        choice = input("\nEnter choice (1/2/3): ").strip()

        if choice == "1":
            diagnostic = BotDiagnostic()
            await diagnostic.run_full_diagnostic()
        elif choice == "2":
            print_manual_instructions()
        elif choice == "3":
            diagnostic = BotDiagnostic()
            diagnostic.print_analysis_summary()
        else:
            print("Invalid choice. Showing manual instructions.")
            print_manual_instructions()

    except KeyboardInterrupt:
        print("\n🛑 Diagnostic cancelled by user")
    except Exception as e:
        print(f"\n❌ Diagnostic error: {e}")
        print("📋 Falling back to manual instructions:")
        print_manual_instructions()

if __name__ == "__main__":
    asyncio.run(main())