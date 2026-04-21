# 3D Printer Timelapse System

Автоматическая система создания таймлапсов для 3D принтеров Flashforge Adventurer 5M с установленным Zmod. Система мониторит состояние принтеров через Moonraker API, автоматически начинает съёмку при старте печати и создаёт видео по её завершении.

посвящено Дяде Роме. 

## Возможности

- 🖨️ **Поддержка нескольких принтеров** — одновременно мониторит несколько принтеров
- 📸 **Автоматическая съёмка** — начинается при старте печати, останавливается по завершении
- 🎬 **Сборка видео** — автоматически создаёт timelapse через ffmpeg
- 🖼️ **Автоматическое превью** — создаёт thumbnail из предпоследнего кадра
- 📁 **Умная структура файлов** — уникальные имена на основе модели и времени
- 📊 **Метаданные** — сохраняет JSON с информацией о каждой печати
- 🔄 **Автоматическое восстановление** — переподключается при ошибках


## Требования

- **Оборудование:**
  - Orange Pi / Raspberry Pi / любой Linux сервер
  - 3D принтер Flashforge Adventurer 5M с установленным Zmod


- **Программное обеспечение:**
  - Python 3.7+
  - FFmpeg (для сборки видео)
  - Moonraker API (доступен через Zmod)
  - ffmpeg (для сборки видео)
- **Для веб интерфейса потребуется web server(apache2, nginx) с поддержкой php**

## Установка

### 1. Клонирование репозитория

```bash
git clone https://github.com/seligor/printer_timelapse.git
cd 3d-printer-timelapse

# Создаём виртуальное окружение
python3 -m venv venv

# Активируем виртуальное окружение
source venv/bin/activate

# Обновляем pip
pip install --upgrade pip

# Устанавливаем необходимые пакеты
pip install aiohttp aiofiles pyyaml

# Или через requirements.txt
pip install -r requirements.txt

# Для Ubuntu/Debian (Orange Pi, Raspberry Pi)
sudo apt update
sudo apt install ffmpeg

# Проверка установки
ffmpeg -version

cp config.yaml.example config.yaml
nano config.yaml
```

# Установка screen (если не установлен)
sudo apt install screen

# Создаём скрипт запуска
nano start_timelapse.sh

```bash

#!/bin/bash
# start_timelapse.sh

# Переходим в директорию проекта
cd /home/seligor/timelapse-program

# Активируем виртуальное окружение
source venv/bin/activate

# Запускаем основной скрипт
python production_timelapse.py
```

```
chmod +x start_timelapse.sh
```

```
# Создаём новую screen сессию с именем timelapse
screen -S timelapse

# Внутри screen сессии запускаем скрипт
./start_timelapse.sh

# Выходим из screen сессии (скрипт продолжает работать)
# Нажмите Ctrl+A, затем D

# Просмотр активных screen сессий
screen -ls

# Подключение к существующей сессии
screen -r timelapse

# Завершение screen сессии (внутри сессии)
exit
```


## Альтернативный запуск через systemd:

/etc/systemd/system/timelapse.service:

```bash
[Unit]
Description=3D Printer Timelapse Service
After=network.target

[Service]
Type=simple
User=seligor
WorkingDirectory=/home/seligor/timelapse-program
ExecStart=/home/seligor/timelapse-program/venv/bin/python /home/seligor/timelapse-program/production_timelapse.py
Restart=always
RestartSec=10
StandardOutput=append:/home/seligor/timelapse-program/timelapse.log
StandardError=append:/home/seligor/timelapse-program/timelapse_error.log

[Install]
WantedBy=multi-user.target
```


Добавил веб часть. Для её работы на вашем сервере потребуется web сервер м поддержкой php

Не забудьте исправить пути на свои. у меня запуск из домашней директории пользователя
