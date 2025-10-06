# 🤖 Telegram Bot Moderation System

Продакшен-ready система модерации для Telegram с RAG pipeline, админским интерфейсом, голосовой поддержкой и комплексной аналитикой.

## 🚀 Возможности системы

### Основной функционал
- **RAG Pipeline**: LightRAG + OpenAI Assistant для интеллектуальных ответов
- **Система модерации**: Очередь сообщений с админским утверждением
- **Админ-бот**: Полноценный интерфейс модерации с inline-кнопками
- **Голосовая поддержка**: Whisper для транскрибации голосовых сообщений
- **AI-коррекция**: Улучшение ответов через отдельный OpenAI Assistant
- **QA Logging**: Двойной формат логирования (JSON + readable текст)
- **Комплексная аналитика**: Метрики фильтрации и производительности

### Система фильтрации
1. **Stage 1**: Проверка длины сообщения (минимум 10 символов)
2. **Stage 2**: AI-валидация рабочего контекста через OpenAI
3. **Stage 3**: ОТКЛЮЧЕН (LightRAG relevance check - избыточен)

## 🏗️ Архитектура системы

```
┌─────────────────────────────────────────────────────────────────┐
│                    МНОГОУРОВНЕВАЯ СИСТЕМА                        │
└─────────────────────────────────────────────────────────────────┘

Пользователь → Main Bot (bot.py)
    ↓
handlers.py: Обработка сообщений
    ↓
┌─────────────────────────────────────────┐
│  Система фильтрации (message_filter.py) │
│  ├─ Stage 1: Length Check (≥10 chars)   │
│  └─ Stage 2: Work Validation (OpenAI)   │
└─────────────────────────────────────────┘
    ↓
┌──────────────────────────────────────────────┐
│  RAG Pipeline                                │
│  ├─ LightRAG: Поиск контекста (120s timeout)│
│  └─ OpenAI Assistant: Генерация ответа      │
└──────────────────────────────────────────────┘
    ↓
QA Logger: Логирование успешных взаимодействий
    ↓
┌──────────────────────────────────────────┐
│  Moderation Queue                        │
│  (moderation_service.py)                 │
│  ├─ Pending messages                     │
│  ├─ Persistence (JSON)                   │
│  └─ Admin notifications                  │
└──────────────────────────────────────────┘
    ↓
Admin Bot (admin_bot.py)
    ↓
Админ действия:
├─ ✅ Отправить (как есть)
├─ ✏️ Редактировать (текст/голос)
│   └─ correction_service.py → AI улучшение
├─ ❌ Отклонить
└─ 📄 Показать полный текст
    ↓
bot_communication.py: Отправка пользователю
    ↓
✅ Пользователь получает ответ
```

## 📁 Структура проекта

```
Бот куратор/
├── main.py                              # 🎯 Orchestrator с валидацией компонентов
├── config.py                           # ⚙️ Конфигурация
├── .env                                # 🔐 Переменные окружения
├── bot.py                              # 🤖 Main bot
├── admin_bot.py                        # 👨‍💼 Admin bot с Moscow time
├── handlers.py                         # 📨 Message handlers + QA logging
├── requirements.txt                    # 📦 Зависимости
│
├── services/                           # 🔧 Service layer
│   ├── openai_service.py              # 🤖 OpenAI Assistant
│   ├── lightrag_service.py            # 🔍 Knowledge base search
│   ├── moderation_service.py          # 📋 Moderation queue
│   ├── correction_service.py          # ✏️ AI corrections
│   ├── bot_communication.py           # 🔄 Inter-bot messaging
│   ├── whisper_service.py             # 🎤 Voice transcription
│   ├── message_filter.py              # 🔍 Multi-stage filtering
│   ├── metrics_service.py             # 📊 Analytics
│   ├── qa_logger.py                   # 📝 QA logging system
│   └── validation_service.py          # ✅ Work validation
│
├── scripts/                            # 🛠️ Utility scripts
│   └── prepare_qa_for_lightrag.py     # 📋 QA → LightRAG preparation
│
├── logs/                               # 📊 QA logging
│   ├── qa_log.jsonl                   # 🗃️ Machine-readable
│   ├── qa_log_readable.txt            # 📖 Human-readable
│   └── (rotated files .1 - .10)       # 🔄 File rotation
│
├── docs/                               # 📚 Documentation
│   ├── ENHANCED_MODERATION_BUILD_SUMMARY.md
│   ├── METRICS_SERVICE_BUILD_SUMMARY.md
│   ├── WHISPER_SERVICE_BUILD_SUMMARY.md
│   └── DEPLOYMENT_GUIDE.md
│
└── utils/                              # 🛠️ Utilities
    └── text_utils.py                  # Text processing
```

## 🔧 Установка и настройка

### 1. Клонирование репозитория
```bash
git clone https://github.com/mttmxr-creator/BotAICurator.git
cd BotAICurator
```

### 2. Установка зависимостей
```bash
pip install -r requirements.txt
```

### 3. Настройка .env файла

```env
# Telegram Bot Configuration
TELEGRAM_BOT_TOKEN=your_main_bot_token_here
ADMIN_BOT_TOKEN=your_admin_bot_token_here
ADMIN_CHAT_IDS=admin_id1,admin_id2,admin_id3

# OpenAI Configuration
OPENAI_API_KEY=your_openai_api_key_here
OPENAI_ASSISTANT_ID=your_main_assistant_id
CORRECTION_ASSISTANT_ID=your_correction_assistant_id
VALIDATION_ASSISTANT_ID=your_validation_assistant_id

# LightRAG Configuration
LIGHTRAG_BASE_URL=http://your_lightrag_server:8100
LIGHTRAG_API_KEY=your_lightrag_api_key
```

### 4. Запуск системы
```bash
python3 main.py
```

## 📊 Полный поток обработки сообщения

```
1. Пользователь отправляет сообщение в групповой чат
   ↓
2. handlers.py получает сообщение
   ↓
3. Проверка: сообщение от админа? → игнорируем
   ↓
4. Stage 1: Длина ≥ 10 символов? → продолжаем
   ↓
5. Stage 2: Валидация через OpenAI (work-related?) → продолжаем
   ↓
6. LightRAG поиск контекста (timeout 120s)
   ↓
7. OpenAI Assistant генерирует ответ
   ↓
8. QA Logger сохраняет взаимодействие (dual format)
   ↓
9. Отправка в moderation queue (persistence)
   ↓
10. Admin Bot уведомляет всех админов (Moscow time)
   ↓
11. Админ выбирает действие:
    • Отправить → пользователю
    • Редактировать → AI коррекция → пользователю
    • Отклонить → удалить из очереди
```

## 🎛️ Особенности системы

### Защита от спама
- ✅ Игнорирование сообщений от администраторов
- ✅ Двухэтапная фильтрация (длина + AI валидация)
- ✅ Priority queue для обработки сообщений

### Модерация
- ✅ Persistent queue (JSON storage)
- ✅ Multi-admin координация
- ✅ Moscow time для всех админов
- ✅ Статусы: pending, editing, sent, rejected, expired

### Аналитика
- ✅ Filtering metrics (по каждому этапу)
- ✅ QA logging с автоматической ротацией файлов
- ✅ Performance dashboard
- ✅ Processing time tracking

### Голосовая поддержка
- ✅ Whisper транскрибация голосовых сообщений админов
- ✅ AI улучшение транскрибированного текста
- ✅ Автоматическая очистка временных файлов

## 🔒 Безопасность

- Все секретные данные в `.env` (не в репозитории)
- `.gitignore` защищает от утечки логов и БД
- Admin access control через `Config.is_admin()`
- Временные файлы голоса автоматически удаляются

## 📈 Метрики и мониторинг

### Filtering Metrics
```python
{
    "length_check": {"total": 45, "percentage": 15.2},
    "work_validation": {"total": 23, "percentage": 7.8},
    "successful": {"total": 161, "percentage": 54.4}
}
```

### QA Logging
- Machine-readable: `logs/qa_log.jsonl`
- Human-readable: `logs/qa_log_readable.txt`
- Auto-rotation: 10MB per file, keeps 10 files
- Thread-safe operations

## 🛠️ Утилиты

### LightRAG Data Preparation
```bash
python3 scripts/prepare_qa_for_lightrag.py
```
Обрабатывает QA логи и создаёт `ready_for_lightrag.txt` для загрузки в базу знаний.

## 🚀 Production Ready

Система полностью готова к продакшену:
- ✅ Multi-bot architecture
- ✅ Comprehensive error handling
- ✅ Automatic file rotation
- ✅ Moscow time synchronization
- ✅ Admin coordination
- ✅ Performance analytics
- ✅ Quality assurance logging

## 📝 Документация

Полная документация доступна в `CLAUDE.md` - подробное техническое описание всех компонентов системы.

## 🤝 Contributing

Проект использует Git для версионирования. Все чувствительные данные защищены `.gitignore`.
