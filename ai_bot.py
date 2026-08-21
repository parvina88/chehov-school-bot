"""Telegram bot: Gemini answers questions about A.P. Chekhov school in Khujand.

The whole school knowledge base sits in the system prompt, so Gemini's implicit
caching makes repeated questions cheap. No vector database needed.

Understands text, voice messages, and photos directly via Gemini's native
audio/image input — no separate speech-to-text service required.

Every exchange (name, Telegram ID, phone if shared, question, answer) is
appended to a Google Sheet — see the "Google Sheets logging" section below
for the required environment variables and one-time setup. Voice messages
are transcribed and photos are auto-captioned (when there's no caption) via
a separate one-off Gemini call, purely so the sheet has a readable "question".
"""
import json
import os
import traceback
from datetime import datetime

import telebot
from telebot.types import KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove
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

MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.6-flash")
MAX_HISTORY = 20  # messages kept per chat before the conversation restarts
DEBUG_ERRORS = os.environ.get("DEBUG_ERRORS") == "1"  # show API errors in the chat while setting up
TELEGRAM_LIMIT = 4000

# the "0:unset" fallbacks keep the module importable in tests; __main__ demands the real values
bot = telebot.TeleBot(os.environ.get("AI_BOT_TOKEN") or "0:unset")
client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY") or "unset")
chats = {}
phones = {}  # chat_id -> phone number, shared via the Telegram contact button (in-memory only)


# ---------------------------------------------------------------------------
# Google Sheets logging
#
# One-time setup:
#   1. Google Cloud Console -> create a project -> enable "Google Sheets API".
#   2. Create a Service Account -> create a JSON key -> download it.
#   3. Open the JSON file, copy its ENTIRE content as one string.
#   4. Create (or open) the Google Sheet you want to log into, click "Share",
#      and share it with the service account's email (looks like
#      xxx@xxx.iam.gserviceaccount.com) as an Editor.
#   5. Copy the Spreadsheet ID from its URL:
#      https://docs.google.com/spreadsheets/d/THIS_PART_IS_THE_ID/edit
#   6. Set two environment variables on your hosting:
#        GOOGLE_SHEET_ID              = the spreadsheet ID from step 5
#        GOOGLE_SERVICE_ACCOUNT_JSON  = the full JSON content from step 3 (one line)
#
# If these variables are not set, logging is silently skipped — the bot keeps
# working normally, just without the spreadsheet log.
# ---------------------------------------------------------------------------

GOOGLE_SHEET_ID = os.environ.get("GOOGLE_SHEET_ID")
GOOGLE_SERVICE_ACCOUNT_JSON = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
SHEET_HEADERS = ["Timestamp", "Name", "Telegram ID", "Phone", "Question", "Answer"]

_sheet = None
_sheet_init_failed = False


def get_sheet():
    """Lazily connects to the Google Sheet and caches the worksheet handle.
    Returns None (and logs a warning once) if credentials are missing or invalid,
    so a Sheets outage never breaks the bot's replies."""
    global _sheet, _sheet_init_failed
    if _sheet is not None or _sheet_init_failed:
        return _sheet
    if not GOOGLE_SHEET_ID or not GOOGLE_SERVICE_ACCOUNT_JSON:
        _sheet_init_failed = True
        print("Google Sheets logging disabled: set GOOGLE_SHEET_ID and GOOGLE_SERVICE_ACCOUNT_JSON to enable it.")
        return None
    try:
        import gspread
        from google.oauth2.service_account import Credentials

        creds_info = json.loads(GOOGLE_SERVICE_ACCOUNT_JSON)
        creds = Credentials.from_service_account_info(
            creds_info, scopes=["https://www.googleapis.com/auth/spreadsheets"]
        )
        worksheet = gspread.authorize(creds).open_by_key(GOOGLE_SHEET_ID).sheet1
        if worksheet.row_values(1) != SHEET_HEADERS:
            worksheet.update("A1", [SHEET_HEADERS])
        _sheet = worksheet
    except Exception:
        traceback.print_exc()
        _sheet_init_failed = True
        return None
    return _sheet


def log_to_sheet(name, telegram_id, phone, question, answer):
    sheet = get_sheet()
    if sheet is None:
        return
    try:
        sheet.append_row(
            [datetime.now().strftime("%Y-%m-%d %H:%M:%S"), name, str(telegram_id), phone or "", question, answer],
            value_input_option="USER_ENTERED",
        )
    except Exception:
        traceback.print_exc()  # never let a Sheets hiccup break the bot's reply


def log_user_exchange(message, question, answer):
    """Convenience wrapper: pulls name/telegram_id/phone from the Telegram
    message so handlers don't have to repeat that boilerplate."""
    name = message.from_user.first_name or message.from_user.username or "Без имени"
    log_to_sheet(name, message.from_user.id, phones.get(message.chat.id, ""), question, answer)


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


def ask_gemini(chat_id, parts):
    """Sends `parts` (text and/or types.Part audio/image blobs) to the chat's
    Gemini session and returns the reply text, or None on failure (the error
    is already printed/reported to the user by the caller)."""
    return get_chat(chat_id).send_message(parts).text


def ask_gemini_once(parts):
    """One-off Gemini call that does NOT touch any chat's persistent history —
    used for transcribing voice / auto-captioning photos purely for the Sheets
    log, so those side calls never leak into the user's actual conversation."""
    return client.models.generate_content(model=MODEL, contents=parts).text


def reply_with_error(message, error):
    traceback.print_exc()
    text = "Не получилось получить ответ. Попробуйте ещё раз чуть позже."
    if DEBUG_ERRORS:
        text += "\n\n" + f"{type(error).__name__}: {error}"[:1000]
    bot.reply_to(message, text)


def send_reply(chat_id, reply):
    reply = reply or "Не понял вопрос. Попробуйте сформулировать иначе."
    for part in split_message(reply):
        bot.send_message(chat_id, part)
    return reply


def phone_request_markup():
    markup = ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    markup.add(KeyboardButton("📱 Поделиться номером", request_contact=True))
    markup.add(KeyboardButton("Пропустить"))
    return markup


@bot.message_handler(commands=["start", "help"])
def start(message):
    bot.reply_to(
        message,
        "Привет! Я ИИ-помощник школы имени А.П. Чехова в Худжанде.\n"
        "Спросите меня о поступлении, расписании, учителях, кружках, документах — "
        "я отвечу по информации с сайта школы. Можно написать текстом, отправить "
        "голосовое сообщение или фото (например, фото объявления).\n\n"
        "Поделитесь номером телефона, чтобы мы могли связаться с вами при необходимости "
        "(это не обязательно — можно нажать «Пропустить»).\n\n"
        "/reset — начать разговор заново.",
        reply_markup=phone_request_markup(),
    )


@bot.message_handler(commands=["reset"])
def reset(message):
    chats.pop(message.chat.id, None)
    bot.reply_to(message, "История разговора очищена.")


@bot.message_handler(content_types=["contact"])
def got_contact(message):
    if message.contact and message.contact.user_id == message.from_user.id:
        phones[message.chat.id] = message.contact.phone_number
        bot.reply_to(message, "Спасибо, номер сохранён!", reply_markup=ReplyKeyboardRemove())
    else:
        bot.reply_to(message, "Пожалуйста, поделитесь своим номером через кнопку ниже.")


@bot.message_handler(func=lambda m: m.text == "Пропустить")
def skip_phone(message):
    bot.reply_to(message, "Хорошо, продолжим без номера.", reply_markup=ReplyKeyboardRemove())


@bot.message_handler(func=lambda m: bool(m.text))
def answer(message):
    bot.send_chat_action(message.chat.id, "typing")
    try:
        reply = ask_gemini(message.chat.id, [message.text])
    except Exception as error:  # network, quota, bad key, safety block
        reply_with_error(message, error)
        return

    reply = send_reply(message.chat.id, reply)
    log_user_exchange(message, message.text, reply)


@bot.message_handler(content_types=["voice"])
def voice_message(message):
    bot.send_chat_action(message.chat.id, "typing")
    try:
        file_info = bot.get_file(message.voice.file_id)
        audio_bytes = bot.download_file(file_info.file_path)
    except Exception as error:
        reply_with_error(message, error)
        return

    audio_part = types.Part.from_bytes(data=audio_bytes, mime_type="audio/ogg")

    # Transcribe first (a separate, stateless Gemini call) so we get a clean
    # question string for the Sheet and keep the persistent chat history
    # text-only. If transcription fails for any reason, fall back to sending
    # the audio straight into the chat so the user still gets an answer.
    transcript = ""
    try:
        transcript = (ask_gemini_once([
            audio_part,
            "Расшифруй это голосовое сообщение дословно, на языке говорящего. "
            "Выведи только текст расшифровки, без пояснений и без кавычек.",
        ]) or "").strip()
    except Exception:
        traceback.print_exc()

    try:
        if transcript:
            reply = ask_gemini(message.chat.id, [transcript])
        else:
            reply = ask_gemini(message.chat.id, [audio_part])
    except Exception as error:  # network, quota, bad key, safety block, unsupported audio
        reply_with_error(message, error)
        return

    reply = send_reply(message.chat.id, reply)
    log_user_exchange(message, transcript or "[голосовое сообщение]", reply)


@bot.message_handler(content_types=["photo"])
def photo_message(message):
    bot.send_chat_action(message.chat.id, "typing")
    try:
        largest_photo = message.photo[-1]  # Telegram sends several sizes; take the biggest
        file_info = bot.get_file(largest_photo.file_id)
        photo_bytes = bot.download_file(file_info.file_path)
    except Exception as error:
        reply_with_error(message, error)
        return

    image_part = types.Part.from_bytes(data=photo_bytes, mime_type="image/jpeg")
    prompt = message.caption or (
        "Пользователь прислал фото без подписи. Если на фото что-то относящееся "
        "к школе (расписание, объявление, документ и т.п.) — опиши, что на нём, "
        "и ответь по правилам из системного промпта. Если фото не по теме школы — "
        "вежливо скажи, что можешь помочь только с вопросами о школе."
    )

    try:
        reply = ask_gemini(message.chat.id, [image_part, prompt])
    except Exception as error:  # network, quota, bad key, safety block, unsupported image
        reply_with_error(message, error)
        return

    reply = send_reply(message.chat.id, reply)

    # For the log: use the caption if there was one; otherwise ask for a short
    # one-off description so the sheet shows something more useful than "[фото]".
    log_question = message.caption
    if not log_question:
        try:
            log_question = (ask_gemini_once([
                image_part,
                "Опиши одним коротким предложением, что на этом фото. Это для "
                "внутреннего журнала, не для пользователя — просто суть фото.",
            ]) or "").strip()
        except Exception:
            traceback.print_exc()
    log_user_exchange(message, f"[Фото] {log_question or 'без подписи'}", reply)


if __name__ == "__main__":
    assert os.environ.get("AI_BOT_TOKEN"), "set AI_BOT_TOKEN"
    assert os.environ.get("GEMINI_API_KEY"), "set GEMINI_API_KEY"
    bot.remove_webhook()  # на случай, если раньше был настроен webhook — иначе он конфликтует с polling
    bot.infinity_polling()
