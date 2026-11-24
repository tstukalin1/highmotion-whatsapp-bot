# Contributing Guide

Спасибо за интерес к проекту! Вот как сделать вклад.

## Порядок работы

### 1. Fork и клонирование

```bash
# Fork через GitHub UI, затем:
git clone https://github.com/<your-username>/whatsapp-ai-bot.git
cd whatsapp-ai-bot
```

### 2. Создание ветки

Используй конвенцию именования:

| Тип | Формат |
|-----|--------|
| Новая функция | `feat/описание-функции` |
| Исправление бага | `fix/описание-бага` |
| Документация | `docs/описание` |
| Рефакторинг | `refactor/описание` |
| CI / сборка | `chore/описание` |

```bash
git checkout -b feat/telegram-fallback
```

### 3. Настройка окружения разработки

```bash
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
# Заполни .env, установи DEV_MODE=true
```

### 4. Написание кода

- Следуй стилю кода проекта (ruff linter)
- Добавляй docstring к публичным функциям
- Не добавляй незаполненные плейсхолдеры `<<...>>` в исходный код
- Обновляй `PLACEHOLDERS.md` при добавлении новых плейсхолдеров

### 5. Запуск тестов и линтера

```bash
# Линтер
ruff check app/ tests/
ruff format app/ tests/

# Тесты
pytest tests/ -v
```

Все тесты должны проходить перед отправкой PR.

### 6. Формат коммитов (Conventional Commits)

```
<type>(<scope>): <короткое описание>

[опциональное тело]

[опциональные сноски]
```

Допустимые типы:

| Тип | Когда использовать |
|-----|--------------------|
| `feat` | Новая функция |
| `fix` | Исправление бага |
| `docs` | Только документация |
| `style` | Форматирование, пробелы (не логика) |
| `refactor` | Рефакторинг без изменения поведения |
| `test` | Добавление/изменение тестов |
| `chore` | Сборка, зависимости, CI |
| `perf` | Улучшение производительности |

**Примеры:**

```
feat(payments): add Stripe webhook signature verification
fix(ai_agent): handle empty tool_use response from Claude
docs(readme): add ngrok setup instructions
chore(deps): bump anthropic to 0.35.0
```

### 7. Pull Request

1. Пуш ветки в свой fork:
   ```bash
   git push origin feat/my-feature
   ```
2. Открой PR в основном репозитории через GitHub UI
3. Заполни шаблон PR (`.github/pull_request_template.md`)
4. Дождись прохождения CI и ревью

## Вопросы

Если что-то неясно — открой [Issue](../../issues) с вопросом.
