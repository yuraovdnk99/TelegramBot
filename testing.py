import sqlite3
from sqlite3 import Error
import telebot
from telebot import types
from datetime import datetime
import requests
from time import sleep
from threading import Thread
 
bot = telebot.TeleBot(token)
 # Функция получение записей с правочника названий городов
def pochta_api(city):
    request_url = 'https://api.novaposhta.ua/v2.0/json/'
    data_json = {
            "modelName": "AddressGeneral",
            "calledMethod": "getSettlements",
            "methodProperties": {
                "FindByString": city,
                "Page": "1"
            },
            "apiKey": "API ключ для соединения с справочником"
        }
    headers = {'Content-type': 'application/json', 'Accept': 'text/plain'}
    r = requests.post(request_url, json=data_json, headers=headers).json()
    result = {x['Description']: x['AreaDescriptionRu'] for x in r['data']}
    return result 
#Метод для получения контактов пользователя, который уже запускал бот. 
#Этот метод создан для обновления данных в БД.
@bot.message_handler(content_types=['contact'])
def contact(message):
    if message.contact is not None:
        users_update = f'UPDATE USERS SET phone_number = "{message.contact.phone_number}" ' \
                       f'WHERE user_id = {message.chat.id};'
        post_sql_query(users_update)
 #Старт бота.Вставляем данные о пользователе
@bot.message_handler(commands=['start'])
def start(message):
    user_reg_query = f'INSERT OR IGNORE INTO USERS(user_id, username, first_name, last_name)' \
                     f'VALUES ({message.chat.id}, "{message.chat.username}", "{message.chat.first_name}", ' \
                     f'"{message.chat.last_name}");'
    post_sql_query(user_reg_query)
    temp_query = f'INSERT OR IGNORE INTO TEMP(user_id, city_start, city_end, flag)' \
                 f'VALUES({message.chat.id}, NULL, NULL, NULL);'
    post_sql_query(temp_query)
    try:
        markup = types.ReplyKeyboardMarkup(one_time_keyboard=True, row_width=1)
        markup.add('Найти поездку', 'Предложить поездку')
        msg = bot.reply_to(message, 'Что Вы хотите?', reply_markup=markup)
        bot.register_next_step_handler(msg, process_act_step)
    except Exception as e:
        print(e, 'error start')
#Обрабатываем результат нажатия кнопки.
def process_act_step(message):
    act = message.text
    if act == 'Найти поездку':
        flag = 'Найти поездку'
    else:
        flag = 'Предложить поездку'
    update_temp_query = f'UPDATE TEMP SET flag = "{flag}" WHERE user_id = {message.from_user.id};'
    post_sql_query(update_temp_query)
    try:
        msg = bot.reply_to(message, 'Введите город для поиска ')
        bot.register_next_step_handler(msg, process_s_city_step)
    except Exception as e:
        print(e, 'error process_act_step')

#Получение данных о начале маршрута.
def process_s_city_step(message):
    try:
        city = message.text
        cities_s = pochta_api(city)
        if cities_s:
            markup = types.InlineKeyboardMarkup()
            for key, value in cities_s.items():
                markup.add(types.InlineKeyboardButton(text=f"{key} - {value}", callback_data=f'{key} city_s'))
            bot.send_message(message.chat.id, 'Выберите город отправления ', reply_markup=markup)
        else:
            msg = bot.reply_to(message, 'Введите город для поиска ')
            bot.register_next_step_handler(msg, process_s_city_step)
    except Exception as e:
        print(e, 'error process_s_city_step')
 #Получение данных о конце маршрута.
def process_e_city_step(message):
    try:
        city = message.text
        cities_f = pochta_api(city)
        if cities_f:
            markup = types.InlineKeyboardMarkup()
            for key, value in cities_f.items():
                markup.add(types.InlineKeyboardButton(text=f'{key} - {value}', callback_data=f'{key} city_e'))
            bot.send_message(message.chat.id, 'Выберите город назначения ', reply_markup=markup)
        else:
            msg = bot.reply_to(message, 'Введите город для поиска ')
            bot.register_next_step_handler(msg, process_e_city_step)
    except Exception as e:
        print(e, 'error process_e_city_step')

#Обработка события нажатия на кнопку. Получаем и корректируем данные с Inline кнопок
@bot.callback_query_handler(func=lambda call: True)
def callback_inline(call):
    if call.data.find('city_s') != -1:
        city_s = call.data[:call.data.find('city_s') - 1]
        temp_city_s_update = f'UPDATE TEMP SET city_start = "{city_s}" ' \
                             f'WHERE user_id = {call.message.chat.id};'
        post_sql_query(temp_city_s_update)
        msg = bot.send_message(chat_id=call.message.chat.id, text='Введите город для поиска ')
        bot.register_next_step_handler(msg, process_e_city_step)
    elif call.data.find('city_e') != -1:
        city_e = call.data[:call.data.find('city_e') - 1]
        temp_city_s_update = f'UPDATE TEMP SET city_end = "{city_e}" ' \
                             f'WHERE user_id = {call.message.chat.id};'
        post_sql_query(temp_city_s_update)
        check_temp_table_query = f'SELECT * FROM TEMP WHERE city_start NOT NULL ' \
                                 f'AND city_end NOT NULL AND user_id = {call.message.chat.id};'
        temp = post_sql_query(check_temp_table_query)
        if temp:
            for i in temp:
                search_route(i)

#Добавляем новый маршрут, если в базе нет похожих маршрутов, которые ввел пользователь, 
# то эти данные обрабатываем и реализуем запрос отправки их в таблицу БД. 
# Далее, вызываем функцию получения даты, и просим ввести дату поездки
def add_route(message):
    act = message.text
    if act == 'Да':
        check_temp_table_query = f'SELECT * FROM TEMP WHERE city_start NOT NULL ' \
                                 f'AND city_end NOT NULL AND user_id = {message.chat.id};'
        temp_data = post_sql_query(check_temp_table_query)
        if temp_data:
            for i in temp_data:
                user, city_s, city_e, flag = i
                route_data = post_sql_query('SELECT COUNT (*) FROM ROUTE;')
                route_id = route_data[0][0] + 1
                add_route_query = f'INSERT OR IGNORE INTO ROUTE(route_id, city_start, city_end)' \
                                  f' VALUES ({route_id}, "{city_s}", "{city_e}");'
                post_sql_query(add_route_query)
                bot.send_message(user, f'Маршрут {city_s} - {city_e} добавлен!')
                msg = bot.send_message(user, 'Укажите дату поездки в формате ddMMYYYY')
                bot.register_next_step_handler(msg, get_date)
    else:
        bot.send_message(message.chat.id, f'Давай досвидания!')
 
# Метод проверяет текущую дату с датами в таблице с поездками. 
# Если дата поездки уже прошла, то метод удаляет их, остаются только сегодняшние и планируемые
def delete_old_trip():
    today = datetime.today()
    check_trip_query = f'SELECT * FROM COMPANIONS;'
    check_trip = post_sql_query(check_trip_query)
    if check_trip:
        for line in check_trip:
            date_trip = datetime.strptime(line[2], '%d%m%Y')
            if date_trip <= today:
                delete_trip_query = f'DELETE FROM COMPANIONS WHERE date_trip= "{line[2]}";'
                post_sql_query(delete_trip_query)
    sleep(86400)
 
# Получаем от пользователя дату в формате (ddmmyyyy) и проверяем ее на корректность. 
# Затем проверяем, чтобы дата поездки не была позже настоящей и вставляем данные в БД:
def get_date(message):
    date = message.text
    user = message.chat.id
    if date.isdigit() and len(date) == 8:
        date_trip = datetime.strptime(date, '%d%m%Y')
        if datetime.today() < date_trip:
            check_temp_table_query = f'SELECT * FROM TEMP WHERE city_start NOT NULL ' \
                                     f'AND city_end NOT NULL AND user_id = {user};'
            temp_data = post_sql_query(check_temp_table_query)
            city_s, city_e = temp_data[0][1], temp_data[0][2]
            search_query = f'SELECT * FROM ROUTE WHERE city_start = "{city_s}" AND city_end = "{city_e}" ;'
            result_query = post_sql_query(search_query)
            route_id = result_query[0][0]
            companions_insert_query = f'INSERT OR IGNORE INTO COMPANIONS(user_id, route_id, date_trip) ' \
                                      f'VALUES({user}, {route_id}, "{date}");'
            post_sql_query(companions_insert_query)
            if temp_data:
                for i in temp_data:
                    search_route(i)
        else:
            msg = bot.send_message(user, 'Поездка должна быть позднее текущей даты')
            bot.register_next_step_handler(msg, get_date)
    else:
        msg = bot.send_message(user, 'Вы указали неверный формат ddMMYYYY')
        bot.register_next_step_handler(msg, get_date)

# В этом методе мы получаем данные о начале и конце маршрута, которые мы получили в методе callback_inline и выводим пользователю
def search_route(temp):	
    user, city_s, city_e, flag = temp
    search_query = f'SELECT * FROM ROUTE WHERE city_start = "{city_s}" AND city_end = "{city_e}" ;'
    result_query = post_sql_query(search_query)
    if result_query:
        route_id = result_query[0][0]
        if flag == 'Найти поездку':
            search_companions_query = f'SELECT * FROM COMPANIONS WHERE route_id={route_id};'
            search_companions_data = post_sql_query(search_companions_query)
            if search_companions_data:
                for line in search_companions_data:
                    friend = line[0]
                    date_trip = line[2]
                    search_friend = f'SELECT * FROM USERS WHERE user_id =  {friend};'
                    friend_info = post_sql_query(search_friend)

                    bot.send_message(user, f'Найден маршрут ✅\n{city_s} - {city_e}\n'
                                           f'Дата поездки🗓: {date_trip}\n' 
                                           f'Контакт пользователя📱: {"Имя: "+ friend_info[0][2],"Телефон: " + friend_info[0][4]}\n'
                                           f'Написать @{friend_info[0][1]}')
            else:
                bot.send_message(user, f'По маршруту {city_s} - {city_e} попутичков нет')
        else:
            check_phone_query = f'SELECT phone_number FROM USERS WHERE user_id={user};'
            check_phone_data = post_sql_query(check_phone_query)
            if check_phone_data[0][0] is None:
                markup = telebot.types.ReplyKeyboardMarkup(True, True)
                button_phone = types.KeyboardButton(text="Отправить номер телефона", request_contact=True)
                markup.add(button_phone)
                bot.send_message(user, 'Поделитесь своим номером?', reply_markup=markup)
        delete_temp_query = f'DELETE FROM TEMP WHERE user_id={user};'
        post_sql_query(delete_temp_query)
 
    else:
        markup = types.ReplyKeyboardMarkup(one_time_keyboard=True, row_width=1)
        markup.add('Да', 'Нет')
        msg = bot.send_message(user, 'Хотите добавить маршрут?', reply_markup=markup)
        bot.register_next_step_handler(msg, add_route)
 
def create_tables():
    users_table_query = f'CREATE TABLE IF NOT EXISTS USERS(user_id INTEGER PRIMARY KEY NOT NULL, ' \
                        f'username TEXT, first_name TEXT, last_name TEXT, phone_number TEXT);'
    post_sql_query(users_table_query)
    temp_user_table_query = f'CREATE TABLE IF NOT EXISTS TEMP(user_id INTEGER PRIMARY KEY NOT NULL, ' \
                            f'city_start TEXT, city_end TEXT, flag TEXT);'
    post_sql_query(temp_user_table_query)
    route_table_query = f'CREATE TABLE IF NOT EXISTS ROUTE(route_id INTEGER, city_start TEXT, city_end TEXT, ' \
                        f'PRIMARY KEY (city_start, city_end));'
    post_sql_query(route_table_query)
    companions_table_query = f'CREATE TABLE IF NOT EXISTS COMPANIONS(user_id INTEGER, route_id INTEGER, date_trip TEXT,' \
                             f'PRIMARY KEY (user_id, route_id));'
    post_sql_query(companions_table_query)
 
def post_sql_query(sql_query):
    with sqlite3.connect('poputki.db') as connection:
        cursor = connection.cursor()
        try:
            cursor.execute(sql_query)
        except Error:
            print(Error)
        result = cursor.fetchall()
        return result
 
def register_user(user, username, first_name, last_name):
    user_check_query = f'SELECT * FROM USERS WHERE user_id = {user};'
    user_check_data = post_sql_query(user_check_query)
    if not user_check_data:
        user_reg_query = f'INSERT OR IGNORE INTO USERS(user_id, username, first_name, last_name)' \
                         f'VALUES ({user}, {username}, {first_name}, {last_name});'
        post_sql_query(user_reg_query)
 
create_tables()
 
Thread(target=delete_old_trip, args=()).start()
 
while True:
    try:
        bot.polling(none_stop=True)
    except Exception as E:
        print(E)