# Начало работы с Qriterra

[English](../getting-started.md) | [Русский](getting-started.md)

Это руководство поможет вам установить и настроить **Qriterra**, подключить его к **Agent Shuttle** и выполнить первые семантические проверки качества кода для сниппетов, отдельных файлов и целых проектов.

---

## 1. Требования и установка

Библиотека требует интерпретатор **Python 3.11** или новее. В качестве зависимостей используются `agent-shuttle` (Agent Shuttle) для транспорта агентов и `mcp` для запуска MCP-сервера.

> [!NOTE]
> Qriterra и Agent Shuttle находятся в отдельных Git-репозиториях. Пакеты пока не опубликованы в PyPI; первым установите Agent Shuttle.

### Создание виртуального окружения

Создайте изолированное окружение и установите оба пакета с GitHub:

#### В Windows (PowerShell):
```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install "git+https://github.com/Plartex/agent-shuttle.git"
.\.venv\Scripts\python.exe -m pip install "git+https://github.com/Plartex/qriterra.git"
```

#### В Linux или macOS:
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install "git+https://github.com/Plartex/agent-shuttle.git"
pip install "git+https://github.com/Plartex/qriterra.git"
```

### Проверка установки

Убедитесь, что исполняемые файлы CLI и MCP-сервера доступны:

```powershell
.\.venv\Scripts\qriterra.exe --help
.\.venv\Scripts\qriterra-mcp.exe --help
```

---

## 2. Подключение к Agent Shuttle

Qriterra выполняет роль клиента-оркестратора. Для непосредственного обращения к языковым моделям он взаимодействует с сервером Agent Shuttle по локальному HTTP-протоколу Agent-to-Agent (A2A).

Поддерживаются следующие агентные харнессы:
- **Codex**: модели OpenAI (`gpt-6-sol` и др.) через Codex CLI или SDK.
- **Antigravity**: модели Google (`gemini-3.8-flash-medium`, `gemini-3.8-pro-high` и др.) через Antigravity CLI.
- **OpenCode**: локальные модели (например, `qwen3.5:9b` в Ollama) или кастомные OpenAI-совместимые эндпоинты.
- **Claude Code**: модели Anthropic через Claude Code CLI.

### Запуск постоянных серверов Bridge

В отдельных терминалах можно запустить серверы Bridge с привязкой к рабочей директории:

```powershell
# Терминал 1: Харнесс Codex на порту 8765
agent-shuttle serve codex --workspace . --port 8765

# Терминал 2: Харнесс Antigravity на порту 8766
agent-shuttle serve antigravity --workspace . --port 8766

# Терминал 3: Харнесс OpenCode на порту 8767 (с JSON-профилем)
agent-shuttle serve profile --profile path/to/opencode.profile.json --workspace . --port 8767
```

Подключить чекер к этим серверам можно параметром `--agent-url` или стандартными переменными окружения:
- `BRIDGE_CODEX_URL=http://127.0.0.1:8765`
- `BRIDGE_ANTIGRAVITY_URL=http://127.0.0.1:8766`
- `BRIDGE_OPENCODE_URL=http://127.0.0.1:8767`
- `BRIDGE_CLAUDE_CODE_URL=http://127.0.0.1:8768`

---

## 3. Выполнение первой проверки

### Проверка фрагмента кода (Snippet)

Используйте подкоманду `evaluate snippet` для проверки фрагмента логики без сохранения файла на диск:

```powershell
qriterra evaluate snippet `
  --code "def calculate_discount(price, customer):
    if customer.is_vip:
        if customer.orders_count > 50:
            if price > 1000:
                return price * 0.3
            return price * 0.2
        return price * 0.1
    return 0" `
  --language python `
  --provider agent-shuttle:codex `
  --agent-url http://127.0.0.1:8765 `
  --rules complex_conditional,deeply_nested_code
```

Анализ фрагмента выполняется в закрытом режиме (`tool_policy="no_tools"`). Модель получает текст напрямую в блоке `REQUEST_DATA_JSON`.

### Проверка отдельного файла (File)

Для отдельного файла содержимое считывается и встраивается в запрос (допустимый размер файла — до 1 МБ):

```powershell
qriterra evaluate file src/checkout.py `
  --provider agent-shuttle:opencode `
  --agent-url http://127.0.0.1:8767 `
  --model qwen3.5:9b `
  --rules long_method,large_class `
  --debug
```

Поскольку код передаётся непосредственно в промпте, агент не выполняет системных вызовов и не читает соседние файлы.

### Проверка проекта (Project)

В проектном режиме агент получает путь к каталогу и самостоятельно применяет инструменты чтения и поиска для анализа связей между модулями:

```powershell
qriterra evaluate project path/to/project `
  --provider agent-shuttle:codex `
  --rules duplicate_code,cyclic_dependency `
  --max-project-seconds 900 `
  --json --output project.evaluation.json
```

> [!TIP]
> **Автоматический запуск харнесса**: Если параметр `--agent-url` не указан, Qriterra самостоятельно поднимает временный процесс Agent Shuttle в целевом каталоге проекта на время проверки и корректно гасит его по завершении.

---

## 4. Настройка MCP (Model Context Protocol)

MCP-сервер позволяет запускать проверки из сред разработки и AI-ассистентов (Claude Desktop, Cursor, PyCharm).

### Пример конфигурации

Добавьте блок `qriterra` в файл настроек MCP (например, `claude_desktop_config.json` или `mcp_config.json`):

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

Сервер экспортирует единственный инструмент: `evaluate(target_type, target, profile="code_smells", ...)`.

---

## 5. Что читать дальше

- [Справочник по Python API](api.md) — программная интеграция и типы данных.
- [Проектная оценка и семантика](project-evaluation.md) — особенности межфайлового анализа и схема 2.0.
- [Каталог правил](rule-catalog.md) — 80 запахов кода и гарантии двуязычного перевода.
- [Архитектура библиотеки](architecture.md) — внутренний поток исполнения и пакетирование.
- [Диагностика и устранение неполадок](troubleshooting.md) — решение типичных проблем.
