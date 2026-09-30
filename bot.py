import os
import asyncio
import logging
import sqlite3
from contextlib import closing

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message
from groq import AsyncGroq
from dotenv import load_dotenv


# =========================================================
# CONFIG
# =========================================================

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
DB_PATH = os.getenv("DB_PATH", "dictionary.db")

MAX_RETRIES = 3

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is missing.")

if not GROQ_API_KEY:
    raise RuntimeError("GROQ_API_KEY is missing.")


# =========================================================
# LOGGING
# =========================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)


# =========================================================
# TELEGRAM + GROQ
# =========================================================

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

client = AsyncGroq(
    api_key=GROQ_API_KEY
)


# =========================================================
# AI PROMPT
# =========================================================

SYSTEM_PROMPT = """
You are an advanced English dictionary and vocabulary assistant.

Your job is to analyze an English word or phrase comprehensively.

The user may send only one English word, for example:
"depend"

Give a useful, accurate dictionary-style analysis.

IMPORTANT:
- Do not invent meanings, word families, phrasal verbs, collocations,
  roots, or expressions.
- If something does not genuinely exist or is not commonly used,
  say so instead of inventing it.
- Distinguish between common and uncommon information.
- Use simple English explanations.
- Use Arabic for translations and important explanations.
- Examples must sound natural.
- Do not overload the answer with irrelevant information.

Analyze the word using the following structure when applicable:

━━━━━━━━━━━━━━━━━━
🔤 WORD
Word + IPA pronunciation

🇺🇸 American pronunciation
🇬🇧 British pronunciation

🇦🇪 Main Arabic meanings

━━━━━━━━━━━━━━━━━━
📚 PARTS OF SPEECH
Explain each important part of speech.

━━━━━━━━━━━━━━━━━━
🌱 ROOT / ORIGIN
Give the linguistic root or etymological origin when reliably known.
If the modern English word does not have a useful/simple root,
explain that briefly.

━━━━━━━━━━━━━━━━━━
🌳 WORD FAMILY
Give important related words.

For each word:
- word
- part of speech
- Arabic meaning

Include derivatives such as nouns, adjectives, adverbs, verbs,
prefix/suffix forms when genuinely related.

━━━━━━━━━━━━━━━━━━
🔄 WORD FORMS
Give important grammatical forms.

For verbs:
base
3rd person
past
past participle
-ing

For nouns/adjectives/adverbs, give useful forms when they exist.

━━━━━━━━━━━━━━━━━━
🧠 MEANINGS
Give the important meanings separately.

For every important meaning:
- simple English explanation
- Arabic meaning
- natural example
- Arabic translation

Do not mix unrelated meanings together.

━━━━━━━━━━━━━━━━━━
🔗 COMMON PREPOSITIONS
Show common combinations such as:

depend on
interested in
responsible for

Only include genuinely common combinations.

━━━━━━━━━━━━━━━━━━
🧩 COLLOCATIONS
Give common natural combinations with the word.

━━━━━━━━━━━━━━━━━━
⚡ PHRASAL VERBS
Give important phrasal verbs containing the word,
if they genuinely exist.

For each:
- phrasal verb
- Arabic meaning
- natural example
- Arabic translation

If there are none, say:
"No common phrasal verbs."

━━━━━━━━━━━━━━━━━━
💬 EXPRESSIONS
Give common fixed expressions or phrases containing the word,
if applicable.

━━━━━━━━━━━━━━━━━━
🔄 SYNONYMS
Give useful synonyms grouped by meaning.

Do not give synonyms that are only vaguely related.

━━━━━━━━━━━━━━━━━━
↔️ ANTONYMS
Give genuine antonyms when they exist.

━━━━━━━━━━━━━━━━━━
⚠️ COMMON MISTAKES
Mention important mistakes learners commonly make with this word.

Include:
❌ incorrect
✅ correct
and explain briefly when necessary.

━━━━━━━━━━━━━━━━━━
🔍 CONFUSING WORDS
If the word is commonly confused with another word,
explain the difference.

Example:
affect vs effect

━━━━━━━━━━━━━━━━━━
🎯 LEVEL
Give an approximate CEFR level:
A1 / A2 / B1 / B2 / C1 / C2

━━━━━━━━━━━━━━━━━━
📝 EXTRA NOTES
Add only useful information that helps an English learner
understand and use the word naturally.

Rules:
- Do not force a section if it is irrelevant.
- Do not invent information just to fill a section.
- Important English words should be bold.
- Keep the formatting clean and easy to read on a phone.
- Avoid decorative stars.
"""


# =========================================================
# DATABASE
# =========================================================

def init_db():
    with closing(sqlite3.connect(DB_PATH)) as conn:

        conn.execute("""
            CREATE TABLE IF NOT EXISTS words (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                word TEXT NOT NULL,
                answer TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        conn.commit()


def get_saved_word(user_id: str, word: str):

    with closing(sqlite3.connect(DB_PATH)) as conn:

        row = conn.execute(
            """
            SELECT answer
            FROM words
            WHERE user_id = ? AND word = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (user_id, word.lower()),
        ).fetchone()

    if row:
        return row[0]

    return None


def save_word(user_id: str, word: str, answer: str):

    with closing(sqlite3.connect(DB_PATH)) as conn:

        conn.execute(
            """
            INSERT INTO words
            (user_id, word, answer)
            VALUES (?, ?, ?)
            """,
            (user_id, word.lower(), answer),
        )

        conn.commit()


# =========================================================
# AI
# =========================================================

async def analyze_word(word: str):

    messages = [
        {
            "role": "system",
            "content": SYSTEM_PROMPT,
        },
        {
            "role": "user",
            "content": f'Analyze this English word comprehensively:\n\n"{word}"',
        },
    ]

    last_error = None

    for attempt in range(1, MAX_RETRIES + 1):

        try:

            response = await client.chat.completions.create(
                model=MODEL,
                messages=messages,
                temperature=0.2,
                max_completion_tokens=5000,
            )

            answer = response.choices[0].message.content

            if answer and answer.strip():
                return answer.strip()

            last_error = "Empty response from AI."

        except Exception as exc:

            last_error = str(exc)

            logging.exception(
                "AI attempt %s/%s failed",
                attempt,
                MAX_RETRIES,
            )

        if attempt < MAX_RETRIES:
            await asyncio.sleep(1.5 * attempt)

    raise RuntimeError(
        last_error or "Unknown AI error."
    )


# =========================================================
# /START
# =========================================================

@dp.message(Command("start"))
async def start_handler(message: Message):

    await message.answer(
        "📚 <b>Smart English Dictionary</b>\n\n"
        "أرسل أي كلمة أو عبارة إنجليزية، وسأعطيك تحليلًا شاملًا لها.\n\n"
        "مثال:\n"
        "<code>depend</code>\n\n"
        "سأعطيك المعاني، النطق، الجذر، "
        "Word Family، Forms، Synonyms، Antonyms، "
        "Phrasal Verbs، Collocations، Prepositions، "
        "الأمثلة والأخطاء الشائعة وغيرها.",
        parse_mode="HTML",
    )


# =========================================================
# /CLEAR
# =========================================================

@dp.message(Command("clear"))
async def clear_handler(message: Message):

    user_id = str(message.from_user.id)

    with closing(sqlite3.connect(DB_PATH)) as conn:

        conn.execute(
            "DELETE FROM words WHERE user_id = ?",
            (user_id,),
        )

        conn.commit()

    await message.answer(
        "🗑️ تم حذف الكلمات المحفوظة لهذا المستخدم."
    )


# =========================================================
# WORD HANDLER
# =========================================================

@dp.message(F.text)
async def word_handler(message: Message):

    text = message.text.strip()

    if not text:
        return

    # Ignore commands
    if text.startswith("/"):
        return

    user_id = str(message.from_user.id)

    # Limit accidental huge messages
    if len(text) > 100:
        await message.answer(
            "أرسل كلمة أو عبارة إنجليزية قصيرة لتحليلها."
        )
        return

    try:

        await message.bot.send_chat_action(
            chat_id=message.chat.id,
            action="typing",
        )

        # Check local database
        saved = get_saved_word(
            user_id,
            text,
        )

        if saved:

            await message.answer(
                saved,
                parse_mode="HTML",
            )

            return

        # Analyze with AI
        answer = await analyze_word(text)

        # Save result
        save_word(
            user_id,
            text,
            answer,
        )

        # Telegram message limit
        chunk_size = 3900

        for i in range(
            0,
            len(answer),
            chunk_size,
        ):

            await message.answer(
                answer[i:i + chunk_size],
                parse_mode="HTML",
            )

    except Exception:

        logging.exception(
            "Word analysis failed."
        )

        await message.answer(
            "تعذر تحليل الكلمة بعد عدة محاولات.\n\n"
            "حاول مرة أخرى."
        )


# =========================================================
# MAIN
# =========================================================

async def main():

    init_db()

    logging.info(
        "Smart Dictionary starting..."
    )

    logging.info(
        "Model: %s",
        MODEL,
    )

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
