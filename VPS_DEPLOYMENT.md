# 🚀 Инструкция по развертыванию на VPS

## 📋 Предварительные требования

### На VPS должно быть установлено:
```bash
# Python 3.10+
python3 --version

# pip
pip3 --version

# git
git --version

# ffmpeg (для голосовой поддержки Whisper)
ffmpeg -version
```

## 🔧 Установка на VPS

### 1. Подключитесь к VPS
```bash
ssh user@your-vps-ip
```

### 2. Установите необходимые пакеты (если отсутствуют)
```bash
# Ubuntu/Debian
sudo apt update
sudo apt install -y python3 python3-pip python3-venv git ffmpeg

# CentOS/RHEL
sudo yum install -y python3 python3-pip git ffmpeg
```

### 3. Клонируйте репозиторий
```bash
cd ~
git clone https://github.com/mttmxr-creator/BotAICurator.git
cd BotAICurator
```

### 4. Создайте виртуальное окружение
```bash
python3 -m venv venv
source venv/bin/activate
```

### 5. Установите зависимости
```bash
pip install --upgrade pip
pip install -r requirements.txt
```

### 6. Создайте .env файл
```bash
nano .env
```

Вставьте следующее содержимое:
```env
# Telegram Bot Configuration
TELEGRAM_BOT_TOKEN=ваш_токен_главного_бота
ADMIN_BOT_TOKEN=ваш_токен_админ_бота
ADMIN_CHAT_IDS=842335711,283245918,1194568828,600475928,7307142437,1490163772,1254245290,8288594047,8352293994

# OpenAI Configuration
OPENAI_API_KEY=ваш_openai_api_key
OPENAI_ASSISTANT_ID=ваш_основной_assistant_id
CORRECTION_ASSISTANT_ID=ваш_correction_assistant_id
VALIDATION_ASSISTANT_ID=ваш_validation_assistant_id

# LightRAG Configuration
LIGHTRAG_BASE_URL=http://83.222.19.143:8100
LIGHTRAG_API_KEY=aicuratorschool

# Bot Configuration
TRIGGER_KEYWORD=Екатерина хелп
```

Сохраните: `Ctrl+X`, затем `Y`, затем `Enter`

### 7. Создайте директорию для логов
```bash
mkdir -p logs
```

## 🚀 Запуск системы

### ❌ НЕПРАВИЛЬНО - НЕ запускайте bot.py или admin_bot.py отдельно!
```bash
# ❌ python3 bot.py          # Неправильно!
# ❌ python3 admin_bot.py     # Неправильно!
```

### ✅ ПРАВИЛЬНО - Запускайте через main.py (orchestrator)

#### Способ 1: Тестовый запуск (передний план)
```bash
source venv/bin/activate
python3 main.py
```

Проверьте вывод:
```
========================================
🚀 Система запускается...
✅ Основной бот: токен найден
✅ Админ бот: токен найден
✅ Фильтрация: валидатор настроен
✅ Модерация: конфигурация найдена
✅ Логирование Q&A: папка logs/ готова
✅ LightRAG: URL настроен
========================================
```

Нажмите `Ctrl+C` для остановки

#### Способ 2: Production запуск (фоновый режим)
```bash
source venv/bin/activate
nohup python3 main.py > bot.log 2>&1 &
```

Это запустит:
- **Main Bot** (обработка пользователей)
- **Admin Bot** (интерфейс модерации)
- **Priority Queue** (3 worker'а)
- **Moderation Service**
- **Metrics Service**

### Проверка статуса
```bash
# Проверить что боты запущены
ps aux | grep main.py

# Просмотр логов в реальном времени
tail -f bot.log

# Просмотр только ошибок
tail -f bot.log | grep -E "ERROR|CRITICAL"
```

### Остановка ботов
```bash
# Найти процесс
ps aux | grep main.py

# Остановить по PID
kill -9 <PID>

# Или остановить все процессы main.py
pkill -9 -f "python3 main.py"
```

## 🔄 Автоматический перезапуск (systemd)

### 1. Создайте systemd service файл
```bash
sudo nano /etc/systemd/system/telegram-bot.service
```

### 2. Вставьте конфигурацию
```ini
[Unit]
Description=Telegram Bot Moderation System
After=network.target

[Service]
Type=simple
User=your_username
WorkingDirectory=/home/your_username/BotAICurator
Environment="PATH=/home/your_username/BotAICurator/venv/bin"
ExecStart=/home/your_username/BotAICurator/venv/bin/python3 /home/your_username/BotAICurator/main.py
Restart=always
RestartSec=10
StandardOutput=append:/home/your_username/BotAICurator/bot.log
StandardError=append:/home/your_username/BotAICurator/bot_error.log

[Install]
WantedBy=multi-user.target
```

**Замените:**
- `your_username` на ваше имя пользователя VPS
- `/home/your_username/BotAICurator` на полный путь к проекту

### 3. Активируйте service
```bash
# Перезагрузите systemd
sudo systemctl daemon-reload

# Включите автозапуск при загрузке
sudo systemctl enable telegram-bot

# Запустите сервис
sudo systemctl start telegram-bot

# Проверьте статус
sudo systemctl status telegram-bot
```

### 4. Управление сервисом
```bash
# Запуск
sudo systemctl start telegram-bot

# Остановка
sudo systemctl stop telegram-bot

# Перезапуск
sudo systemctl restart telegram-bot

# Просмотр логов
sudo journalctl -u telegram-bot -f

# Просмотр последних 100 строк логов
sudo journalctl -u telegram-bot -n 100
```

## 📊 Мониторинг

### Проверка работы компонентов
```bash
# Логи главного бота
tail -f bot.log | grep "Main Bot"

# Логи админ бота
tail -f bot.log | grep "Admin Bot"

# Логи модерации
tail -f bot.log | grep "moderation"

# QA логи
tail -f logs/qa_log_readable.txt
```

### Проверка метрик
```bash
# Размер базы метрик
ls -lh metrics.db

# QA логи
ls -lh logs/

# Очередь модерации
cat moderation_queue.json | python3 -m json.tool
```

## 🐛 Решение проблем

### Проблема: Боты не запускаются
```bash
# Проверьте .env файл
cat .env

# Проверьте зависимости
pip list | grep telegram

# Проверьте логи ошибок
tail -f bot_error.log
```

### Проблема: Admin bot не отправляет уведомления
```bash
# Проверьте ADMIN_CHAT_IDS
grep ADMIN_CHAT_IDS .env

# Проверьте что admin bot token правильный
grep ADMIN_BOT_TOKEN .env
```

### Проблема: LightRAG не отвечает
```bash
# Проверьте доступность LightRAG
curl http://83.222.19.143:8100/health

# Проверьте логи
tail -f bot.log | grep LightRAG
```

### Проблема: OpenAI ошибки
```bash
# Проверьте API key
grep OPENAI_API_KEY .env

# Проверьте assistant IDs
grep ASSISTANT_ID .env

# Проверьте логи OpenAI запросов
tail -f bot.log | grep openai
```

## 🔐 Безопасность на VPS

### 1. Права доступа к .env
```bash
chmod 600 .env
```

### 2. Firewall (опционально)
```bash
# Если нужен доступ только к боту, закройте все порты кроме SSH
sudo ufw allow 22/tcp
sudo ufw enable
```

### 3. Регулярное обновление
```bash
# Обновление кода
cd ~/BotAICurator
git pull origin main
sudo systemctl restart telegram-bot
```

## 📈 Производительность

### Рекомендуемые ресурсы VPS:
- **CPU**: 2 cores минимум
- **RAM**: 2GB минимум (рекомендуется 4GB)
- **Disk**: 10GB минимум
- **Bandwidth**: Unlimited или 1TB+

### Оптимизация:
```bash
# Очистка старых логов (каждую неделю)
find logs/ -name "*.txt.*" -mtime +7 -delete
find logs/ -name "*.jsonl.*" -mtime +7 -delete

# Очистка старых backup файлов модерации
find . -name "moderation_queue.json.backup.*" -mtime +7 -delete
```

## ✅ Checklist развертывания

- [ ] VPS настроен (Python 3.10+, pip, git, ffmpeg)
- [ ] Репозиторий склонирован
- [ ] Виртуальное окружение создано
- [ ] Зависимости установлены
- [ ] .env файл создан и заполнен
- [ ] Директория logs/ создана
- [ ] Тестовый запуск через `python3 main.py` успешен
- [ ] Production запуск через nohup или systemd настроен
- [ ] Боты отвечают в Telegram
- [ ] Админ бот отправляет уведомления
- [ ] Модерация работает
- [ ] QA логи записываются

## 🆘 Поддержка

Если возникают проблемы:
1. Проверьте логи: `tail -f bot.log`
2. Проверьте статус: `systemctl status telegram-bot`
3. Проверьте .env: `cat .env`
4. Проверьте процессы: `ps aux | grep python`
