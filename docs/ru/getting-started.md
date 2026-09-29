# Начало работы с Agent Code Checker

[English](../getting-started.md) | [Русский](getting-started.md)

Это руководство поможет вам установить и настроить **Agent Code Checker**, подключить его к **Agent Bridge** и выполнить первые семантические проверки качества кода для сниппетов, отдельных файлов и целых проектов.

---

## 1. Требования и установка

Библиотека требует интерпретатор **Python 3.11** или новее. В качестве зависимостей используются `codex-antigravity-a2a-bridge` (Agent Bridge) для транспорта агентов и `mcp` для запуска MCP-сервера.

> [!NOTE]
> Репозитории Agent Code Checker и Agent Bridge полностью независимы. Они могут находиться в любых каталогах вашей файловой системы.

### Создание виртуального окружения

Создайте изолированное окружение и установите оба пакета из локальных каталогов с исходным кодом:

#### В Windows (PowerShell):
```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install "path/to/agent-bridge" "path/to/agent-code-checker"
```

#### В Linux или macOS:
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install "path/to/agent-bridge" "path/to/agent-code-checker"
```

### Проверка установки

Убедитесь, что исполняемые файлы CLI и MCP-сервера доступны:

```powershell
.\.venv\Scripts\agent-code-checker.exe --help
.\.venv\Scripts\agent-code-checker-mcp.exe --help
```

---

## 2. Подключение к Agent Bridge

Agent Code Checker выполняет роль клиента-оркестратора. Для непосредственного обращения к языковым моделям он взаимодействует с сервером Agent Bridge по локальному HTTP-протоколу Agent-to-Agent (A2A).

Поддерживаются следующие агентные харнессы:
- **Codex**: модели OpenAI (`gpt-6-sol` и др.) через Codex CLI или SDK.
- **Antigravity**: модели Google (`gemini-3.8-flash-medium`, `gemini-3.8-pro-high` и др.) через Antigravity CLI.
- **OpenCode**: локальные модели (например, `qwen3.5:9b` в Ollama) или кастомные OpenAI-совместимые эндпоинты.
- **Claude Code**: модели Anthropic через Claude Code CLI.

### Запуск постоянных серверов Bridge

В отдельных терминалах можно запустить серверы Bridge с привязкой к рабочей директории:

```powershell
# Терминал 1: Харнесс Codex на порту 8765
agent-bridge serve codex --workspace . --port 8765

# Терминал 2: Харнесс Antigravity на порту 8766
agent-bridge serve antigravity --workspace . --port 8766

# Терминал 3: Харнесс OpenCode на порту 8767 (с JSON-профилем)
agent-bridge serve profile --profile path/to/opencode.profile.json --workspace . --port 8767
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
agent-code-checker evaluate snippet `
  --code "def calculate_discount(price, customer):
    if customer.is_vip:
        if customer.orders_count > 50:
            if price > 1000:
                return price * 0.3
            return price * 0.2
        return price * 0.1
    return 0" `
  --language python `
  --provider agent-bridge:codex `
  --agent-url http://127.0.0.1:8765 `
  --rules complex_conditional,deeply_nested_code
```

Анализ фрагмента выполняется в закрытом режиме (`tool_policy="no_tools"`). Модель получает текст напрямую в блоке `REQUEST_DATA_JSON`.

### Проверка отдельного файла (File)

Для отдельного файла содержимое считывается и встраивается в запрос (допустимый размер файла — до 1 МБ):

```powershell
agent-code-checker evaluate file src/checkout.py `
  --provider agent-bridge:opencode `
  --agent-url http://127.0.0.1:8767 `
  --model qwen3.5:9b `
  --rules long_method,large_class `
  --debug
```

Поскольку код передаётся непосредственно в промпте, агент не выполняет системных вызовов и не читает соседние файлы.

### Проверка проекта (Project)

В проектном режиме агент получает путь к каталогу и самостоятельно применяет инструменты чтения и поиска для анализа связей между модулями:

```powershell
agent-code-checker evaluate project path/to/project `
  --provider agent-bridge:codex `
  --rules duplicate_code,cyclic_dependency `
  --max-project-seconds 900 `
  --json --output project.evaluation.json
```

> [!TIP]
> **Автоматический запуск харнесса**: Если параметр `--agent-url` не указан, Agent Code Checker самостоятельно поднимает временный процесс Agent Bridge в целевом каталоге проекта на время проверки и корректно гасит его по завершении.

---

## 4. Настройка MCP (Model Context Protocol)

MCP-сервер позволяет запускать проверки из сред разработки и AI-ассистентов (Claude Desktop, Cursor, PyCharm).

### Пример конфигурации

Добавьте блок `agent-code-checker` в файл настроек MCP (например, `claude_desktop_config.json` или `mcp_config.json`):

```json
{
  "mcpServers": {
    "agent-code-checker": {
      "command": "path/to/.venv/Scripts/agent-code-checker-mcp.exe",
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
