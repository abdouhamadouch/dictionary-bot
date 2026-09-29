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

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

WIKTIONARY_API = "https://en.wiktionary.org/w/api.php"

HEADERS = {
    "User-Agent": "DictionaryBot/1.0"
}


# =========================================================
# WIKTIONARY
# =========================================================

def get_wiktionary_data(word):
    """
    Get the raw English Wiktionary wikitext for a word.
    """

    word = word.strip()

    if not word:
        return None

    # First try the word exactly as entered.
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
            logging.error("Wiktionary request failed: %s", e)
            return None

        except ValueError:
            logging.error("Invalid JSON received from Wiktionary.")
            return None

        parse_data = data.get("parse")

        if parse_data and parse_data.get("wikitext"):
            return parse_data["wikitext"]

    return None


# =========================================================
# CLEAN WIKITEXT
# =========================================================

def clean_wikitext(text):
    """
    Convert common Wiktionary markup into readable text.
    This is intentionally conservative.
    """

    if not text:
        return ""

    # Remove comments
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)

    # Remove templates such as {{lb|en|formal}}
    # but keep useful visible parameters in simple cases.
    def template_replacer(match):
        content = match.group(1).strip()

        # Common templates where the visible second parameter
        # is useful.
        parts = [p.strip() for p in content.split("|")]

        if len(parts) >= 2:
            template_name = parts[0]

            if template_name in {
                "l",
                "m",
                "mention",
                "gloss",
                "qualifier",
            }:
                return parts[-1]

        return ""

    # Repeat because templates can be nested.
    for _ in range(3):
        new_text = re.sub(
            r"\{\{([^{}]*)\}\}",
            template_replacer,
            text,
        )

        if new_text == text:
            break

        text = new_text

    # [[word|display]] -> display
    text = re.sub(
        r"\[\[([^|\]]+)\|([^\]]+)\]\]",
        r"\2",
        text,
    )

    # [[word]] -> word
    text = re.sub(
        r"\[\[([^\]]+)\]\]",
        r"\1",
        text,
    )

    # Remove bold / italic markup
    text = text.replace("'''", "")
    text = text.replace("''", "")

    # Remove HTML tags
    text = re.sub(r"<[^>]+>", "", text)

    # Remove reference-like markup
    text = re.sub(r"<ref.*?>.*?</ref>", "", text, flags=re.S)

    # Clean whitespace
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()


# =========================================================
# ENGLISH SECTION
# =========================================================

def extract_english_section(wikitext):
    """
    Extract the English section only.

    Wiktionary pages may contain:
    ==English==
    ==Indonesian==
    ==French==
    etc.
    """

    if not wikitext:
        return ""

    match = re.search(
        r"(?ms)^==\s*English\s*==\s*(.*?)(?=^==\s*[^=].*?==\s*$|\Z)",
        wikitext,
    )

    if not match:
        return ""

    return match.group(1).strip()


# =========================================================
# SECTIONS
# =========================================================

def extract_subsections(english_text):
    """
    Split the English section into level-3 sections.

    Example:
    ===Pronunciation===
    ===Noun===
    ===Verb===
    ===Adjective===
    """

    pattern = re.compile(
        r"(?ms)^===\s*(.*?)\s*===\s*(.*?)(?=^===\s*.*?\s*===\s*$|\Z)"
    )

    sections = []

    for match in pattern.finditer(english_text):
        title = match.group(1).strip()
        content = match.group(2).strip()

        sections.append({
            "title": title,
            "content": content,
        })

    return sections


# =========================================================
# PRONUNCIATION
# =========================================================

def extract_pronunciation(english_text):
    result = {
        "ipa": [],
        "audio_us": [],
        "audio_uk": [],
    }

    pronunciation_match = re.search(
        r"(?ms)^===\s*Pronunciation\s*===\s*(.*?)(?=^===\s*.*?\s*===\s*$|\Z)",
        english_text,
    )

    if not pronunciation_match:
        return result

    section = pronunciation_match.group(1)

    # IPA
    for match in re.finditer(
        r"\{\{IPA\|(?:[^|{}]*\|)*([^|{}]+)",
        section,
    ):
        ipa = match.group(1).strip()

        if ipa and ipa not in result["ipa"]:
            result["ipa"].append(ipa)

    # Audio templates
    for match in re.finditer(
        r"\{\{audio\|en\|([^|{}]+)(?:\|a=([^|{}]+))?",
        section,
    ):
        filename = match.group(1).strip()
        accent = (match.group(2) or "").strip().lower()

        if accent == "us":
            if filename not in result["audio_us"]:
                result["audio_us"].append(filename)

        elif accent == "uk":
            if filename not in result["audio_uk"]:
                result["audio_uk"].append(filename)

    return result


# =========================================================
# PARTS OF SPEECH
# =========================================================

POS_NAMES = {
    "Noun": "Noun",
    "Verb": "Verb",
    "Adjective": "Adjective",
    "Adverb": "Adverb",
    "Pronoun": "Pronoun",
    "Preposition": "Preposition",
    "Conjunction": "Conjunction",
    "Interjection": "Interjection",
    "Determiner": "Determiner",
    "Article": "Article",
    "Numeral": "Numeral",
    "Proper noun": "Proper noun",
    "Participle": "Participle",
}


def extract_definitions(content):
    """
    Extract numbered definitions from a POS section.
    """

    definitions = []

    for line in content.splitlines():
        line = line.strip()

        if not line:
            continue

        # Main definitions:
        # # definition
        if line.startswith("# ") or line == "#":
            definition = line[1:].strip()

            definition = clean_wikitext(definition)

            if definition:
                definitions.append(definition)

    return definitions


def extract_pos_sections(english_text):
    """
    Extract actual English parts of speech.
    """

    sections = extract_subsections(english_text)

    results = []

    for section in sections:
        title = section["title"]

        if title not in POS_NAMES:
            continue

        definitions = extract_definitions(section["content"])

        if not definitions:
            continue

        results.append({
            "part_of_speech": POS_NAMES[title],
            "definitions": definitions,
        })

    return results


# =========================================================
# SYNONYMS / ANTONYMS
# =========================================================

def extract_relation_section(content, heading):
    """
    Extract a ====Synonyms==== or ====Antonyms==== subsection.
    """

    pattern = re.compile(
        rf"(?ms)^====\s*{re.escape(heading)}\s*====\s*(.*?)(?=^====\s*.*?\s*====\s*$|^===\s*.*?\s*===\s*$|\Z)"
    )

    match = pattern.search(content)

    if not match:
        return []

    section = match.group(1)

    words = []

    for line in section.splitlines():
        line = line.strip()

        if not line.startswith("*"):
            continue

        line = line.lstrip("*").strip()

        cleaned = clean_wikitext(line)

        if not cleaned:
            continue

        # Avoid very long explanatory lines.
        if len(cleaned) > 120:
            continue

        if cleaned not in words:
            words.append(cleaned)

    return words


def extract_synonyms_antonyms(english_text):
    synonyms = []
    antonyms = []

    for section in extract_subsections(english_text):
        if section["title"] not in POS_NAMES:
            continue

        syns = extract_relation_section(
            section["content"],
            "Synonyms",
        )

        ants = extract_relation_section(
            section["content"],
            "Antonyms",
        )

        for word in syns:
            if word not in synonyms:
                synonyms.append(word)

        for word in ants:
            if word not in antonyms:
                antonyms.append(word)

    return synonyms, antonyms


# =========================================================
# WORD FORMS
# =========================================================

def extract_forms(english_text):
    """
    Try to collect common inflected forms.
    This is intentionally limited for the first parser version.
    """

    forms = []

    patterns = [
        r"\{\{en-past\|([^}]+)\}\}",
        r"\{\{en-pp\|([^}]+)\}\}",
        r"\{\{en-pres\|([^}]+)\}\}",
        r"\{\{en-3rd-sing\|([^}]+)\}\}",
        r"\{\{en-ing\|([^}]+)\}\}",
    ]

    for pattern in patterns:
        for match in re.finditer(pattern, english_text):
            value = clean_wikitext(match.group(1))

            if value and value not in forms:
                forms.append(value)

    return forms


# =========================================================
# FULL WORD PARSER
# =========================================================

def parse_wiktionary(word, wikitext):
    """
    Convert Wiktionary raw wikitext into structured data.
    """

    english = extract_english_section(wikitext)

    if not english:
        return None

    pronunciation = extract_pronunciation(english)

    parts_of_speech = extract_pos_sections(english)

    synonyms, antonyms = extract_synonyms_antonyms(
        english
    )

    forms = extract_forms(english)

    return {
        "word": word,
        "parts_of_speech": parts_of_speech,
        "pronunciation": pronunciation,
        "synonyms": synonyms,
        "antonyms": antonyms,
        "forms": forms,
    }


# =========================================================
# TELEGRAM FORMAT
# =========================================================

def format_word_result(data):
    word = data["word"]
    parts_of_speech = data["parts_of_speech"]
    pronunciation = data["pronunciation"]
    synonyms = data["synonyms"]
    antonyms = data["antonyms"]
    forms = data["forms"]

    lines = []

    lines.append(f"📖 <b>{word.upper()}</b>")
    lines.append("")
    lines.append("━━━━━━━━━━━━━━━━━━")

    # Parts of speech
    for pos in parts_of_speech:
        lines.append("")
        lines.append(f"🟦 <b>{pos['part_of_speech']}</b>")
        lines.append("")

        for index, definition in enumerate(
            pos["definitions"],
            start=1,
        ):
            lines.append(
                f"{index}️⃣ {definition}"
            )

    # Pronunciation
    ipa = pronunciation["ipa"]

    if ipa:
        lines.append("")
        lines.append("━━━━━━━━━━━━━━━━━━")
        lines.append("")
        lines.append("🔊 <b>Pronunciation</b>")

        for value in ipa:
            lines.append(f"• /{value}/")

    # Synonyms
    if synonyms:
        lines.append("")
        lines.append("━━━━━━━━━━━━━━━━━━")
        lines.append("")
        lines.append("🔄 <b>Synonyms</b>")
        lines.append("• " + " • ".join(synonyms[:12]))

    # Antonyms
    if antonyms:
        lines.append("")
        lines.append("↔️ <b>Antonyms</b>")
        lines.append("• " + " • ".join(antonyms[:12]))

    # Forms
    if forms:
        lines.append("")
        lines.append("━━━━━━━━━━━━━━━━━━")
        lines.append("")
        lines.append("📝 <b>Forms</b>")
        lines.append("• " + " • ".join(forms[:12]))

    return "\n".join(lines)


# =========================================================
# WORD ANALYSIS
# =========================================================

async def analyze_word(update: Update, word: str):

    word = word.strip()

    if not word:
        return

    if " " in word:
        await update.message.reply_text(
            "📚 For this first version, please send one English word."
        )
        return

    await update.message.reply_text(
        "🔎 Looking up the word..."
    )

    raw_data = get_wiktionary_data(word)

    if not raw_data:
        await update.message.reply_text(
            f"❌ No Wiktionary entry found for: {word}"
        )
        return

    data = parse_wiktionary(
        word,
        raw_data,
    )

    if not data:
        await update.message.reply_text(
            f"⚠️ I found the page for <b>{word}</b>, "
            "but could not find a usable English entry.",
            parse_mode="HTML",
        )
        return

    if not data["parts_of_speech"]:
        await update.message.reply_text(
            f"⚠️ I found <b>{word}</b>, "
            "but no usable English definitions were extracted yet.",
            parse_mode="HTML",
        )
        return

    result = format_word_result(data)

    await update.message.reply_text(
        result,
        parse_mode="HTML",
        disable_web_page_preview=True,
    )


# =========================================================
# PRIVATE MESSAGES
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
# GROUP MESSAGES
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

    username = bot.username

    if not username:
        return

    mention = f"@{username.lower()}"

    if mention not in text.lower():
        return

    # Remove bot mention
    clean_text = re.sub(
        re.escape(mention),
        "",
        text,
        flags=re.IGNORECASE,
    ).strip()

    # If the message only mentions the bot,
    # use the replied-to message.
    if not clean_text:

        if message.reply_to_message:
            replied = message.reply_to_message

            if replied.text:
                clean_text = replied.text.strip()

    if not clean_text:
        await message.reply_text(
            "📚 Please mention me with a word or reply to a message containing the word."
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

    # Private chat
    application.add_handler(
        MessageHandler(
            filters.ChatType.PRIVATE
            & filters.TEXT
            & ~filters.COMMAND,
            handle_private,
        )
    )

    # Groups
    application.add_handler(
        MessageHandler(
            filters.ChatType.GROUPS
            & filters.TEXT
            & ~filters.COMMAND,
            handle_group,
        )
    )

    logging.info("Dictionary Bot is starting...")

    application.run_polling(
        drop_pending_updates=True
    )


if __name__ == "__main__":
    main()
