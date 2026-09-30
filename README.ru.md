# Qriterra

[![Тесты](https://github.com/Plartex/qriterra/actions/workflows/tests.yml/badge.svg)](https://github.com/Plartex/qriterra/actions/workflows/tests.yml)
[![Лицензия MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python Version](https://img.shields.io/badge/python-3.11%2B-blue.svg)](pyproject.toml)
[![Architecture](https://img.shields.io/badge/architecture-LLM--first-brightgreen.svg)](docs/ru/architecture.md)
[![Rule Catalog](https://img.shields.io/badge/rules-80%20smells-orange.svg)](docs/ru/rule-catalog.md)
[![Language](https://img.shields.io/badge/docs-English%20%7C%20Русский-lightgrey.svg)](README.md)

[English](README.md) | [Русский](README.ru.md)

**Qriterra** — первый шаг к расширяемой платформе оценки. Идея проекта — применять к объекту настраиваемые проверки и возвращать понятный структурированный результат, подкреплённый доказательствами.

Поддерживаются три типа целей анализа:
- **`snippet`**: фрагмент кода в оперативной памяти с опциональным указанием языка.
- **`file`**: отдельный файл на диске (встраивается в промпт размером до 1 МБ для автономного анализа без вызова инструментов).
- **`project`**: каталог проекта со множеством файлов, исследуемый агентом интерактивно с помощью инструментов поиска и чтения.

---

## Agent Shuttle как отдельная зависимость

Qriterra расположен в самостоятельном Git-репозитории и не содержит собственного кода исполнения моделей. В качестве отдельной транспортной зависимости используется [**Agent Shuttle**](https://github.com/Plartex/agent-shuttle) (`agent-shuttle`).

- **Agent Shuttle** предоставляет стандартные HTTP-эндпоинты протокола Agent-to-Agent (A2A) для управления локальными харнессами: **Codex**, **Antigravity**, **OpenCode** и **Claude Code**.
- **Qriterra** оркестрирует проверку: загружает базу из 80 запахов кода, стабильно разбивает правила на пакеты, управляет сессиями агентов, строго валидирует структурированные JSON-ответы, проверяет цитаты по реальным строкам файлов и вычисляет детерминированный балл качества.
- Agent Shuttle ничего не знает о запахах кода, пакетах и оценках; Qriterra не управляет низкоуровневыми подпроцессами CLI и особенностями конкретных харнессов.

---

## Установка

> [!NOTE]
> Пакеты пока не опубликованы в PyPI. Сначала установите Agent Shuttle, затем Qriterra напрямую из их GitHub-репозиториев.

Создайте виртуальное окружение (Python 3.11 или новее) и установите обе библиотеки с GitHub:

```powershell
python -m venv .venv
# В Windows:
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install "git+https://github.com/Plartex/agent-shuttle.git"
.\.venv\Scripts\python.exe -m pip install "git+https://github.com/Plartex/qriterra.git"
```

В Linux или macOS:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install "git+https://github.com/Plartex/agent-shuttle.git"
pip install "git+https://github.com/Plartex/qriterra.git"
```

После установки в виртуальном окружении становятся доступны две консольные команды:
- `qriterra`: консольный интерфейс запуска проверок.
- `qriterra-mcp`: FastMCP stdio-сервер с инструментом `evaluate`.

Для совместимости сохраняются импорт `agent_code_checker` и команды
`agent-code-checker` / `agent-code-checker-mcp`.

---

## Быстрый старт

### 1. Проверка фрагмента кода (Snippet)

Передайте код напрямую через CLI, используя локальный или удалённый эндпоинт Agent Shuttle:

```powershell
qriterra evaluate snippet `
  --code "def process(data): return [x * 2 for x in data if x > 0]" `
  --language python `
  --provider agent-shuttle:codex `
  --agent-url http://127.0.0.1:8765 `
  --rules long_method,complex_conditional
```

### 2. Проверка отдельного файла (File)

Содержимое файла встраивается в промпт без предоставления агенту системных инструментов:

```powershell
qriterra evaluate file src/service.py `
  --provider agent-shuttle:opencode `
  --agent-url http://127.0.0.1:8767 `
  --model qwen3.5:9b `
  --rules long_method,large_class `
  --json --output service.report.json
```

### 3. Проверка каталога проекта (Project)

В проектном режиме агент использует инструменты чтения и поиска внутри рабочей области:

```powershell
qriterra evaluate project path/to/project `
  --provider agent-shuttle:codex `
  --rules duplicate_code,cyclic_dependency `
  --max-project-seconds 900 `
  --debug
```

Если для встроенных харнессов (`codex`, `antigravity`, `opencode`, `claude_code`) параметр `--agent-url` не указан, CLI автоматически запустит временный процесс Agent Shuttle, привязанный к каталогу проверяемого проекта. Старый префикс провайдера `agent-bridge:` сохранён для совместимости.

---

## Режимы использования

### Консольный интерфейс (CLI)

```text
qriterra evaluate <snippet|file|project> [target] [параметры]
```

Основные параметры CLI:
- `--rules <id1,id2>`: идентификаторы правил через запятую (по умолчанию проверяются все 80 правил профиля).
- `--batch-size <N>`: число правил в одном запросе к агенту (по умолчанию: `10`).
- `--model <name>`: переопределение модели (например, `gpt-6-sol`, `gemini-3.8-flash-medium`, `qwen3.5:9b`).
- `--reasoning-effort <effort>`: уровень рассуждений (`low`, `medium`, `high`).
- `--tool-policy <policy>`: уровень разрешений агента (`no_tools`, `read_only`, `workspace_write`, `full_access`).
- `--prompt-language <auto|en|ru>`: язык правил в промпте (`auto` выбирает английский для встроенного каталога).
- `--max-project-seconds <sec>`: лимит времени на проверку проекта (по умолчанию: `1800`).
- `--no-session`: независимый запрос на каждый пакет (запрещено для `project`).
- `--json`: вывод отчёта в структурированном формате JSON вместо отформатированного текста.
- `--debug`: вывод потока событий трассировки в `stderr` и сохранение `debug_trace` в отчёте.
- `--output <path>`: сохранение отчёта в файл на диске.

### Python API

```python
import asyncio
from qriterra import (
    EvaluationService,
    EvaluationTarget,
    format_text_report,
    load_code_smells_profile,
)
from qriterra.providers import AgentBridgeProvider

async def main():
    # 1. Подключение к серверу Agent Shuttle
    provider = AgentBridgeProvider(
        peer_url="http://127.0.0.1:8765",
        agent="codex",
        tool_policy="read_only",
    )

    # 2. Выбор правил и цели
    profile = load_code_smells_profile(rule_ids=["long_method", "large_class"])
    target = EvaluationTarget.file("src/service.py")

    # 3. Выполнение проверки
    service = EvaluationService(provider)
    report = await service.evaluate(target, profile, debug=True)

    # 4. Вывод результатов
    print(format_text_report(report))
    print(f"Оценка качества: {report.summary.quality_score}%")

if __name__ == "__main__":
    asyncio.run(main())
```

### Model Context Protocol (MCP)

Библиотека предоставляет MCP-сервер (`qriterra-mcp`) с инструментом `evaluate`. Добавьте его в конфигурацию вашего редактора или среды разработки (Claude Desktop, Codex, Cursor):

```json
{
  "mcpServers": {
    "qriterra": {
      "command": "path/to/.venv/Scripts/qriterra-mcp.exe",
      "args": [],
      "env": {
        "BRIDGE_CODEX_URL": "http://127.0.0.1:8765",
        "BRIDGE_ANTIGRAVITY_URL": "http://127.0.0.1:8766"
      }
    }
  }
}
```

---

## Рабочие области, разрешения и безопасность

| Область цели | Окружение выполнения | Допустимые политики инструментов |
|---|---|---|
| `snippet` | Строка в памяти | `no_tools` (по умолчанию) |
| `file` | Встроенный текст (< 1 МБ) | `no_tools` (по умолчанию) |
| `project` | Каталог на диске | `read_only` (по умолчанию для Codex, OpenCode, Claude Code), `workspace_write`, `full_access` (обязательно для Antigravity) |

> [!WARNING]
> **Antigravity и режим `full_access`**: Antigravity CLI не поддерживает гарантированный read-only режим песочницы при автоматическом запуске в headless-режиме. Поэтому временный запуск Antigravity для проектов принудительно требует `full_access`. Чекер просит агента не изменять файлы, однако это ограничение обеспечивается инструкцией в промпте, а не песочницей операционной системы.

> [!IMPORTANT]
> **Безопасность локального A2A**: Эндпоинты Agent Shuttle используют неаутентифицированный HTTP-протокол на `127.0.0.1`. Не открывайте эти порты во внешнюю сеть. Анализируемый исходный код всегда трактуется как недоверенные данные во избежание атак внедрения промптов (prompt injection).

---

## Оценка качества и результаты проверок

Каждое проверенное правило получает ровно один из пяти статусов:
- **`passed`**: правило проверено, нарушение не обнаружено.
- **`failed`**: обнаружен запах кода, приведено подтверждённое доказательство с номерами строк.
- **`skipped`**: область цели принципиально не позволяет применить правило (например, циклические зависимости для изолированного сниппета).
- **`inconclusive`**: правило применимо, но предоставленного контекста или лимита времени недостаточно для однозначного вывода.
- **`error`**: технический или протокольный сбой (невалидный JSON от агента, таймаут, ошибка связи).

### Детерминированная оценка качества (Quality Score)

Оценка качества взвешивается по степени критичности нарушений (`low = 1`, `medium = 2`, `high = 3`, `critical = 5`):

$$\text{Quality Score} = 100 \times \frac{\sum \text{вес}(\text{passed})}{\sum \text{вес}(\text{passed}) + \sum \text{вес}(\text{failed})}$$

**Когда оценка равна `N/A` (`null`)?**
Для предотвращения ложно-высоких оценок:
1. При наличии хотя бы одной ошибки (**`error`**) оценка равна `null`.
2. В режиме **`project`**, если хотя бы одно правило имеет неполный охват (**`partial`**) или завершилось со статусом **`inconclusive`** / **`skipped`**, оценка равна `null`.
3. Если нет ни одного оценённого правила (`passed_weight + failed_weight == 0`), оценка равна `null`.

**Покрытие оценки (Assessment Coverage)**:
$$\text{Assessment Coverage} = 100 \times \frac{\text{Число оценённых правил}}{\text{Всего запрошенных правил}}$$

---

## Тестирование

Запуск полного набора оффлайн unit- и интеграционных тестов без расхода модельной квоты:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Все 62 теста используют локальные mock-провайдеры и выполняются приблизительно за 1.5 секунды.

---

## Документация

- [Руководство по началу работы](docs/ru/getting-started.md)
- [Справочник по Python API](docs/ru/api.md)
- [Проектная оценка и семантика](docs/ru/project-evaluation.md)
- [Каталог правил и двуязычный паритет](docs/ru/rule-catalog.md)
- [Архитектура и протоколы](docs/ru/architecture.md)
- [Диагностика и устранение неполадок](docs/ru/troubleshooting.md)
- [Руководство для разработчиков (Contributing)](CONTRIBUTING.ru.md)
- [Политика безопасности (Security)](SECURITY.ru.md)
- [Evaluation Framework Design](docs/evaluation-framework-design.md) (Оригинальный RFC дизайн-документ на русском)
