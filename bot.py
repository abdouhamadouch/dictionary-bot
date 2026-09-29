import os
import logging

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    Application,
    ContextTypes,
    MessageHandler,
    filters,
)

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is missing.")


logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger(__name__)


async def handle_private(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle normal messages in private chat."""

    if not update.message or not update.message.text:
        return

    text = update.message.text.strip()

    if not text:
        return

    await update.message.reply_text(
        f"🔎 Received:\n\n{text}"
    )


async def handle_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle only messages that explicitly mention the bot."""

    if not update.message or not update.message.text:
        return

    text = update.message.text.strip()

    if not text:
        return

    bot = await context.bot.get_me()

    username = bot.username

    if not username:
        return

    mention = f"@{username}".lower()

    if mention not in text.lower():
        return

    # Remove the bot mention
    remaining = text.replace(f"@{username}", "").strip()

    # If this is a reply and there is no text after the mention,
    # use the replied message as the input.
    if not remaining and update.message.reply_to_message:
        replied = update.message.reply_to_message

        if replied.text:
            remaining = replied.text.strip()

    if not remaining:
        await update.message.reply_text(
            "🔎 Please send a word or sentence after mentioning me."
        )
        return

    await update.message.reply_text(
        f"🔎 Received:\n\n{remaining}"
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Route messages according to chat type."""

    if not update.message:
        return

    if update.message.chat.type == "private":
        await handle_private(update, context)

    elif update.message.chat.type in ("group", "supergroup"):
        await handle_group(update, context)


def main():
    application = Application.builder().token(BOT_TOKEN).build()

    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_message,
        )
    )

    logger.info("Dictionary Bot is starting...")

    application.run_polling()


if __name__ == "__main__":
    main()
