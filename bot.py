import os
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

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

WIKTIONARY_API = "https://en.wiktionary.org/w/api.php"
ONELOOK_URL = "https://www.onelook.com/"

HEADERS = {
    "User-Agent": "DictionaryBot/1.0"
}


# =========================================================
# WIKTIONARY
# =========================================================

def get_wiktionary_data(word):
    """
    Get raw Wiktionary data for a word.
    """

    word = word.strip()

    if not word:
        return None

    titles_to_try = [
        word,
        word.lower(),
    ]

    tried = set()

    for title in titles_to_try:

        if title in tried:
            continue

        tried.add(title)

        params = {
            "action": "parse",
            "page": title,
            "prop": "wikitext",
            "redirects": 1,
            "format": "json",
            "formatversion": "2",
        }

        try:
            response = requests.get(
                WIKTIONARY_API,
                params=params,
                headers=HEADERS,
                timeout=15,
            )

            response.raise_for_status()

            data = response.json()

        except requests.RequestException as e:
            logging.error(
                "Wiktionary request failed: %s",
                e,
            )
            return None

        except ValueError:
            logging.error(
                "Invalid JSON received from Wiktionary."
            )
            return None

        parse_data = data.get("parse")

        if parse_data:

            wikitext = parse_data.get("wikitext")

            if wikitext:
                return wikitext

    return None


# =========================================================
# ONELOOK
# =========================================================

def get_onelook_data(word):
    """
    Get OneLook XML data for a word.

    OneLook's XML interface is used only for basic
    dictionary lookups at this stage.
    """

    word = word.strip()

    if not word:
        return None

    params = {
        "w": word,
        "xml": "1",
    }

    try:

        response = requests.get(
            ONELOOK_URL,
            params=params,
            headers=HEADERS,
            timeout=15,
        )

        response.raise_for_status()

        if not response.text.strip():
            return None

        return response.text

    except requests.RequestException as e:

        logging.error(
            "OneLook request failed: %s",
            e,
        )

        return None


# =========================================================
# COLLECT ALL SOURCES
# =========================================================

def collect_sources(word):

    logging.info(
        "Collecting dictionary data for: %s",
        word,
    )

    wiktionary = get_wiktionary_data(word)

    onelook = get_onelook_data(word)

    sources = {
        "word": word,
        "wiktionary": wiktionary,
        "onelook": onelook,
    }

    logging.info(
        "Wiktionary: %s",
        bool(wiktionary),
    )

    logging.info(
        "OneLook: %s",
        bool(onelook),
    )

    return sources


# =========================================================
# TEMPORARY DEBUG OUTPUT
# =========================================================

def create_debug_message(sources):

    word = sources["word"]

    wiktionary_status = (
        "✅ Found"
        if sources["wiktionary"]
        else "❌ Not found"
    )

    onelook_status = (
        "✅ Found"
        if sources["onelook"]
        else "❌ Not found"
    )

    return (
        f"🔎 <b>{word}</b>\n\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"📚 <b>Sources</b>\n\n"
        f"• Wiktionary: {wiktionary_status}\n"
        f"• OneLook: {onelook_status}\n\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"🧪 Source collection is working.\n"
        f"AI organization will be added next."
    )


# =========================================================
# ANALYZE WORD
# =========================================================

async def analyze_word(
    update: Update,
    word: str,
):

    word = word.strip()

    if not word:
        return

    # Current testing stage:
    # one word only.
    if " " in word:

        await update.message.reply_text(
            "📚 For this testing stage, please send one English word."
        )

        return

    await update.message.reply_text(
        "🔎 Searching dictionary sources..."
    )

    sources = collect_sources(word)

    if not sources["wiktionary"] and not sources["onelook"]:

        await update.message.reply_text(
            f"❌ I couldn't find usable dictionary data for <b>{word}</b>.",
            parse_mode="HTML",
        )

        return

    debug_message = create_debug_message(
        sources
    )

    await update.message.reply_text(
        debug_message,
        parse_mode="HTML",
        disable_web_page_preview=True,
    )


# =========================================================
# PRIVATE CHAT
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
        text.strip(),
    )


# =========================================================
# GROUP CHAT
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

    # Get bot username
    bot = await context.bot.get_me()

    username = bot.username

    if not username:
        return

    mention = f"@{username.lower()}"

    # Ignore messages that don't mention the bot
    if mention not in text.lower():
        return

    # Remove bot mention
    clean_text = text

    clean_text = clean_text.replace(
        f"@{username}",
        "",
    )

    clean_text = clean_text.strip()

    # If user only mentioned the bot,
    # use the replied message.
    if not clean_text:

        if message.reply_to_message:

            replied = message.reply_to_message

            if replied.text:
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

    # Private messages
    application.add_handler(
        MessageHandler(
            filters.ChatType.PRIVATE
            & filters.TEXT
            & ~filters.COMMAND,
            handle_private,
        )
    )

    # Group messages
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
