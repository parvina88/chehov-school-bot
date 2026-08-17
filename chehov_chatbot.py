import os
import sqlite3
import datetime
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

TOKEN = '8251623204:AAFWgbm25fGaY58oDodDaiLsjSfsNk73UhE'
bot = telebot.TeleBot(TOKEN)
DB_NAME = 'support.db'

MY_QUESTIONS_PAGE_SIZE = 5

# warning использовал нимножко cloude AI

def init_db():
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute('''
        CREATE TABLE IF NOT EXISTS users (
            telegram_id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'user'
        )
    ''')
    cur.execute('''
        CREATE TABLE IF NOT EXISTS questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sender_id INTEGER NOT NULL,
            sender_name TEXT NOT NULL,
            question TEXT NOT NULL,
            answer TEXT,
            answerer_id INTEGER,
            answerer_name TEXT,
            status TEXT NOT NULL DEFAULT 'open',
            taken_by_id INTEGER,
            taken_by_name TEXT,
            created_at TEXT,
            answered_at TEXT
        )
    ''')

    existing_cols = {row[1] for row in cur.execute('PRAGMA table_info(questions)')}
    migrations = {
        'taken_by_id': 'INTEGER',
        'taken_by_name': 'TEXT',
        'created_at': 'TEXT',
        'answered_at': 'TEXT',
    }
    for col, col_type in migrations.items():
        if col not in existing_cols:
            cur.execute(f'ALTER TABLE questions ADD COLUMN {col} {col_type}')
    conn.commit()
    conn.close()


def now_str():
    return datetime.datetime.now().strftime('%Y-%m-%d %H:%M')

def ensure_user(telegram_id, name):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute(
        'INSERT INTO users (telegram_id, name, status) VALUES (?, ?, "user") '
        'ON CONFLICT(telegram_id) DO UPDATE SET name = excluded.name',
        (telegram_id, name)
    )
    conn.commit()
    conn.close()


def get_user_status(telegram_id):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute('SELECT status FROM users WHERE telegram_id = ?', (telegram_id,))
    row = cur.fetchone()
    conn.close()
    return row[0] if row else 'user'


def is_admin(telegram_id):
    return get_user_status(telegram_id) == 'admin'


def get_admin_ids():
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("SELECT telegram_id FROM users WHERE status = 'admin'")
    rows = cur.fetchall()
    conn.close()
    return [row[0] for row in rows]


def display_name(user):
    return user.first_name or user.username or "Пользователь"


def add_question(sender_id, sender_name, question):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute(
        'INSERT INTO questions (sender_id, sender_name, question, status, created_at) '
        'VALUES (?, ?, ?, "open", ?)',
        (sender_id, sender_name, question, now_str())
    )
    conn.commit()
    q_id = cur.lastrowid
    conn.close()
    return q_id


def get_next_open_question(after_id=None):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    if after_id is not None:
        cur.execute(
            'SELECT id, sender_id, sender_name, question FROM questions '
            'WHERE status = "open" AND id > ? ORDER BY id LIMIT 1',
            (after_id,)
        )
        row = cur.fetchone()
        if row is None:
            cur.execute(
                'SELECT id, sender_id, sender_name, question FROM questions '
                'WHERE status = "open" ORDER BY id LIMIT 1'
            )
            row = cur.fetchone()
    else:
        cur.execute(
            'SELECT id, sender_id, sender_name, question FROM questions '
            'WHERE status = "open" ORDER BY id LIMIT 1'
        )
        row = cur.fetchone()
    conn.close()
    return row


def get_question_by_id(q_id):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute(
        'SELECT id, sender_id, sender_name, question, status, taken_by_id FROM questions WHERE id = ?',
        (q_id,)
    )
    row = cur.fetchone()
    conn.close()
    return row


def take_question(q_id, admin_id, admin_name):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute(
        'UPDATE questions SET status = "in_progress", taken_by_id = ?, taken_by_name = ? '
        'WHERE id = ? AND status = "open"',
        (admin_id, admin_name, q_id)
    )
    conn.commit()
    success = cur.rowcount > 0
    conn.close()
    return success


def release_question(q_id):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute(
        'UPDATE questions SET status = "open", taken_by_id = NULL, taken_by_name = NULL '
        'WHERE id = ? AND status = "in_progress"',
        (q_id,)
    )
    conn.commit()
    conn.close()


def close_question(q_id):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute('UPDATE questions SET status = "closed" WHERE id = ?', (q_id,))
    conn.commit()
    conn.close()


def save_answer(q_id, answer, answerer_id, answerer_name):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute(
        'UPDATE questions SET answer = ?, answerer_id = ?, answerer_name = ?, '
        'status = "answered", answered_at = ? WHERE id = ?',
        (answer, answerer_id, answerer_name, now_str(), q_id)
    )
    conn.commit()
    conn.close()


def get_user_questions_page(sender_id, offset, limit):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute(
        'SELECT id, question, answer, answerer_name, status, created_at FROM questions '
        'WHERE sender_id = ? ORDER BY id DESC LIMIT ? OFFSET ?',
        (sender_id, limit + 1, offset)
    )
    rows = cur.fetchall()
    conn.close()
    has_more = len(rows) > limit
    return rows[:limit], has_more


init_db()
user_states = {}


# ---------------------------------------------------------------------------
# Главное меню / FAQ

def main_menu(chat_id):
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("❓ Частые вопросы", callback_data="menu_faq"))
    markup.add(InlineKeyboardButton("✉️ Задать вопрос в поддержку", callback_data="menu_ask"))
    markup.add(InlineKeyboardButton("🗂 Мои вопросы", callback_data="myq_page_0"))
    if is_admin(chat_id):
        markup.add(InlineKeyboardButton("🛠 Ответить на вопросы", callback_data="menu_support"))
    return markup


@bot.message_handler(commands=['start'])
def send_welcome(message):
    ensure_user(message.chat.id, display_name(message.from_user))
    bot.send_message(message.chat.id, "привет это чат бот для вопросов", reply_markup=main_menu(message.chat.id))


def faq_menu():
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("Как записать рёбенка в Школу ?", callback_data="q1"))
    markup.add(InlineKeyboardButton("Когда можно записать рёбенка в школу ?", callback_data="q2"))
    markup.add(InlineKeyboardButton("Когда заканчиваються уроки ?", callback_data="q3"))
    markup.add(InlineKeyboardButton("Что если забрать ученика по неувожительной причине ?", callback_data="q4"))
    markup.add(InlineKeyboardButton("Можно ли прийти в школу с другим ребёнком не являющимся учеником школы ?", callback_data="q5"))
    return markup


@bot.message_handler(commands=['qession'])
def send_question(message):
    ensure_user(message.chat.id, display_name(message.from_user))
    bot.send_message(message.chat.id, "задайте вопрос", reply_markup=faq_menu())


@bot.message_handler(commands=['help'])
def send_help(message):
    ensure_user(message.chat.id, display_name(message.from_user))
    ask_for_question(message.chat.id)


# ---------------------------------------------------------------------------
# Задать вопрос в поддержку

def cancel_markup():
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("❌ Отмена", callback_data="cancel_action"))
    return markup


def ask_for_question(chat_id):
    user_states[chat_id] = {'action': 'awaiting_question'}
    bot.send_message(
        chat_id,
        "Напишите ваш вопрос в службу поддержки одним сообщением:",
        reply_markup=cancel_markup()
    )


def handle_new_question_text(message):
    chat_id = message.chat.id
    sender_name = display_name(message.from_user)
    ensure_user(chat_id, sender_name)
    q_id = add_question(chat_id, sender_name, message.text)
    user_states.pop(chat_id, None)
    bot.send_message(chat_id, f"Ваш вопрос №{q_id} принят. Мы ответим вам, как только это будет возможно.")
    notify_admins_new_question(q_id, sender_name, message.text)


def notify_admins_new_question(q_id, sender_name, question):
    admin_ids = get_admin_ids()
    if not admin_ids:
        return
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("✅ Ответить", callback_data=f"answer_{q_id}"))
    for admin_id in admin_ids:
        try:
            bot.send_message(
                admin_id,
                f"Новый вопрос №{q_id} от {sender_name}:\n\n{question}",
                reply_markup=markup
            )
        except Exception:
            pass  # админ мог не запускать бота / заблокировать его


# ---------------------------------------------------------------------------
# Мои вопросы

STATUS_LABELS = {
    'open': 'ожидает ответа',
    'in_progress': 'рассматривается сотрудником поддержки',
    'answered': 'отвечен',
    'closed': 'закрыт без ответа',
}


def show_my_questions(chat_id, offset, edit_message_id=None):
    rows, has_more = get_user_questions_page(chat_id, offset, MY_QUESTIONS_PAGE_SIZE)
    if not rows and offset == 0:
        bot.send_message(chat_id, "У вас пока нет заданных вопросов.")
        return

    parts = []
    for q_id, question, answer, answerer_name, status, created_at in rows:
        block = f"Вопрос №{q_id} ({created_at}):\n{question}\nСтатус: {STATUS_LABELS.get(status, status)}"
        if status == 'answered':
            block += f"\nОтвет ({answerer_name}): {answer}"
        parts.append(block)
    text = "\n\n".join(parts) if parts else "Больше вопросов нет."

    markup = InlineKeyboardMarkup()
    if has_more:
        markup.add(InlineKeyboardButton("➡️ Показать ещё", callback_data=f"myq_page_{offset + MY_QUESTIONS_PAGE_SIZE}"))
    if offset > 0:
        markup.add(InlineKeyboardButton("⬅️ Назад", callback_data=f"myq_page_{max(0, offset - MY_QUESTIONS_PAGE_SIZE)}"))

    if edit_message_id:
        try:
            bot.edit_message_text(text, chat_id, edit_message_id, reply_markup=markup if (has_more or offset > 0) else None)
            return
        except Exception:
            pass
    bot.send_message(chat_id, text, reply_markup=markup if (has_more or offset > 0) else None)


# ---------------------------------------------------------------------------
# Ответить на вопросы


def support_question_markup(q_id):
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("✅ Ответить", callback_data=f"answer_{q_id}"))
    markup.add(InlineKeyboardButton("➡️ Следующий", callback_data=f"next_{q_id}"))
    markup.add(InlineKeyboardButton("🚫 Закрыть без ответа", callback_data=f"close_{q_id}"))
    return markup


def show_open_question(chat_id, after_id=None, edit_message_id=None):
    row = get_next_open_question(after_id)
    if not row:
        text = "Открытых вопросов нет."
        if edit_message_id:
            try:
                bot.edit_message_text(text, chat_id, edit_message_id)
                return
            except Exception:
                pass
        bot.send_message(chat_id, text)
        return
    q_id, sender_id, sender_name, question = row
    text = f"Вопрос №{q_id} от {sender_name}:\n\n{question}"
    markup = support_question_markup(q_id)
    if edit_message_id:
        try:
            bot.edit_message_text(text, chat_id, edit_message_id, reply_markup=markup)
            return
        except Exception:
            pass
    bot.send_message(chat_id, text, reply_markup=markup)


def start_answering(chat_id, q_id, admin_name):
    row = get_question_by_id(q_id)
    if not row or row[4] != 'open':
        bot.send_message(chat_id, "Этот вопрос уже взят другим сотрудником или недоступен.")
        return
    if not take_question(q_id, chat_id, admin_name):
        bot.send_message(chat_id, "Этот вопрос уже взят другим сотрудником.")
        return

    sender_id = row[1]
    user_states[chat_id] = {'action': 'awaiting_answer', 'question_id': q_id}
    bot.send_message(chat_id, "Напишите ответ одним сообщением:", reply_markup=cancel_markup())

    try:
        bot.send_message(sender_id, f"Ваш вопрос №{q_id} сейчас рассматривается сотрудником поддержки.")
    except Exception:
        pass


def handle_answer_text(message, question_id):
    chat_id = message.chat.id
    row = get_question_by_id(question_id)
    user_states.pop(chat_id, None)
    if not row:
        bot.send_message(chat_id, "Этот вопрос уже недоступен.")
        return
    _, sender_id, sender_name, question, status, taken_by_id = row
    answerer_name = display_name(message.from_user)
    save_answer(question_id, message.text, chat_id, answerer_name)

    bot.send_message(chat_id, "Ответ сохранён и отправлен пользователю.")
    try:
        bot.send_message(
            sender_id,
            f"Ответ на ваш вопрос №{question_id}:\n\n"
            f"Вопрос: {question}\n"
            f"Ответ ({answerer_name}): {message.text}"
        )
    except Exception:
        pass  # пользователь мог заблокировать бота

# ---------------------------------------------------------------------------
# Отмена текущего действия

def cancel_current_action(chat_id):
    state = user_states.pop(chat_id, None)
    if not state:
        bot.send_message(chat_id, "Нечего отменять.")
        return
    if state['action'] == 'awaiting_answer':
        release_question(state['question_id'])
        bot.send_message(chat_id, "Ответ отменён, вопрос возвращён в очередь.")
    else:
        bot.send_message(chat_id, "Действие отменено.")


# ---------------------------------------------------------------------------
# Обработка нажатий на кнопки

@bot.callback_query_handler(func=lambda call: True)
def callback_answer(call):
    chat_id = call.message.chat.id
    msg_id = call.message.message_id
    data = call.data
    admin_name = display_name(call.from_user)
    ensure_user(chat_id, admin_name)

    admin_only_actions = data == "menu_support" or data.startswith(("answer_", "next_", "close_"))
    if admin_only_actions and not is_admin(chat_id):
        bot.answer_callback_query(call.id, "Эта функция доступна только администраторам поддержки.", show_alert=True)
        return

    if data in ("q1", "q2", "q3", "q4", "q5"):
        answers = {
            "q1": "Для записи ребенка нужно прийти в школу и поговорить с администрацией",
            "q2": "Можно записать во все дни кроме воскресенья. С 7:00 по 16:00",
            "q3": ("Уроки обычно заканчиваються.\n"
                   "1-ый урок: 8:45\n"
                   "2-ой урок: 9:40\n"
                   "3-ий урок: 10:30\n"
                   "4-ый урок: 11:40\n"
                   "5-ый урок: 12:45\n"
                   "6-ой урок: 13:40\n"
                   "7-ой урок: 14:25\n"),
            "q4": "За это ученика могут наказать может дойти до доклодной",
            "q5": "Да можно прийти с ребенком не являющимся учеником школы.",
        }
        bot.send_message(chat_id, answers[data])

    elif data == "menu_faq":
        bot.send_message(chat_id, "задайте вопрос", reply_markup=faq_menu())

    elif data == "menu_ask":
        ask_for_question(chat_id)

    elif data == "menu_support":
        show_open_question(chat_id)

    elif data.startswith("myq_page_"):
        offset = int(data.split("_")[-1])
        show_my_questions(chat_id, offset, edit_message_id=msg_id)

    elif data.startswith("answer_"):
        q_id = int(data.split("_", 1)[1])
        start_answering(chat_id, q_id, admin_name)

    elif data.startswith("next_"):
        after_id = int(data.split("_", 1)[1])
        show_open_question(chat_id, after_id=after_id, edit_message_id=msg_id)

    elif data.startswith("close_"):
        q_id = int(data.split("_", 1)[1])
        row = get_question_by_id(q_id)
        close_question(q_id)
        bot.send_message(chat_id, f"Вопрос №{q_id} закрыт без ответа.")
        if row:
            sender_id = row[1]
            try:
                bot.send_message(sender_id, f"Ваш вопрос №{q_id} был закрыт службой поддержки без ответа.")
            except Exception:
                pass
        show_open_question(chat_id, after_id=q_id, edit_message_id=msg_id)

    elif data == "cancel_action":
        cancel_current_action(chat_id)

    bot.answer_callback_query(call.id)


# ---------------------------------------------------------------------------
# Обработка текстовых сообщений

@bot.message_handler(func=lambda message: user_states.get(message.chat.id) is not None,
                      content_types=['text'])
def handle_state_text(message):
    state = user_states.get(message.chat.id)
    if not state:
        return
    if state['action'] == 'awaiting_question':
        handle_new_question_text(message)
    elif state['action'] == 'awaiting_answer':
        handle_answer_text(message, state['question_id'])

if __name__ == '__main__':
    bot.polling(non_stop=True)