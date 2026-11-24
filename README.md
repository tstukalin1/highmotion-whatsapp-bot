# WhatsApp AI Bot для туристического бизнеса

Полнофункциональный бот на базе Claude AI для автоматизации бронирований через WhatsApp Business API.

## Архитектура

```
┌─────────────────────────────────────────────────────────────┐
│                        WhatsApp Cloud API                    │
│           (Meta Graph API v19.0 / Webhooks)                  │
└──────────────────────┬──────────────────────────────────────┘
                       │ POST /webhook
                       ▼
┌─────────────────────────────────────────────────────────────┐
│                    FastAPI Application                       │
│                                                              │
│  ┌─────────────┐   ┌──────────────┐   ┌──────────────────┐ │
│  │  app/main   │──▶│ app/ai_agent │──▶│   app/tools      │ │
│  │  (routes)   │   │ (Claude API) │   │ (DB operations)  │ │
│  └─────────────┘   └──────────────┘   └──────────────────┘ │
│         │                                      │             │
│         ▼                                      ▼             │
│  ┌─────────────┐                    ┌──────────────────┐   │
│  │ app/payments│                    │   app/models     │   │
│  │ (webhooks)  │                    │   (SQLAlchemy)   │   │
│  └─────────────┘                    └──────────────────┘   │
│         │                                      │             │
│         ▼                                      ▼             │
│  ┌─────────────┐   ┌──────────────┐   ┌──────────────────┐ │
│  │  app/qr     │   │app/word_export│  │app/notifications │ │
│  │ (QR codes)  │   │  (.docx)     │   │(WA + Email)      │ │
│  └─────────────┘   └──────────────┘   └──────────────────┘ │
└─────────────────────────────────────────────────────────────┘
                       │
                       ▼
            ┌──────────────────┐
            │   SQLite / PG    │
            │   (Database)     │
            └──────────────────┘
```

**Поток бронирования:**
```
Клиент → WhatsApp → Вебхук → AI Agent (Claude) → Tools → DB
                                   ↓
                              QR для оплаты
                                   ↓
              Платёжный вебхук → подтверждение → Word экспорт
```

---

## Быстрый старт

### 1. Клонирование и настройка

```bash
git clone https://github.com/<<YOUR_USERNAME>>/whatsapp-ai-bot.git
cd whatsapp-ai-bot

# Скопируй и заполни переменные окружения
cp .env.example .env
nano .env
```

### 2. Заполнение плейсхолдеров

Смотри [PLACEHOLDERS.md](PLACEHOLDERS.md) для полного списка всех `<<PLACEHOLDER>>` значений.

Минимально необходимые для запуска:
- `WHATSAPP_ACCESS_TOKEN`
- `WHATSAPP_PHONE_NUMBER_ID`
- `WHATSAPP_VERIFY_TOKEN`
- `WHATSAPP_APP_SECRET`
- `ANTHROPIC_API_KEY`
- `ADMIN_API_TOKEN`
- `BUSINESS_NAME`

### 3. Запуск через Docker Compose

```bash
docker-compose up -d --build
```

Приложение будет доступно на `http://localhost:8000`.

### 4. Локальная разработка

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# Установи DEV_MODE=true в .env
uvicorn app.main:app --reload --port 8000
```

---

## Настройка Meta for Developers

### Шаг 1: Создание приложения

1. Перейди на [developers.facebook.com](https://developers.facebook.com/)
2. **Мои приложения → Создать приложение**
3. Тип: **Business**
4. Добавь продукт: **WhatsApp**

### Шаг 2: Получение токенов

В разделе **WhatsApp → API Setup**:
- Скопируй **Temporary access token** → `WHATSAPP_ACCESS_TOKEN`
- Скопируй **Phone number ID** → `WHATSAPP_PHONE_NUMBER_ID`

В разделе **Settings → Basic**:
- Скопируй **App secret** → `WHATSAPP_APP_SECRET`

### Шаг 3: Настройка вебхука через ngrok

```bash
# Установи ngrok: https://ngrok.com/download
ngrok http 8000
```

Скопируй HTTPS URL (например, `https://abc123.ngrok.io`).

В Meta Developer Console → **WhatsApp → Configuration → Webhooks**:
- **Callback URL**: `https://abc123.ngrok.io/webhook`
- **Verify token**: значение из `WHATSAPP_VERIFY_TOKEN` в .env
- Подпишись на: `messages`

### Шаг 4: Тестирование

Отправь сообщение на тестовый номер WhatsApp — бот должен ответить.

---

## Docker деплой на сервер

```bash
# На сервере:
git clone ...
cp .env.example .env
# Заполни .env
docker-compose up -d

# Проверка логов:
docker-compose logs -f app
```

Для HTTPS на продакшене раскомментируй nginx-сервис в `docker-compose.yml` и настрой SSL-сертификаты (Let's Encrypt / certbot).

---

## API администратора

Все admin-эндпоинты защищены Bearer-токеном из `ADMIN_API_TOKEN`.

### Подтвердить бронирование вручную

```bash
curl -X POST http://localhost:8000/admin/bookings/42/confirm \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN"
```

### Список броней

```bash
# Все брони
curl http://localhost:8000/admin/bookings \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN"

# Фильтр по дате и статусу
curl "http://localhost:8000/admin/bookings?travel_date=2024-07-15&status=paid" \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN"
```

### Отменить бронирование

```bash
curl -X POST http://localhost:8000/admin/bookings/42/cancel \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN"
```

### GDPR удаление клиента

```bash
curl -X DELETE http://localhost:8000/admin/clients/79001234567 \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN"
```

---

## Шаблоны WhatsApp

Шаблоны необходимо создать и одобрить в **WhatsApp Business Manager**.

| Переменная | Шаблон | Параметры |
|---|---|---|
| `WA_TEMPLATE_BOOKING_CONFIRMED` | Подтверждение брони | `{{1}}` — номер брони |
| `WA_TEMPLATE_PAYMENT_REMINDER` | Напоминание об оплате | `{{1}}` — номер брони, `{{2}}` — сумма |

После одобрения шаблонов (обычно 1–3 рабочих дня) установи их имена в `.env`.

---

## Платёжные провайдеры

### СБП (Система Быстрых Платежей)

1. Установи `PAYMENT_PROVIDER=sbp`
2. Заполни в `app/qr.py` плейсхолдеры `<<SBP_*>>`
3. Настрой `PAYMENT_CONFIRMATION_MODE=manual` (или auto с вебхуком банка)

### Stripe

1. Установи `PAYMENT_PROVIDER=stripe`
2. Создай Payment Link в Stripe Dashboard
3. Установи URL ссылки как `PAYMENT_DETAILS`
4. Настрой Stripe вебхук → `POST /webhook/payment`
5. Установи `PAYMENT_WEBHOOK_SECRET` = Stripe webhook signing secret

### Generic

Любые другие реквизиты (ссылка, текст, URL) — `PAYMENT_PROVIDER=generic`, `PAYMENT_DETAILS=...`.

---

## Тесты

```bash
# Запуск всех тестов
pytest tests/ -v

# С отчётом покрытия
pytest tests/ --cov=app --cov-report=html

# Только быстрые unit-тесты
pytest tests/test_tools.py -v
```

---

## Плейсхолдеры

Полный список всех `<<PLACEHOLDER>>` значений смотри в [PLACEHOLDERS.md](PLACEHOLDERS.md).
