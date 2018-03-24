#!/usr/bin/env python
# -*- coding: utf-8 -*-
#скрипт для сбора конфигурации с микротиков при помощи pexpect

import getpass
import pexpect
import sys
import re
import os
import sqlite3
import datetime
import argparse


def save_data_in_database(address, command_output, 
                          database='mikrotik_database.db'):
    """Функция составляет запрос к БД на основании полученной информации и 
    выполняет его. Сделана проверка существования БД
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
        except sqlite3.IntegrityError as error:
            print(error, 
                  "\nКонфигурация этого устройства уже есть в базе данных\n")        

        connection.commit()
        connection.close()
    else:
        print("""БД не существует. Перед добавлением данных ее сначала 
              нужно создать """)
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
    result  = connection_id.before   
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
        print(connection_id.before)
        print('#' * 40)
        print(connection_id.after)
        sys.exit()

    connection_id.expect('\[\S+@.+\]\s+>')


def collect_data_from_devices(parameters):
    """Сбор данных с устройств, доступных напрямую"""
    username, password, ip_addresses, port = parameters
    for address in ip_addresses:
        print('='*72)
        print('Подключаемся к устройству с IP адресом {} ...'.format(address))
        connection_command = 'ssh {}@{} -p {}'.format(username, address, port)
        
        # Формируем данные для сохранения в базе
        try:
            command_output = connect_to_device(connection_command, password)            
            print('Конфигурация устройства собрана успешно.'
                  + 'Сохраняем в базе данных')
        except pexpect.exceptions.TIMEOUT as error:
            print('Время истекло. Произошла ошибка подключения\n')
            continue
        except pexpect.exceptions.EOF:
            print('Ошибка EOF\n')
            continue

        save_data_in_database(address, command_output)  


def collect_data_from_devices_vpn(parameters):
    """Сбор данных устройст, которые находятся за vpn """ 
    (username_vpn, password_vpn, vpn_gateway, 
     username, password, ip_addresses, port) = parameters

    print('Подключаемся к шлюзу VPN с IP адресом {} ...'.format(vpn_gateway))
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
                print(error, '\nСкрипт не нашел приглашения от шлюза VPN.')
                print(ssh.before)
                print('#' * 40)
                print(ssh.after)
                sys.exit()
            print('Вы находитесь на VPN шлюзе. Что будем делать дальше?')
            print('='*72)
            # ---------------------------------------------------------

            # Блок подключения к микротику-----------------------------
            print('Подключаемся к устройству с IP адресом {} ...'
                  .format(address))            
            try: 
                mikrotik_connect(ssh, username, password, address, port)

            except pexpect.exceptions.TIMEOUT as error:
                print('Время истекло. Произошла ошибка подключения\n')
                continue
            except pexpect.exceptions.EOF:
                print('Ошибка EOF\n')
                continue
            #---------------------------------------------------------- 

            # Блок выполнения команды и сбора результата---------------
            try:
                command_output = command_execute(ssh)
            except pexpect.exceptions.TIMEOUT as error:
                print('Не удалось выполнить все необходимые команды')
                print('Пытаемся отключиться от устройства')
                ssh.sendline('quit\r\n')
                continue            
            # ---------------------------------------------------------
            
            # Блок сохранения результата-------------------------------
            print('Конфигурация устройства собрана успешно.'
                  + 'Сохраняем в базе данных')           
            save_data_in_database(address, command_output)  
            # ---------------------------------------------------------
    

def auth(args):
    """Функция авторизации. Возвращает набор параметров для подключения"""
    ip_addresses = []
    if args.vpn_gateway == 'notvpn':
        print('Целевые устройства доступны напрямую')
        # Запрашиваем у пользователя данные для авторизации 
        print('Введите учетные данные для авторизации на устройствах:')
        username = input('Username: ')
        password = getpass.getpass()
        port = input('Port: ')

        if os.path.isfile(args.destination):
            with open(args.destination, 'r') as f:
                ip_addresses = f.read().split('\n')
                print(ip_addresses)
        else:
            ip_addresses.append(args.destination)

        result = [username, password, ip_addresses, port]   

        return (result)

    else:
        print('Целевые устройства находятся в VPN')

        print('Введите учетные данные для авторизации на шлюзе VPN:')
        username_vpn = input('Username: ')
        password_vpn = getpass.getpass()

        print('Введите учетные данные для авторизации на устройствах:')  
        username = input('Username: ')
        password = getpass.getpass()
        port = input('Port: ')

        if os.path.isfile(args.destination):
            with open(args.destination, 'r') as f:
                ip_addresses = f.read().split('\n')
                print(ip_addresses)
        else:   
            ip_addresses.append(args.destination)

        result = [username_vpn, password_vpn, 
                  args.vpn_gateway, username, 
                  password, ip_addresses, port]

        return (result)


# Обработка переданных пользователем аргументов
parser = argparse.ArgumentParser(description='collect_data_from_devices')
parser.add_argument('-v', action='store', 
                    dest='vpn_gateway', 
                    default='notvpn')
parser.add_argument('-a', action='store', dest='destination', required=True)
args = parser.parse_args()

parameters = auth(args)
if len(parameters) == 4:
    collect_data_from_devices(parameters)
else:
    collect_data_from_devices_vpn(parameters)