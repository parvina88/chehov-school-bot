"""Telegram bot: Gemini answers questions about A.P. Chekhov school in Khujand.

The whole school knowledge base sits in the system prompt, so Gemini's implicit
caching makes repeated questions cheap. No vector database needed.
"""
import os
import telebot
from google import genai
from google.genai import types

KNOWLEDGE = open(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "knowledge.md"),
    encoding="utf-8",
).read()

SYSTEM_PROMPT = f"""Ты — ИИ-помощник российско-таджикской школы с углублённым изучением
отдельных предметов в г. Худжанде имени А.П. Чехова. Отвечаешь ученикам, родителям и учителям.

Правила:
- Отвечай ТОЛЬКО по информации ниже. Ничего не выдумывай.
- Если ответа в ней нет — скажи об этом прямо и предложи написать на rtsosh.khujand@gmail.com
  или посмотреть сайт https://rtsosh-khujand.tj/.
- Отвечай на языке вопроса (русский, таджикский, английский).
- Коротко и по делу. Обычный текст, без Markdown-разметки.

=== ИНФОРМАЦИЯ О ШКОЛЕ ===
{KNOWLEDGE}"""

MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
MAX_HISTORY = 20  # messages kept per chat before the conversation restarts
TELEGRAM_LIMIT = 4000

# the "0:unset" fallbacks keep the module importable in tests; __main__ demands the real values
bot = telebot.TeleBot(os.environ.get("AI_BOT_TOKEN") or "0:unset")
client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY") or "unset")
chats = {}


def get_chat(chat_id):
    chat = chats.get(chat_id)
    if chat is None or len(chat.get_history()) > MAX_HISTORY:
        chat = chats[chat_id] = client.chats.create(
            model=MODEL,
            config=types.GenerateContentConfig(system_instruction=SYSTEM_PROMPT),
        )
    return chat


def split_message(text, limit=TELEGRAM_LIMIT):
    """Telegram rejects messages over 4096 characters, so cut on line breaks."""
    parts = []
    while len(text) > limit:
        cut = text.rfind("\n", 0, limit)
        if cut <= 0:
            cut = limit
        parts.append(text[:cut])
        text = text[cut:].lstrip("\n")
    if text or not parts:
        parts.append(text)
    return parts


@bot.message_handler(commands=["start", "help"])
def start(message):
    bot.reply_to(
        message,
        "Привет! Я ИИ-помощник школы имени А.П. Чехова в Худжанде.\n"
        "Спросите меня о поступлении, расписании, учителях, кружках, документах — "
        "я отвечу по информации с сайта школы.\n\n"
        "/reset — начать разговор заново.",
    )


@bot.message_handler(commands=["reset"])
def reset(message):
    chats.pop(message.chat.id, None)
    bot.reply_to(message, "История разговора очищена.")


@bot.message_handler(func=lambda m: bool(m.text))
def answer(message):
    bot.send_chat_action(message.chat.id, "typing")
    try:
        reply = get_chat(message.chat.id).send_message(message.text).text
    except Exception as error:  # network, quota, safety block
        print("gemini error:", error)
        bot.reply_to(message, "Не получилось получить ответ. Попробуйте ещё раз чуть позже.")
        return
    for part in split_message(reply or "Не понял вопрос. Попробуйте сформулировать иначе."):
        bot.send_message(message.chat.id, part)


if __name__ == "__main__":
    assert os.environ.get("AI_BOT_TOKEN"), "set AI_BOT_TOKEN"
    assert os.environ.get("GEMINI_API_KEY"), "set GEMINI_API_KEY"
    bot.infinity_polling()
