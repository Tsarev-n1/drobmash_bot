import os
import sqlite3
import requests
from datetime import timedelta

from telegram import (InlineKeyboardMarkup, ReplyKeyboardMarkup,
                      InlineKeyboardButton)
from telegram.ext import (Updater, Filters, MessageHandler,
                          CallbackQueryHandler, CommandHandler,
                          ConversationHandler)

from dotenv import load_dotenv


load_dotenv()

HAPPY_URL = 'https://drobmash.happydesk.ru/panel/api'

ACCOUNT_ID = os.getenv('ACCOUNT_ID')
TG_TOKEN = os.getenv('TG_TOKEN')
updater = Updater(token=TG_TOKEN)

conn = sqlite3.connect('problems.db', check_same_thread=False)
cur = conn.cursor()

cur.execute("""
    CREATE TABLE IF NOT EXISTS problem(
        chat_id INT PRIMARY KEY,
        type TEXT,
        description TEXT,
        message TEXT);
""")
conn.commit()


PROBLEM_DICT = {
    'Проблема с монитором': [
        'не включается экран',
        'мерцает экран',
        'рябь на экране',
        'сгорел монитор'
    ],
    'Проблема с системным блоком': [
        'не включается',
        'перегревается',
        'громко шумит',
        'западает кнопка'
    ],
    'Другое': 1
}

TYPE, DESCRIPTION, MESSAGE = range(3)


def insert_table(data: str, coloumn: str, chat_id: int) -> None:
    try:
        sql_request = (
            """UPDATE problem SET {0} = '{1}'
            WHERE chat_id = '{2}'"""
            .format(coloumn, data, chat_id)
        )
        cur.execute(sql_request)
        conn.commit()
    except sqlite3.Error as error:
        print('Error sqlite table insert')
        print(error)


def get_problem_message(chat_id):
    cur.execute(
        """SELECT type, description, message
        FROM problem WHERE chat_id = ?""",
        (chat_id,)
    )
    problem = cur.fetchall()
    result = ''
    for i in problem:
        result += ' '.join(i)
    return result


def start(update, context):
    chat = update.effective_chat
    cur.execute(
        """INSERT OR IGNORE
        INTO problem (chat_id) VALUES (?)""", (chat.id,)
    )
    conn.commit()
    start_message = (
        f'Здравствуй, {chat.first_name}. '
        f'Здесь ты сможешь создать заявку.'
    )
    button = ReplyKeyboardMarkup(
        [['/start', '/cancel'], ],
        resize_keyboard=True
    )
    update.message.reply_text(start_message, reply_markup=button)
    context.bot.send_message(
        chat_id=chat.id,
        text='Выберите тип пробемы',
        reply_markup=create_keyboard()
    )
    return TYPE


def create_keyboard(problem_request=None):
    keyboard = []
    if problem_request is None:
        for problem in PROBLEM_DICT.keys():
            button = [InlineKeyboardButton(problem, callback_data=problem)]
            keyboard.append(button)
        inline_keyboard = InlineKeyboardMarkup(keyboard)
        return inline_keyboard
    for current_problem in PROBLEM_DICT[problem_request]:
        button = [InlineKeyboardButton(
            current_problem,
            callback_data=current_problem
        )]
        keyboard.append(button)
    inline_keyboard = InlineKeyboardMarkup(keyboard)
    return inline_keyboard


def first_level(update, context):
    query = update.callback_query
    new_problem = query.data
    if new_problem == 'Другое':
        query.edit_message_text(text=new_problem)
        insert_table(new_problem, 'type', update.effective_chat.id)
        message = (
            f'{update.effective_chat.first_name}, '
            f'опиши свою проблему и оставь контактные данные'
        )
        context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=message
        )
        return MESSAGE
    insert_table(new_problem, 'type', update.effective_chat.id)
    query.answer()
    keyboard = create_keyboard(new_problem)
    query.edit_message_text(text=new_problem, reply_markup=keyboard)
    return DESCRIPTION


def second_level(update, context):
    chat = update.effective_chat
    query = update.callback_query
    data = query.data
    first_name = query.message.chat.first_name
    insert_table(data, 'description', chat.id)
    query.answer()
    cur.execute("""SELECT type FROM problem WHERE chat_id = ?""", (chat.id,))
    new_text = cur.fetchone()
    query.edit_message_text(text=new_text[0] + ' ' + data)
    message = (
        f'{first_name}, '
        f'опиши подробнее свою проблему и оставь контактные данные'
    )
    context.bot.send_message(chat_id=chat.id, text=message)
    return MESSAGE


def get_message(update, context):
    chat = update.effective_chat
    insert_table(update.message.text, 'message', chat.id)
    first_name = update.message.chat.first_name
    message = f'{first_name}, твое обращение отправлено'
    send_problem(chat.id)
    context.bot.send_message(
        chat_id=chat.id,
        text=get_problem_message(chat.id)
    )
    button = ReplyKeyboardMarkup([['/start'], ], resize_keyboard=True)
    context.bot.send_message(
        chat_id=chat.id,
        text=message, reply_markup=button
    )
    return ConversationHandler.END


def cancel(update, context):
    button = ReplyKeyboardMarkup([['/start'], ], resize_keyboard=True)
    context.bot.send_message(
        chat_id=update.effective_chat.id,
        text='Покеда',
        reply_markup=button
    )
    return ConversationHandler.END


def get_token():
    url = HAPPY_URL + '/v2/auth'
    data = {
        'email': os.getenv('HAPPY_LOGIN'),
        'password': os.getenv('HAPPY_PASSWORD')
    }
    try:
        response = requests.post(url, data=data)
    except requests.exceptions.HTTPError as error:
        print(error)
        print(response.status_code)
    token = response.json().get('token')
    return token


def send_problem(chat_id):
    cur.execute(
        """SELECT type, description
        FROM problem WHERE chat_id = ?""",
        (chat_id,)
    )
    issue_type = cur.fetchall()
    if issue_type[0][0] == 'Другое':
        issue_title = issue_type[0][0]
    else:
        issue_title = ' '.join(issue_type[0])
    cur.execute(
        """SELECT message FROM problem
        WHERE chat_id = ?""",
        (chat_id,)
    )
    issue_description = cur.fetchall()[0][0]
    issue_dict = {
        "type": "Issue",
        "title": issue_title,
        "channel": "telegram",
        "from": f'Telegram chat_id {chat_id}',
        "description": issue_description,
        "executor_id": ACCOUNT_ID,
        "user_id": ACCOUNT_ID
    }
    print(issue_dict)
    try:
        request = requests.post(
            HAPPY_URL + '/issue',
            headers={'X-Auth-Token': get_token()},
            data=issue_dict
        )
    except requests.exceptions.HTTPError as error:
        print(error)
    return print(request.status_code)


def main():
    problem_conversation = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            TYPE: [CallbackQueryHandler(first_level)],
            DESCRIPTION: [CallbackQueryHandler(second_level)],
            MESSAGE: [MessageHandler(
                Filters.text & (~Filters.command),
                get_message
            )]
        },
        fallbacks=[CommandHandler('cancel', cancel)],
        run_async=True,
        conversation_timeout=timedelta(minutes=3),
        allow_reentry=True,
    )

    updater.dispatcher.add_handler(problem_conversation)
    updater.start_polling()
    updater.idle()


if __name__ == "__main__":
    main()
