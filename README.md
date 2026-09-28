# Agent Code Checker

Отдельная библиотека для LLM-проверок качества кода. Agent Bridge
— транспортная зависимость: он запускает агентные харнессы через A2A,
но не хранит правила запахов, не формирует оценки и не знает о чекере.

Сейчас профиль `code_smells` содержит 80 правил. Чекер принимает сниппет, файл
или проект, группирует правила в пакеты, проверяет структурированный ответ
агента, собирает доказательства и рассчитывает оценку. Он только выявляет
проблемы и не изменяет код.

## Установка в любом проекте

Создайте окружение в своём проекте и установите обе библиотеки в него. Их исходные репозитории могут находиться где угодно; при запуске после установки они не нужны:

```powershell
python -m venv .venv
$bridgeSource = 'C:\path\to\agent-bridge'
$checkerSource = 'C:\path\to\agent-code-checker'
& .\.venv\Scripts\python.exe -m pip install $bridgeSource $checkerSource
```

В PyCharm выберите тот же `ваш-проект\.venv\Scripts\python.exe` как Project Interpreter. Если будете устанавливать опубликованные пакеты из индекса, достаточно `pip install agent-code-checker`: пакет объявляет Agent Bridge обычной зависимостью.

Серверы запускаются из окружения проекта и получают его каталог через `--workspace`:

```powershell
& .\.venv\Scripts\agent-bridge.exe serve codex --workspace . --port 8765
# В другом терминале:
& .\.venv\Scripts\agent-bridge.exe serve antigravity --workspace . --port 8766
```

Для OpenCode и Claude Code создайте JSON-профили по примерам в Agent Bridge и запустите `serve profile --profile <путь> --workspace . --port <порт>`. Рабочая папка берётся из `--workspace`; профиль не обязан находиться в проекте.

## CLI

```powershell
& .\.venv\Scripts\agent-code-checker.exe evaluate file .\src\service.py `
  --provider agent-bridge:opencode-local --agent-url http://127.0.0.1:8767 `
  --tool-policy no_tools --model qwen3.5:9b --rules long_method,large_class `
  --debug --json --output service.report.json
```

Для Codex используйте `--provider agent-bridge:codex --agent-url http://127.0.0.1:8765 --model gpt-6-sol`. Для Antigravity передайте его URL и доступный model ID. Старые переменные `BRIDGE_CODEX_URL` и `BRIDGE_ANTIGRAVITY_URL` также поддерживаются. MCP-инструмент `evaluate` принимает те же `provider`, `agent_url` и `tool_policy`.
Сниппет передаётся как `evaluate snippet --code '...' --language python`.
Отдельные правила выбираются флагом `--rules long_method,duplicate_code`.

Для агентной проверки всего проекта Bridge запускается временно в каталоге
цели, если `--agent-url` не указан:

```powershell
& .\.venv\Scripts\agent-code-checker.exe evaluate project 'D:\path\to\repo' `
  --provider agent-bridge:codex --model gpt-6-sol `
  --rules duplicate_code,cyclic_dependency --max-project-seconds 900 `
  --debug --json --output project.code-quality.json
```

Та же проверка через временный Antigravity Bridge:

```powershell
& .\.venv\Scripts\agent-code-checker.exe evaluate project 'D:\path\to\repo' `
  --provider agent-bridge:antigravity --tool-policy full_access `
  --rules duplicate_code,cyclic_dependency --max-project-seconds 900 `
  --debug --json --output project.antigravity.code-quality.json
```

Проектный режим открывает одну сессию даже для одного пакета правил.
Агент сам читает и ищет файлы, решает семантические вопросы; чекер не запускает
AST/CPD-детектор. Существующий Bridge можно указать через `--agent-url`, но он
должен сообщить точно тот же workspace.
Для временного OpenCode/Claude Code укажите `--provider agent-bridge:opencode`
или `agent-bridge:claude_code`, модель и, если требуется, `--harness-profile`.
По умолчанию Codex, OpenCode и Claude Code получают `read_only`; Antigravity
автоматически запускается с `full_access`, поскольку его CLI не гарантирует
`read_only` в headless-режиме. Для всех харнессов можно явно передать
`--tool-policy full_access` или `workspace_write` (кроме Antigravity, которому
для проектного режима нужен `full_access`). Для OpenCode/Claude Code пользовательский
профиль должен разрешать выбранный уровень через `max_tool_policy`. Чекер
по-прежнему только выявляет проблемы и просит агента не менять файлы, однако
при `full_access` это требование в промпте, а не техническая гарантия.
Контрольный live-прогон Antigravity на двух файлах и одном правиле
`duplicate_code` завершился за 173,5 секунды и сообщил 205 154 токена суммарно;
стоимость полного проекта может быть значительно выше. Для первых запусков
ограничьте `--rules` и `--max-project-seconds`, изучите `--debug` и охват.

## Отладочный скрипт — композиция двух библиотек

[Скрипт для PyCharm](examples/debug_harnesses.py) запускается кнопкой Run без параметров. Все прикладные вызовы теперь находятся в нём: `discover_harnesses()` находит харнессы, `connect_harness()` временно поднимает Bridge при необходимости, `BridgeClient.info()` читает модели и лимиты, `BridgeClient.ask()` просит стих, а `EvaluationService.evaluate()` проверяет code smells через `AgentBridgeProvider`. В библиотеках нет кода, который выбирает стих, файл `rls.py` или порядок этих шагов.

Выберите интерпретатор `agent-code-checker/.venv/Scripts/python.exe`. В начале скрипта доступны `TARGET`, `AGENTS`, `RULES`, `MODELS`, `COMMANDS`, `URLS`, `PROFILES`. Текущее `RULES = None` — сохранённый выбор для всех 80 правил; такой прогон может потратить значительную квоту. Для короткой проверки поставьте `RULES = "long_method,large_class"`. Отчёты и логи находятся в `examples/debug-runs/`.

Из PowerShell можно запустить тот же скрипт с переопределениями:

```powershell
& .\.venv\Scripts\python.exe .\examples\debug_harnesses.py --part agents
& .\.venv\Scripts\python.exe .\examples\debug_harnesses.py --part smells --target .\src\service.py --rules long_method,large_class
```

`--agents auto` выбирает найденные харнессы; `--agents codex,opencode` ограничивает список. Для локальных OpenCode и Claude Code создаётся временный профиль Ollama с `qwen3.5:9b`; Ollama и модель должны быть доступны. Команду можно указать через `COMMANDS` или `--agy-command`/`--opencode-command`/`--claude-command`; уже работающий сервер — через `URLS` или соответствующий `--*-url`. Явно заданный URL не запускается автоматически. Для другого поставщика модели передайте JSON-профиль через `PROFILES` или `--opencode-profile`/`--claude-profile` и нужный ID модели. `--no-auto-start` запрещает временные серверы; `--no-session` делает отдельный запрос на каждый пакет правил.

Отдельной команды `agent-code-checker-debug` больше нет: это прикладной сценарий, а не функция библиотеки. Каждый прогон сохраняет `summary.json` и отдельные `*.code-smells.json`; трасса также печатается в stderr. Локальная Ollama не предоставляет квоты аккаунта через этот профиль (`usage.available=false`).

Для встроенного каталога по умолчанию используется полный английский перевод
`agent_code_checker/profiles/data/code_smells.en.json`. Он сохраняет все поля,
порядок правил, метрики и примеры русского `code_smells.min.json`; программный
код примеров оставлен дословно, чтобы перевод не менял их поведение. SHA-256
русского источника хранится рядом в `code_smells.en.sha256`, и загрузчик
отклоняет устаревший или структурно неполный перевод. Агенту передаются
английские определение, симптомы и метрики обнаружения, без потери численных
порогов. Причины, последствия, техники рефакторинга и примеры сохранены в
зеркальном каталоге, но не включаются в каждый промпт ради ограничения токенов.
`--prompt-language ru` использует исходные русские формулировки; внешний
`--catalog` в режиме `auto` использует собственный язык.

Прежние измерения расхода токенов для краткого английского профиля больше не
характеризуют полный перевод: промпты станут длиннее. Сравнивайте точность и
`--debug` usage на своей модели и проекте.

`--debug` немедленно печатает в stderr начало и конец каждого пакета, ожидание,
размер запроса, статусы, длительность и предоставленные провайдером токены.
Трасса также попадает в JSON-поле `debug_trace`. Токены Antigravity CLI и
Codex передаются через Bridge по каждому вызову.

При нескольких пакетах чекер по умолчанию открывает одну изолированную сессию
Agent Bridge на проверку и закрывает её в конце. Код и общие ограничения
передаются в первом запросе; следующие запросы содержат только новые правила.
В `--debug` видны `session_opened`/`session_closed` и usage каждого хода.
`--no-session` возвращает независимые запросы с полным кодом в каждом пакете
для сравнения или обхода проблем сессии; в Python это `use_session=False`,
в MCP — `use_session=false`. Модель и reasoning effort закреплены за сессией.
Кеширование у провайдера не гарантировано; длинная история разговора также
может увеличить входной контекст, поэтому оценивайте реальное usage.

Файл до 1 МБ встраивается в первый пакет сессии (или в каждый пакет при
`--no-session`). Проектная проверка вместо встраивания кода разрешает агенту
инструменты чтения и поиска в отдельной сессии. `--no-session` для проекта
запрещён. Проектный отчёт использует схему 2.0: одна находка может содержать
несколько связанных локаций. Охват декларируется агентом и не является
независимым доказательством полного обхода; при частичном охвате оценка
качества не рассчитывается. Лимит времени задаётся `--max-project-seconds`.

## Python и MCP

```python
from agent_code_checker import EvaluationService, EvaluationTarget, load_code_smells_profile
from agent_code_checker.providers import AgentBridgeProvider

provider = AgentBridgeProvider('http://127.0.0.1:8767', 'opencode-local', tool_policy='no_tools')
report = await EvaluationService(provider).evaluate(
    EvaluationTarget.file('src/service.py'),
    load_code_smells_profile(),
    debug=True,
)
print(report.to_json())
```

MCP-сервер чекера запускается из установленного окружения командой
`agent-code-checker-mcp`. Его инструмент `evaluate` не входит в MCP-сервер
Agent Bridge. Укажите путь к этой команде в конфигурации MCP своего проекта;
`Configure-Mcp.ps1` в исходном репозитории — лишь удобный скрипт настройки.

## Тесты

```powershell
& .\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Тесты используют fake-провайдер и не расходуют модельную квоту. Архитектурное
описание находится в [docs/evaluation-framework-design.md](docs/evaluation-framework-design.md).
