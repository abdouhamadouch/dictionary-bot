import os
import logging
import requests
import xml.etree.ElementTree as ET

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    Application,
    MessageHandler,
    ContextTypes,
    filters,
)

# =========================================================
# CONFIG
# =========================================================

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
    word = word.strip()

    if not word:
        return None

    titles = [
        word,
        word.lower(),
    ]

    tried = set()

    for title in titles:

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
                "Wiktionary request error: %s",
                e,
            )
            return None

        except ValueError:
            logging.error(
                "Wiktionary returned invalid JSON."
            )
            return None

        parsed = data.get("parse")

        if parsed:

            wikitext = parsed.get("wikitext")

            if wikitext:
                return wikitext

    return None


# =========================================================
# ONELOOK
# =========================================================

def get_onelook_data(word):
    """
    Get basic OneLook XML results.

    OneLook's XML interface supports basic
    word lookups.
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

    except requests.RequestException as e:
        logging.error(
            "OneLook request error: %s",
            e,
        )
        return None

    xml_text = response.text.strip()

    if not xml_text:
        return None

    # Validate XML
    try:
        root = ET.fromstring(xml_text)

    except ET.ParseError:
        logging.error(
            "OneLook returned invalid XML."
        )
        return None

    # Store useful XML information without
    # trying to interpret it yet.
    return {
        "raw_xml": xml_text,
        "root_tag": root.tag,
    }


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
        "Wiktionary found: %s",
        bool(wiktionary),
    )

    logging.info(
        "OneLook found: %s",
        bool(onelook),
    )

    return {
        "word": word,
        "wiktionary": wiktionary,
        "onelook": onelook,
    }


# =========================================================
# TEMPORARY RESULT
# =========================================================

def format_test_result(data):

    word = data["word"]

    wiktionary = data["wiktionary"]
    onelook = data["onelook"]

    lines = [
        f"📖 <b>{word}</b>",
        "",
        "━━━━━━━━━━━━━━━━━━",
        "",
        "🔎 <b>Dictionary Sources</b>",
        "",
        (
            "• Wiktionary: ✅ Found"
            if wiktionary
            else "• Wiktionary: ❌ Not found"
        ),
        (
            "• OneLook: ✅ Found"
            if onelook
            else "• OneLook: ❌ Not found"
        ),
        "",
        "━━━━━━━━━━━━━━━━━━",
        "",
        "🧪 Source collection completed.",
    ]

    return "\n".join(lines)


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

    # For now we test single words only.
    if " " in word:

        await update.message.reply_text(
            "📚 For now, please send one English word."
        )

        return

    await update.message.reply_text(
        "🔎 Searching dictionary sources..."
    )

    sources = collect_sources(word)

    if not sources["wiktionary"] and not sources["onelook"]:

        await update.message.reply_text(
            f"❌ No dictionary data was found for "
            f"<b>{word}</b>.",
            parse_mode="HTML",
        )

        return

    result = format_test_result(
        sources
    )

    await update.message.reply_text(
        result,
        parse_mode="HTML",
        disable_web_page_preview=True,
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

    username = bot.username

    mention_pattern = rf"@{username}\b"

    # The bot must be mentioned.
    if not re.search(
        mention_pattern,
        text,
        flags=re.IGNORECASE,
    ):
        return

    # Remove the mention.
    clean_text = re.sub(
        mention_pattern,
        "",
        text,
        flags=re.IGNORECASE,
    ).strip()

    # If there is no text after the mention,
    # use the replied message.
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
