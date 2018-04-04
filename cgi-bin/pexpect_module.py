#!/usr/bin/env python
# -*- coding: utf-8 -*-
# скрипт для сбора конфигурации с микротиков при помощи pexpect

import cgi
import sys
import os
import pexpect
import re
import sqlite3
import datetime
import html
import http.cookies


def save_data_in_database(address, command_output,
                          database='output/mikrotik_database.db'):
    """Функция составляет запрос к БД на основании полученной
    информации и выполняет его. Сделана проверка существования БД
    """
    if os.path.isfile(database):
        connection = sqlite3.connect(database)
        cursor = connection.cursor()

        mac = configuration_parse(command_output)
        now = str(datetime.datetime.today().replace(microsecond=0))
        data = tuple([mac, address, command_output, now])

        query = "INSERT INTO devices VALUES (?, ?, ?, ?)"
        try:
            cursor.execute(query, data)
            print('Конфигурация устройства добавлена в базу данных')
            print('<br>')
        except sqlite3.IntegrityError as error:
            print(error,
                  "Конфигурация этого устройства уже есть в базе данных")
            print('<br>')

        connection.commit()
        connection.close()
    else:
        print("""БД не существует. Перед добавлением данных ее сначала 
              нужно создать """)
        print('<br>')
        print(os.getcwd())
        sys.exit()


def connect_to_device(connection_command, password):
    """Функция подключается к микротику, выполняет команду и 
    возвращает ее результат
    """
    with pexpect.spawn(connection_command, encoding='utf-8') as ssh:
        answer = ssh.expect(['password', 'continue connecting'])
        if answer == 0:
            ssh.sendline(password)
        else:
            ssh.sendline('yes')
            ssh.expect(['password', 'Password'])
            ssh.sendline(password)

        ssh.expect('\[\S+@.+\]\s+>')
        result = command_execute(ssh)

        print('Отключаемся от устройства')
    return (result)


def configuration_parse(data):
    """Выделяем mac адрес устройства"""
    match = None
    for line in data.split('\n'):

        match = re.search('((\S\S:){5}\S\S)', line)
        if match:
            match = match.group()
            break
    if match is None:
        match = 'not specified'
    return (match)


def command_execute(connection_id):
    """Выполняем команду и возвращаем ее вывод пользователю"""
    connection_id.sendline('export compact\r\n')
    # Ищем приглашение системы два раза. Почему так нужно - не понимаю
    connection_id.expect('\[\S+@.+\]\s+>')
    connection_id.expect('\[\S+@.+\]\s+>')
    result = connection_id.before
    connection_id.sendline('quit\r\n')
    return (result)


def mikrotik_connect(connection_id, username, password, address, port):
    """Подключаемся к микротику"""
    connection_id.sendline('ssh {}@{} -p {}'.format(username, address, port))
    answer = connection_id.expect(['password', 'continue connecting'])
    if answer == 0:
        connection_id.sendline(password)
    elif answer == 1:
        connection_id.sendline('yes')
        connection_id.expect(['password'])
        connection_id.sendline(password)
    else:
        print('Непонятная ситуация, нужно разбираться')
        print('<br>')
        print(connection_id.before)
        print('<br>')
        print('#' * 40)
        print('<br>')
        print(connection_id.after)
        print('<br>')
        sys.exit()

    connection_id.expect('\[\S+@.+\]\s+>')


def collect_data_from_devices(parameters):
    """Сбор данных с устройств, доступных напрямую"""
    username, password, ip_addresses, port = parameters

    print(ip_addresses)
    print('<br>')
    print('_' * 40 + '<br>')

    for address in ip_addresses:
        print('=' * 72)
        print('<br>')
        print('Подключаемся к устройству с IP адресом {} ...'.format(address))
        print('<br>')
        connection_command = 'ssh {}@{} -p {}'.format(username, address, port)

        # Формируем данные для сохранения в базе
        try:
            command_output = connect_to_device(connection_command, password)
            print('Конфигурация устройства собрана успешно.'
                  + 'Сохраняем в базе данных')
            print('<br>')
        except pexpect.exceptions.TIMEOUT as error:
            print('Время истекло. Произошла ошибка подключения')
            print('<br>')
            continue
        except pexpect.exceptions.EOF:
            print('Ошибка EOF')
            print('<br>')
            continue

        save_data_in_database(address, command_output)


def collect_data_from_devices_vpn(parameters):
    """Сбор данных устройст, которые находятся за vpn """
    (username_vpn, password_vpn, vpn_gateway,
     username, password, ip_addresses, port) = parameters

    print('Подключаемся к шлюзу VPN с IP адресом {} ...'.format(vpn_gateway))
    print('<br>')
    connection_command = 'ssh {}@{}'.format(username_vpn, vpn_gateway)
    with pexpect.spawn(connection_command, encoding='utf-8') as ssh:
        answer = ssh.expect(['password', 'continue connecting'])
        if answer == 0:
            ssh.sendline(password_vpn)
        else:
            ssh.sendline('yes')
            ssh.expect(['password'])
            ssh.sendline(password_vpn)

        for address in ip_addresses:
            # Блок проверки, находимся ли мы на шлюзе------------------
            try:
                ssh.expect('\[\S+@.+\]\$')
            except pexpect.exceptions.TIMEOUT as error:
                print('<br>')
                print(error, 'Скрипт не нашел приглашения от шлюза VPN.')
                print('<br>')
                print(ssh.before)
                print('<br>')
                print('#' * 40 + '<br>')
                print(ssh.after)
                sys.exit()
            print('Вы находитесь на VPN шлюзе. Что будем делать дальше?')
            print('<br>')
            print('=' * 72 + '<br>')
            # ---------------------------------------------------------

            # Блок подключения к микротику-----------------------------
            print('Подключаемся к устройству с IP адресом {} ...'
                  .format(address))
            print('<br>')
            try:
                mikrotik_connect(ssh, username, password, address, port)

            except pexpect.exceptions.TIMEOUT as error:
                print('Время истекло. Произошла ошибка подключения')
                print('<br>')
                continue
            except pexpect.exceptions.EOF:
                print('Ошибка EOF')
                print('<br>')
                continue
            # ---------------------------------------------------------

            # Блок выполнения команды и сбора результата---------------
            try:
                command_output = command_execute(ssh)
            except pexpect.exceptions.TIMEOUT as error:
                print('Не удалось выполнить все необходимые команды')
                print('<br>')
                print('Пытаемся отключиться от устройства')
                print('<br>')
                ssh.sendline('quit\r\n')
                continue
            # ---------------------------------------------------------

            # Блок сохранения результата-------------------------------
            print('Конфигурация устройства собрана успешно.'
                  + 'Сохраняем в базе данных')
            print('<br>')
            save_data_in_database(address, command_output)
            # ---------------------------------------------------------


# для целей тестирования код проверяет,
# установлена ли кука с именем "name" и если ее нет - устанавливаем
cookie = http.cookies.SimpleCookie(os.environ.get("HTTP_COOKIE"))
name = cookie.get("name")
if name is None:
    print("Set-cookie: name=value")
    print("Content-type: text/html\n")
    print("Cookies!!!")
else:
    print("Content-type: text/html\n")
    print("Cookies:")
    print(name.value)

# Выводим верхнюю часть страницы
print("""<!DOCTYPE HTML>
        <html>
        <head>
            <meta charset="utf-8">
            <title>Сбор данных с устройств</title>
        </head>
        <body>""")

# при запуске CGI-сценарий добавляет путь к текущему рабочему
# каталогу (os.getcwd) в путь поиска модулей sys.path.
sys.path.insert(0, os.getcwd())

# Главный шаблон вывода
replyhtml = """
<p> Процесс произошел. Надо проверять"</p>
</body></html>
"""

# парсинг данных формы
form = cgi.FieldStorage()

# проверяем поле с адресом
ip_addresses = html.escape(form['address'].value)
if os.path.isfile(ip_addresses):
    with open(ip_addresses, 'r') as f:
        ip_addresses = f.read().split('\n')
else:
    ip_addresses = [ip_addresses]

# сохраняем имя, пароль и порт
#todo проверять содержимое полей на наличие данных
username = html.escape(form['username'].value)
password = html.escape(form['password'].value)
port = html.escape(form['port'].value)

# сохраняем данные для подключения к VPN серверу
vpn_gateway = html.escape(form.getfirst('vpn_gateway', ''))
username_vpn = html.escape(form.getfirst('username_vpn', ''))
password_vpn = html.escape(form.getfirst('password_vpn', ''))

if vpn_gateway == '':
    parameters = [username, password, ip_addresses, port]
    collect_data_from_devices(parameters)
else:
    parameters = [username_vpn, password_vpn, vpn_gateway,
                  username, password, ip_addresses, port]
    collect_data_from_devices_vpn(parameters)

# вывод страницы с информацией о завершении
print(replyhtml)
