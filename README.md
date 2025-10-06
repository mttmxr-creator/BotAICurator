# Екатерина - Telegram Bot Куратор

Телеграм бот с полной интеграцией OpenAI Assistant и LightRAG для интеллектуального поиска и ответов.

## 🚀 Полный функционал

### RAG + OpenAI Pipeline
1. **Пользователь** отправляет сообщение с "Екатерина хелп"
2. **LightRAG** ищет релевантную информацию в базе знаний
3. **OpenAI Assistant** получает: вопрос пользователя + найденную информацию
4. **Ответ** формируется на основе вопроса и контекста

### Активация
- **Ключевое слово**: "Екатерина хелп" (регистр не важен)
- **Примеры**: 
  - "Екатерина хелп, расскажи про Python"
  - "екатерина хелп как установить Docker?"

## 🏗️ Архитектура

```
Пользователь → Telegram Bot
    ↓
Извлечение запроса
    ↓
LightRAG API ← поиск по базе знаний
    ↓
Формирование контекста
    ↓
OpenAI Assistant ← запрос + контекст (или null)
    ↓
Ответ пользователю
```

## 📁 Структура проекта

```
├── bot.py                    # Основная логика бота
├── config.py                 # Управление конфигурацией
├── handlers.py               # Обработчики сообщений с RAG+OpenAI
├── services/
│   ├── __init__.py
│   ├── openai_service.py     # Сервис OpenAI Assistant
│   └── lightrag_service.py   # Сервис LightRAG API
├── .env                      # Переменные окружения
├── .gitignore
├── requirements.txt          # Зависимости Python
├── venv/                     # Виртуальное окружение
└── README.md
```

## 🔧 Установка и запуск

1. **Установите зависимости:**
   ```bash
   cd "/Users/max/Documents/CloudeCode/Бот куратор"
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```

2. **Запустите бота:**
   ```bash
   source venv/bin/activate
   python bot.py
   ```

## ⚙️ Конфигурация

Все настройки в `.env`:
```env
# Telegram Bot
TELEGRAM_BOT_TOKEN=your_telegram_bot_token_here

# OpenAI Assistant
OPENAI_API_KEY=your_openai_api_key_here
OPENAI_ASSISTANT_ID=your_assistant_id_here

# LightRAG API
LIGHTRAG_BASE_URL=http://your_lightrag_server:8100
LIGHTRAG_API_KEY=your_lightrag_api_key_here

# Bot Settings
TRIGGER_KEYWORD=Екатерина хелп
```

## 🔄 Принцип работы

### Сценарий 1: Информация найдена
```
Вопрос: "Екатерина хелп, что такое машинное обучение?"
↓
LightRAG: Находит статьи о ML
↓
OpenAI Assistant получает:
"Вопрос пользователя: что такое машинное обучение?
Информация из базы знаний: [найденная информация]"
↓
Ответ: Детальный ответ на основе найденных данных
```

### Сценарий 2: Информация не найдена
```
Вопрос: "Екатерина хелп, сколько стоит хлеб в Москве?"
↓
LightRAG: Ничего не найдено
↓
OpenAI Assistant получает:
"Вопрос пользователя: сколько стоит хлеб в Москве?
Информация из базы знаний: null"
↓
Ответ: Общий ответ Assistant'а без специфического контекста
```

## 📊 Логирование

Бот ведет подробные логи:
- Получение сообщений от пользователей
- Поиск в LightRAG (результаты и время)
- Запросы к OpenAI Assistant
- Ошибки и исключения

## 🎯 Готовые возможности

✅ **Keyword Detection** - реагирует только на "Екатерина хелп"  
✅ **LightRAG Integration** - поиск по базе знаний  
✅ **OpenAI Assistant** - интеллектуальные ответы  
✅ **RAG Pipeline** - контекстные ответы на основе данных  
✅ **Error Handling** - обработка ошибок API  
✅ **Typing Indicators** - показывает "печатает"  
✅ **Comprehensive Logging** - детальное логирование  

## 🚀 Статус: Готов к продакшену!

Бот полностью настроен и готов отвечать на вопросы пользователей, используя данные из LightRAG и возможности OpenAI Assistant.