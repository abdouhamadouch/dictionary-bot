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

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
DB_PATH = os.getenv("DB_PATH", "memory.db")

MAX_HISTORY_MESSAGES = 12
MAX_RETRIES = 3

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is missing.")
if not GROQ_API_KEY:
    raise RuntimeError("GROQ_API_KEY is missing.")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
client = AsyncGroq(api_key=GROQ_API_KEY)

SYSTEM_PROMPT = """
You are a capable, honest AI assistant inside a Telegram bot.

Core behavior:
- Answer the user's actual request directly.
- Maintain conversational context when previous messages are relevant.
- Never invent facts just to avoid saying you do not know.
- When a question needs current, obscure, changing, or verifiable information,
  use the available browser search tool.
- Prefer reliable and primary sources when researching.
- When web research is used, clearly distinguish verified information from
  interpretation and include useful source references when available.
- If a tool fails, retry when appropriate. Do not immediately answer with
  a generic "failed" message.
- If reliable information still cannot be obtained, explain specifically
  what could not be verified instead of pretending.
- Use the user's language unless they request another language.
- Keep normal answers readable and reasonably concise.
"""

def init_db():
    with closing(sqlite3.connect(DB_PATH)) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()

def get_history(user_id: str):
    with closing(sqlite3.connect(DB_PATH)) as conn:
        rows = conn.execute("""
            SELECT role, content
            FROM messages
            WHERE user_id = ?
            ORDER BY id DESC
            LIMIT ?
        """, (user_id, MAX_HISTORY_MESSAGES)).fetchall()

    rows.reverse()
    return [{"role": role, "content": content} for role, content in rows]

def save_message(user_id: str, role: str, content: str):
    with closing(sqlite3.connect(DB_PATH)) as conn:
        conn.execute(
            "INSERT INTO messages (user_id, role, content) VALUES (?, ?, ?)",
            (user_id, role, content),
        )
        conn.commit()

def clear_history(user_id: str):
    with closing(sqlite3.connect(DB_PATH)) as conn:
        conn.execute("DELETE FROM messages WHERE user_id = ?", (user_id,))
        conn.commit()

async def ask_ai(user_id: str, user_text: str):
    history = get_history(user_id)

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend(history)
    messages.append({"role": "user", "content": user_text})

    last_error = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = await client.chat.completions.create(
                model=MODEL,
                messages=messages,
                tools=[{"type": "browser_search"}],
                tool_choice="auto",
                temperature=0.2,
                max_completion_tokens=4096,
            )

            answer = response.choices[0].message.content

            if answer and answer.strip():
                answer = answer.strip()

                save_message(user_id, "user", user_text)
                save_message(user_id, "assistant", answer)

                return answer

            last_error = "The AI returned an empty response."

        except Exception as exc:
            last_error = str(exc)
            logging.exception("AI attempt %s/%s failed", attempt, MAX_RETRIES)

        if attempt < MAX_RETRIES:
            await asyncio.sleep(1.5 * attempt)

    raise RuntimeError(last_error or "Unknown AI error")

@dp.message(Command("start"))
async def start_handler(message: Message):
    await message.answer(
        "مرحبًا. أنا مساعد ذكاء اصطناعي.\n\n"
        "يمكنني متابعة سياق المحادثة، واستخدام البحث في الويب "
        "عندما تحتاج الإجابة إلى معلومات حديثة أو غير مؤكدة.\n\n"
        "/new — بدء محادثة جديدة"
    )

@dp.message(Command("new"))
async def new_handler(message: Message):
    user_id = str(message.from_user.id)
    clear_history(user_id)
    await message.answer("تم بدء محادثة جديدة.")

@dp.message(F.text)
async def chat_handler(message: Message):
    user_id = str(message.from_user.id)
    text = message.text.strip()

    if not text:
        return

    try:
        await message.bot.send_chat_action(
            chat_id=message.chat.id,
            action="typing",
        )

        answer = await ask_ai(user_id, text)

        # Telegram has a message-size limit, so split long answers.
        chunk_size = 3900
        for i in range(0, len(answer), chunk_size):
            await message.answer(answer[i:i + chunk_size])

    except Exception:
        logging.exception("Final request failure.")
        await message.answer(
            "تعذر إكمال الطلب بعد عدة محاولات. "
            "تحقق من اتصال الخدمة أو مفاتيح API ثم حاول مرة أخرى."
        )

async def main():
    init_db()
    logging.info("Bot starting with model: %s", MODEL)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
