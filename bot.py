import os
import logging
import requests

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


def get_wiktionary_data(word):
    """Get raw Wiktionary wikitext for an English word."""

    url = "https://en.wiktionary.org/w/api.php"

    params = {
        "action": "parse",
        "page": word,
        "prop": "wikitext",
        "format": "json",
        "formatversion": "2",
        "redirects": "1",
    }

    response = requests.get(
        url,
        params=params,
        timeout=15,
        headers={
            "User-Agent": "DictionaryBot/1.0"
        },
    )

    response.raise_for_status()

    data = response.json()

    if "error" in data:
        return None

    parse_data = data.get("parse")

    if not parse_data:
        return None

    return parse_data.get("wikitext")


async def analyze_text(update: Update, text: str):
    """Test Wiktionary with the supplied text."""

    # For this first test, only single words are sent to Wiktionary.
    word = text.strip()

    if not word or " " in word:
        await update.message.reply_text(
            "🔎 For this first test, please send one English word only."
        )
        return

    try:
        wikitext = get_wiktionary_data(word)

        if not wikitext:
            await update.message.reply_text(
                f"❌ No Wiktionary entry found for:\n\n{word}"
            )
            return

        # Telegram messages have a size limit, so show only the beginning.
        preview = wikitext[:3500]

        await update.message.reply_text(
            f"📚 Wiktionary raw data\n\n"
            f"🔤 Word: {word}\n\n"
            f"{preview}"
        )

    except requests.RequestException as e:
        logger.exception("Wiktionary request failed")

        await update.message.reply_text(
            f"❌ Wiktionary request failed.\n\n{e}"
        )

    except Exception as e:
        logger.exception("Unexpected error")

        await update.message.reply_text(
            f"❌ Unexpected error:\n\n{e}"
        )


async def handle_private(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle normal messages in private chat."""

    if not update.message or not update.message.text:
        return

    text = update.message.text.strip()

    if not text:
        return

    await analyze_text(update, text)


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

    mention = f"@{username}"

    if mention.lower() not in text.lower():
        return

    # Remove the bot mention.
    remaining = text.replace(mention, "").strip()

    # If this is a reply and there is no text after the mention,
    # use the replied message.
    if not remaining and update.message.reply_to_message:
        replied = update.message.reply_to_message

        if replied.text:
            remaining = replied.text.strip()

    if not remaining:
        await update.message.reply_text(
            "🔎 Please send a word after mentioning me."
        )
        return

    await analyze_text(update, remaining)


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
