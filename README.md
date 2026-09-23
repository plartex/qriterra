# Agent Code Checker

Отдельная библиотека для LLM-проверок качества кода. Agent Bridge
— транспортная зависимость: он запускает агентные харнессы через A2A,
но не хранит правила запахов, не формирует оценки и не знает о чекере.

Сейчас профиль `code_smells` содержит 80 правил. Чекер принимает сниппет или
файл, группирует правила в пакеты, проверяет структурированный ответ
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

## Отладочный прогон четырёх харнессов

[Команда `agent-code-checker-debug`](agent_code_checker/debug_harnesses.py) входит в установленный пакет. Она запрашивает модели и лимиты через `/bridge/info`, просит каждый харнесс написать стих, затем проверяет указанный файл на code smells теми же моделями. По умолчанию используются `gpt-6-sol`, доступный `gemini-3.8` и локальный Ollama `qwen3.5:9b`; модели можно поменять флагами. Ошибка одного харнесса не прерывает остальные.

Запустите Ollama и четыре сервера Agent Bridge в отдельных терминалах. Примеры профилей из исходного репозитория можно скопировать в любое место; `--workspace .` задаёт каталог вашего проекта:

```powershell
# Терминал 1, если Ollama ещё не запущена:
ollama serve

# Терминалы 2 и 3, из каталога вашего проекта:
& .\.venv\Scripts\agent-bridge.exe serve codex --workspace . --port 8765
& .\.venv\Scripts\agent-bridge.exe serve antigravity --workspace . --port 8766

# Терминал 4:
& .\.venv\Scripts\agent-bridge.exe serve profile --profile C:\path\to\opencode-ollama.json --workspace . --port 8767

# Терминал 5:
& .\.venv\Scripts\agent-bridge.exe serve profile --profile C:\path\to\claude-code-ollama.json --workspace . --port 8768
```

Если OpenCode или Claude Code не находятся через `PATH`, укажите полный путь к исполняемому файлу в `runtime_command` своего профиля.

Из каталога проекта выполните сначала быструю проверку доступности моделей, затем проверку выбранного файла:

```powershell
& .\.venv\Scripts\agent-code-checker-debug.exe --part agents
& .\.venv\Scripts\agent-code-checker-debug.exe --part smells --target .\src\service.py --rules long_method,large_class
```

Полный прогон применит все 80 правил к каждому из четырёх харнессов и может занять значительное время и квоту. Для короткой диагностики используйте `--rules long_method,large_class`; `--part agents` выполняет только запрос информации и стих, `--part smells` — только проверку. `--agents codex,opencode` ограничивает список. `--no-session` переключает проверку на независимые запросы по пакетам. Флаг `--help` показывает URL и остальные настройки.

Каждый прогон сохраняет `summary.json` и отдельные `*.code-smells.json` в новом каталоге `debug-runs/`. Трасса `debug_trace` также печатается в stderr. Для локальной Ollama Agent Bridge показывает разрешённые профилем модели, но квоты аккаунта отсутствуют; это отражено в поле `usage.available=false`.

Для встроенного каталога агенту по умолчанию передаются краткие английские
критерии из `agent_code_checker/profiles/data/code_smells.en.json`. Исходный
русский `code_smells.min.json` сохранён без изменений и используется для
человекочитаемого отчёта; английский профиль привязан к SHA-256 источника и
содержит те же 80 ID. Флаг `--prompt-language ru` возвращает прежние полные
русские описания для сравнения результатов. Для `--catalog` с внешним файлом
режим `auto` использует его исходные формулировки.

На файле `rls.py` английский профиль сократил 13 независимых промптов примерно
с 207 до 105 КБ. В сессии они заняли около 46,5 КБ: неизменный код и общая
инструкция не отправлялись повторно. В измеренном прогоне Antigravity число
некешированных входных токенов снизилось с 187 249 до 132 958, время — с
5 мин 56 с до 3 мин 03 с, но кешированных токенов стало 425 335 против 8 135:
история сессии продолжает обрабатываться. Результат зависит от модели, кеша,
ответов и длины кода; сравните точность и `--debug` usage на своём проекте.

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
`--no-session`). Режим `project` пока отклоняется до вызова модели:
оптимизированное сканирование проекта ещё не реализовано.

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
