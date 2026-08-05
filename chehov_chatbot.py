import os

import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

TOKEN = os.environ['BOT_TOKEN']
bot = telebot.TeleBot(TOKEN)

@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.send_message(message.chat.id, "привет это чат бот для вопросов")

@bot.message_handler(commands=['qession'])
def send_question(message):
    markup = InlineKeyboardMarkup()
    q1 = InlineKeyboardButton("Как записать рёбенка в Школу ?", callback_data="q1")
    q2 = InlineKeyboardButton("Когда можно записать рёбенка в школу ?", callback_data="q2")
    q3 = InlineKeyboardButton("Когда заканчиваються уроки ?", callback_data="q3")
    q4 = InlineKeyboardButton("Что если забрать ученика по неувожительной причине ?", callback_data="q4")
    q5 = InlineKeyboardButton("Можно ли прийти в школу с другим ребёнком не являющимся учеником школы ?", callback_data="q5")
    markup.add(q1)
    markup.add(q2)
    markup.add(q3)
    markup.add(q4)
    markup.add(q5)
    bot.send_message(message.chat.id, "задайте вопрос", reply_markup=markup)


@bot.callback_query_handler(func=lambda call: True)
def callback_answer(call):
    chat_id = call.message.chat.id
    if call.data == "q1":
        bot.send_message(chat_id, "Для записи ребенка нужно прийти в школу и поговорить с администрацией")
    elif call.data == "q2":
        bot.send_message(chat_id, "Можно записать во все дни кроме воскресенья. С 7:00 по 16:00")
    elif call.data == "q3":
        bot.send_message(chat_id, "Уроки обычно заканчиваються.\n"
                                    "1-ый урок: 8:45\n"
                                    "2-ой урок: 9:40\n"
                                    "3-ий урок: 10:30\n"
                                    "4-ый урок: 11:40\n"
                                    "5-ый урок: 12:45\n"
                                    "6-ой урок: 13:40\n"
                                    "7-ой урок: 14:25\n")
    elif call.data == "q4":
        bot.send_message(chat_id, "За это ученика могут наказать может дойти до доклодной")
    elif call.data == "q5":
        bot.send_message(chat_id, "Да можно прийти с ребенком не являющимся учеником школы.")

if __name__ == '__main__':
    bot.infinity_polling()