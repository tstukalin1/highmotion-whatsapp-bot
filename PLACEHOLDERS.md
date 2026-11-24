# Таблица плейсхолдеров

Все плейсхолдеры проекта в формате `<<ИМЯ>>`. Заполни их в `.env` и соответствующих файлах перед запуском в продакшене.

> В DEV_MODE=true приложение запустится с незаполненными плейсхолдерами (только предупреждения). В продакшене (DEV_MODE=false) незаполненные плейсхолдеры вызовут `SystemExit`.

---

| Плейсхолдер | Файл(ы) | Описание | Пример | Обязательный |
|---|---|---|---|---|
| `<<WHATSAPP_ACCESS_TOKEN>>` | `.env` | Временный или постоянный токен доступа Meta Graph API | `EAABc...xyz` | ✅ Да |
| `<<WHATSAPP_PHONE_NUMBER_ID>>` | `.env` | ID номера телефона из WhatsApp Business API | `123456789012345` | ✅ Да |
| `<<WHATSAPP_VERIFY_TOKEN>>` | `.env` | Произвольная строка для верификации вебхука | `my_secret_verify_token_2024` | ✅ Да |
| `<<WHATSAPP_APP_SECRET>>` | `.env` | App Secret из Meta Developer Console | `abc123def456...` | ✅ Да |
| `<<ANTHROPIC_API_KEY>>` | `.env` | API ключ Anthropic (claude.ai или console.anthropic.com) | `sk-ant-api03-...` | ✅ Да |
| `<<ADMIN_API_TOKEN>>` | `.env` | Секретный токен для доступа к /admin/* эндпоинтам | `a9f3e...long_random_string` | ✅ Да |
| `<<PAYMENT_WEBHOOK_SECRET>>` | `.env` | Секрет для верификации подписи платёжного вебхука | `whsec_...` | ✅ Да |
| `<<PAYMENT_DETAILS>>` | `.env` | Реквизиты для оплаты (URL или строка) | `https://buy.stripe.com/xxx` | ✅ Да |
| `<<PAYMENT_PROVIDER>>` | `.env` | Провайдер платежей: `sbp`, `stripe`, `generic` | `sbp` | ✅ Да |
| `<<MANAGER_PHONE>>` | `.env` | WhatsApp номер менеджера (международный формат без +) | `79001234567` | ⚠️ Рек. |
| `<<MANAGER_EMAIL>>` | `.env` | Email менеджера для уведомлений | `manager@mytours.ru` | ⚠️ Рек. |
| `<<BUSINESS_NAME>>` | `.env`, `prompts/system_prompt.md`, `data/business.example.json` | Название компании, используется в промпте и документах | `Солнечные Туры` | ✅ Да |
| `<<LEGAL_REGION>>` | `.env` | Страна/регион для юридических целей | `RU` | ⚠️ Рек. |
| `<<WA_TEMPLATE_PAYMENT_REMINDER>>` | `.env` | Имя одобренного шаблона WhatsApp для напоминания об оплате | `payment_reminder_v1` | ⚠️ Рек. |
| `<<WA_TEMPLATE_BOOKING_CONFIRMED>>` | `.env` | Имя одобренного шаблона WhatsApp для подтверждения брони | `booking_confirmed_v2` | ⚠️ Рек. |
| `<<MAIN_LANGUAGE>>` | `prompts/system_prompt.md` | Основной язык общения бота | `ru` | ✅ Да |
| `<<BUSINESS_RULES>>` | `prompts/system_prompt.md` | Специфические правила бизнеса (добавь в промпт) | `Туры только по Краснодарскому краю` | ⚠️ Рек. |
| `<<CANCELLATION_POLICY_PLACEHOLDER>>` | `prompts/system_prompt.md` | Краткая политика отмены для системного промпта | `Отмена за 24 часа — возврат 100%` | ⚠️ Рек. |
| `<<SBP_RECIPIENT_NAME>>` | `app/qr.py` | Название получателя для СБП QR | `ИП Иванов Иван Иванович` | СБП только |
| `<<SBP_ACCOUNT>>` | `app/qr.py` | Расчётный счёт для СБП QR | `40802810000000000001` | СБП только |
| `<<SBP_BANK_NAME>>` | `app/qr.py` | Название банка для СБП QR | `ПАО Сбербанк` | СБП только |
| `<<SBP_BIC>>` | `app/qr.py` | БИК банка для СБП QR | `044525225` | СБП только |
| `<<PACKAGE_1_NAME>>` | `data/packages.example.json` | Название первого турпакета | `Горный тур «Роза Хутор»` | ✅ Да |
| `<<PACKAGE_1_DESCRIPTION>>` | `data/packages.example.json` | Описание первого турпакета | `Однодневный тур в горы с гидом` | ✅ Да |
| `<<PACKAGE_1_PRICE>>` | `data/packages.example.json` | Цена первого пакета в рублях | `3500` | ✅ Да |
| `<<PACKAGE_1_CAPACITY>>` | `data/packages.example.json` | Максимальное количество человек в группе | `12` | ✅ Да |
| `<<PACKAGE_1_DURATION_HOURS>>` | `data/packages.example.json` | Длительность тура в часах | `10` | ✅ Да |
| `<<PACKAGE_1_INCLUDES_1>>` | `data/packages.example.json` | Первое включённое в пакет | `Трансфер от/до отеля` | ✅ Да |
| `<<PACKAGE_1_INCLUDES_2>>` | `data/packages.example.json` | Второе включённое в пакет | `Обед на смотровой площадке` | ✅ Да |
| `<<PACKAGE_2_NAME>>` | `data/packages.example.json` | Название второго турпакета | `Морская прогулка` | ✅ Да |
| `<<PACKAGE_2_DESCRIPTION>>` | `data/packages.example.json` | Описание второго турпакета | `Прогулка на яхте вдоль побережья` | ✅ Да |
| `<<PACKAGE_2_PRICE>>` | `data/packages.example.json` | Цена второго пакета | `2500` | ✅ Да |
| `<<PACKAGE_2_CAPACITY>>` | `data/packages.example.json` | Вместимость второго тура | `8` | ✅ Да |
| `<<PACKAGE_2_DURATION_HOURS>>` | `data/packages.example.json` | Длительность второго тура в часах | `4` | ✅ Да |
| `<<PACKAGE_2_INCLUDES_1>>` | `data/packages.example.json` | Первое включённое во второй пакет | `Снаряжение для снорклинга` | ✅ Да |
| `<<PACKAGE_2_INCLUDES_2>>` | `data/packages.example.json` | Второе включённое во второй пакет | `Лёгкие закуски и напитки` | ✅ Да |
| `<<PACKAGE_3_NAME>>` | `data/packages.example.json` | Название третьего турпакета | `Дегустационный тур по виноградникам` | ✅ Да |
| `<<PACKAGE_3_DESCRIPTION>>` | `data/packages.example.json` | Описание третьего турпакета | `Посещение 3 виноградников с дегустацией` | ✅ Да |
| `<<PACKAGE_3_PRICE>>` | `data/packages.example.json` | Цена третьего пакета | `4000` | ✅ Да |
| `<<PACKAGE_3_CAPACITY>>` | `data/packages.example.json` | Вместимость третьего тура | `15` | ✅ Да |
| `<<PACKAGE_3_DURATION_HOURS>>` | `data/packages.example.json` | Длительность третьего тура в часах | `6` | ✅ Да |
| `<<PACKAGE_3_INCLUDES_1>>` | `data/packages.example.json` | Первое включённое в третий пакет | `Трансфер` | ✅ Да |
| `<<PACKAGE_3_INCLUDES_2>>` | `data/packages.example.json` | Второе включённое в третий пакет | `Дегустация 5 вин` | ✅ Да |
| `<<BUSINESS_TAGLINE>>` | `data/business.example.json` | Слоган компании | `Незабываемые путешествия с комфортом` | ⚠️ Рек. |
| `<<BUSINESS_PHONE>>` | `data/business.example.json` | Телефон компании для документов | `+7 900 123-45-67` | ⚠️ Рек. |
| `<<BUSINESS_EMAIL>>` | `data/business.example.json` | Email компании | `info@mytours.ru` | ⚠️ Рек. |
| `<<BUSINESS_WEBSITE>>` | `data/business.example.json` | Сайт компании | `https://mytours.ru` | ⚠️ Рек. |
| `<<BUSINESS_ADDRESS>>` | `data/business.example.json` | Физический адрес компании | `г. Сочи, ул. Навагинская 1` | ⚠️ Рек. |
| `<<BUSINESS_LOGO_PATH>>` | `data/business.example.json` | Путь к файлу логотипа для Word документов | `assets/logo.png` | ⚠️ Рек. |
| `<<CANCELLATION_POLICY>>` | `data/business.example.json` | Полная политика отмены для документов | `Отмена за 48 часов до тура — возврат 100%...` | ⚠️ Рек. |
| `<<WORKING_HOURS>>` | `data/business.example.json` | Часы работы компании | `Пн-Вс 9:00–21:00` | ⚠️ Рек. |
| `<<COPYRIGHT_HOLDER>>` | `LICENSE` | Имя правообладателя для лицензии MIT | `ИП Иванов Иван Иванович` | ✅ Да |

---

## Как заполнить плейсхолдеры

### Шаг 1: .env файл
```bash
cp .env.example .env
nano .env   # или любой редактор
```

### Шаг 2: data/*.example.json
Скопируй и переименуй:
```bash
cp data/packages.example.json data/packages.json
cp data/business.example.json data/business.json
```
Отредактируй оба файла, заменив все `<<...>>` реальными значениями.

### Шаг 3: app/qr.py (только для СБП)
Найди в файле строки с `<<SBP_*>>` и замени банковскими реквизитами.

### Шаг 4: prompts/system_prompt.md
Замени `<<BUSINESS_NAME>>`, `<<MAIN_LANGUAGE>>`, `<<BUSINESS_RULES>>`, `<<CANCELLATION_POLICY_PLACEHOLDER>>`.

### Шаг 5: LICENSE
Замени `<<COPYRIGHT_HOLDER>>` своим именем / названием компании.

### Проверка
```bash
# Убедись, что в .env нет незаполненных плейсхолдеров:
grep -r '<<' .env data/ prompts/ app/qr.py LICENSE
```
