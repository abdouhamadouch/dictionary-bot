import os
import re
import logging
import requests

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    Application,
    MessageHandler,
    ContextTypes,
    filters,
)

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is missing.")


WIKTIONARY_API = "https://en.wiktionary.org/w/api.php"
ONELOOK_URL = "https://www.onelook.com/"

HEADERS = {
    "User-Agent": "DictionaryBot/1.0"
}


logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)


# =========================================================
# WIKTIONARY
# =========================================================

def get_wiktionary_data(word):

    try:
        response = requests.get(
            WIKTIONARY_API,
            params={
                "action": "parse",
                "page": word,
                "prop": "wikitext",
                "redirects": 1,
                "format": "json",
                "formatversion": "2",
            },
            headers=HEADERS,
            timeout=15,
        )

        response.raise_for_status()

        data = response.json()

        parsed = data.get("parse")

        if not parsed:
            return None

        return parsed.get("wikitext")

    except Exception as e:

        logging.error(
            "Wiktionary error: %s",
            e,
        )

        return None


# =========================================================
# ONELOOK
# =========================================================

def get_onelook_data(word):

    try:

        response = requests.get(
            ONELOOK_URL,
            params={
                "w": word,
            },
            headers=HEADERS,
            timeout=15,
        )

        response.raise_for_status()

        html = response.text

        if not html:
            return None

        return html

    except Exception as e:

        logging.error(
            "OneLook error: %s",
            e,
        )

        return None


# =========================================================
# COLLECT SOURCES
# =========================================================

def collect_sources(word):

    logging.info(
        "Searching sources for: %s",
        word,
    )

    wiktionary = get_wiktionary_data(word)

    onelook = get_onelook_data(word)

    logging.info(
        "Wiktionary: %s",
        "FOUND" if wiktionary else "NOT FOUND",
    )

    logging.info(
        "OneLook: %s",
        "FOUND" if onelook else "NOT FOUND",
    )

    return {
        "word": word,
        "wiktionary": wiktionary,
        "onelook": onelook,
    }


# =========================================================
# TEMPORARY RESULT
# =========================================================

def format_result(data):

    word = data["word"]

    wiktionary = data["wiktionary"]
    onelook = data["onelook"]

    return (
        f"📖 <b>{word.upper()}</b>\n\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"📚 <b>Sources</b>\n\n"
        f"• Wiktionary: "
        f"{'✅ Found' if wiktionary else '❌ Not found'}\n"
        f"• OneLook: "
        f"{'✅ Page found' if onelook else '❌ Not found'}\n\n"
        f"━━━━━━━━━━━━━━━━━━"
    )


# =========================================================
# ANALYZE
# =========================================================

async def analyze_word(
    update: Update,
    word: str,
):

    word = word.strip()

    if not word:
        return

    if " " in word:

        await update.message.reply_text(
            "📚 For now, send one English word."
        )

        return

    await update.message.reply_text(
        "🔎 Searching..."
    )

    data = collect_sources(word)

    if not data["wiktionary"] and not data["onelook"]:

        await update.message.reply_text(
            f"❌ No data found for <b>{word}</b>.",
            parse_mode="HTML",
        )

        return

    await update.message.reply_text(
        format_result(data),
        parse_mode="HTML",
    )


# =========================================================
# PRIVATE
# =========================================================

async def handle_private(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not update.message:
        return

    text = update.message.text

    if not text:
        return

    await analyze_word(
        update,
        text,
    )


# =========================================================
# GROUP
# =========================================================

async def handle_group(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not update.message:
        return

    message = update.message
    text = message.text or ""

    if not text:
        return

    bot = await context.bot.get_me()

    if not bot.username:
        return

    pattern = rf"@{re.escape(bot.username)}\b"

    if not re.search(
        pattern,
        text,
        re.IGNORECASE,
    ):
        return

    clean_text = re.sub(
        pattern,
        "",
        text,
        flags=re.IGNORECASE,
    ).strip()

    if not clean_text:

        replied = message.reply_to_message

        if replied and replied.text:
            clean_text = replied.text.strip()

    if not clean_text:

        await message.reply_text(
            "📚 Mention me with a word, "
            "or reply to a message and mention me."
        )

        return

    await analyze_word(
        update,
        clean_text,
    )


# =========================================================
# MAIN
# =========================================================

def main():

    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .build()
    )

    application.add_handler(
        MessageHandler(
            filters.ChatType.PRIVATE
            & filters.TEXT
            & ~filters.COMMAND,
            handle_private,
        )
    )

    application.add_handler(
        MessageHandler(
            filters.ChatType.GROUPS
            & filters.TEXT
            & ~filters.COMMAND,
            handle_group,
        )
    )

    logging.info(
        "Dictionary Bot is starting..."
    )

    application.run_polling(
        drop_pending_updates=True
    )


if __name__ == "__main__":
    main()
