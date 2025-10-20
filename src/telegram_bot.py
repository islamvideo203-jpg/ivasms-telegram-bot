"""
Telegram bot for iVASMS OTP notifications.
Handles all bot commands and message sending functionality.
"""

import asyncio
import logging
import os
import subprocess
import traceback
from datetime import datetime
from typing import Dict, List, Optional

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

logger = logging.getLogger(__name__)


class IVASMSTelegramBot:
    """Telegram bot for OTP notifications and management."""

    def __init__(
        self,
        token: str,
        admin_chat_ids: List[int],
        storage_manager,
        monitor_manager,
    ):
        self.token = token
        self.admin_chat_ids = admin_chat_ids
        self.storage = storage_manager
        self.monitor = monitor_manager

        self.application = None
        self.start_time = datetime.now()

        # Bot status
        self.is_monitoring = False
        self.last_login_time: Optional[datetime] = None
        self.last_fetch_time: Optional[datetime] = None

    async def initialize(self):
        """Initialize the Telegram bot application."""
        try:
            self.application = ApplicationBuilder().token(self.token).build()

            # Add command handlers
            self.application.add_handler(CommandHandler("start", self.start_command))
            self.application.add_handler(CommandHandler("status", self.status_command))
            self.application.add_handler(CommandHandler("config", self.config_command))
            self.application.add_handler(CommandHandler("info", self.info_command))
            self.application.add_handler(CommandHandler("recent_otps", self.recent_otps_command))
            self.application.add_handler(CommandHandler("last_otp", self.last_otp_command))
            self.application.add_handler(CommandHandler("new_otp", self.new_otp_command))
            self.application.add_handler(CommandHandler("restart", self.restart_command))
            self.application.add_handler(CommandHandler("stop", self.stop_command))
            self.application.add_handler(CommandHandler("start_monitor", self.start_monitor_command))
            self.application.add_handler(CommandHandler("logs", self.logs_command))

            # Handle non-command messages
            self.application.add_handler(
                MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message)
            )

            logger.info("Telegram bot initialized successfully")

        except Exception as e:
            logger.error(f"Failed to initialize Telegram bot: {e}")
            raise

    def is_admin(self, chat_id: int) -> bool:
        return chat_id in self.admin_chat_ids

    async def send_admin_message(
        self,
        message: str,
        parse_mode: ParseMode = ParseMode.MARKDOWN_V2,
        disable_notification: bool = False,
    ):
        if not self.application:
            logger.error("Bot application not initialized")
            return

        for chat_id in self.admin_chat_ids:
            try:
                await self.application.bot.send_message(
                    chat_id=chat_id,
                    text=message,
                    parse_mode=parse_mode,
                    disable_notification=disable_notification,
                )
            except Exception as e:
                logger.error(f"Failed to send message to admin {chat_id}: {e}")

    def escape_markdown(self, text: str) -> str:
        special_chars = [
            "_", "*", "[", "]", "(", ")", "~", "`", ">", "#",
            "+", "-", "=", "|", "{", "}", ".", "!"
        ]
        for char in special_chars:
            text = text.replace(char, f"\\{char}")
        return text

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.is_admin(update.effective_chat.id):
            await update.message.reply_text("❌ Unauthorized access")
            return

        status_text = (
            "🤖 *iVASMS Telegram Bot*\n\n"
            f"Status: {'🟢 Running' if self.is_monitoring else '🔴 Stopped'}\n"
            f"Uptime: {self._get_uptime()}\n"
            f"Admin Chat ID: `{update.effective_chat.id}`\n\n"
            "Available commands:\n"
            "• `/status` - Bot status\n"
            "• `/config` - Configuration\n"
            "• `/recent_otps` - Recent OTPs\n"
            "• `/last_otp` - Last OTP\n"
            "• `/new_otp` - Force fetch\n"
            "• `/logs` - View logs\n"
        )
        await update.message.reply_text(status_text, parse_mode=ParseMode.MARKDOWN_V2)

    async def status_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.is_admin(update.effective_chat.id):
            await update.message.reply_text("❌ Unauthorized access")
            return

        status_text = (
            "📊 *Bot Status*\n\n"
            f"Monitoring: {'🟢 Active' if self.is_monitoring else '🔴 Inactive'}\n"
            f"Uptime: {self._get_uptime()}\n"
        )

        if self.last_login_time:
            status_text += f"Last Login: {self.last_login_time.strftime('%Y-%m-%d %H:%M:%S')}\n"
        else:
            status_text += "Last Login: Never\n"

        if self.last_fetch_time:
            status_text += f"Last Fetch: {self.last_fetch_time.strftime('%Y-%m-%d %H:%M:%S')}\n"
        else:
            status_text += "Last Fetch: Never\n"

        otp_count = await self.storage.get_otp_count()
        status_text += f"Total OTPs: {otp_count}\n"

        await update.message.reply_text(status_text, parse_mode=ParseMode.MARKDOWN_V2)

    async def logs_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.is_admin(update.effective_chat.id):
            await update.message.reply_text("❌ Unauthorized access")
            return

        lines = 20
        if context.args:
            try:
                lines = max(1, min(int(context.args[0]), 100))
            except ValueError:
                await update.message.reply_text("❌ Invalid number format")
                return

        log_file = os.getenv("LOG_FILE", "./logs/bot.log")
        if not os.path.exists(log_file):
            await update.message.reply_text("📄 Log file not found")
            return

        with open(log_file, "r") as f:
            log_lines = f.readlines()[-lines:]

        if not log_lines:
            await update.message.reply_text("📄 Log file is empty")
            return

        log_text = ''.join(log_lines)
        response_text = f"📄 *Last {len(log_lines)} log lines*\n\n```\n{log_text}\n```"

        await update.message.reply_text(response_text, parse_mode=ParseMode.MARKDOWN_V2)

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.is_admin(update.effective_chat.id):
            return
        await update.message.reply_text(
            "ℹ️ Use /start to see available commands",
            parse_mode=ParseMode.MARKDOWN_V2,
        )

    def _get_uptime(self) -> str:
        uptime = datetime.now() - self.start_time
        days, seconds = uptime.days, uptime.seconds
        hours, remainder = divmod(seconds, 3600)
        minutes, _ = divmod(remainder, 60)
        if days > 0:
            return f"{days}d {hours}h {minutes}m"
        elif hours > 0:
            return f"{hours}h {minutes}m"
        return f"{minutes}m"

    async def send_error_message(self, error: Exception, context: str = ""):
        try:
            error_msg = f"❌ *Error*\n\n`{self.escape_markdown(str(error))}`"
            stack_trace = traceback.format_exc()
            if len(stack_trace) > 500:
                stack_trace = stack_trace[:500] + "..."
            error_msg += f"\n\n```\n{stack_trace}\n```"
            await self.send_admin_message(error_msg)
        except Exception as e:
            logger.error(f"Failed to send error message: {e}")

    async def run(self):
        """Run the Telegram bot."""
        try:
            logger.info("Starting Telegram bot...")
            await self.send_status_message("Bot started")

            # Jalankan polling langsung (fitur baru PTB v20+)
            await self.application.run_polling()

        except Exception as e:
            logger.error(f"Telegram bot error: {e}")
            await self.send_error_message(e, "Bot runtime")
            raise

    async def send_status_message(self, message: str, is_error: bool = False):
        emoji = "❌" if is_error else "ℹ️"
        formatted_message = f"{emoji} {self.escape_markdown(message)}"
        await self.send_admin_message(formatted_message)
