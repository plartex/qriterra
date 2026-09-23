# Agent Code Checker

Отдельная библиотека для LLM-проверок качества кода. [Agent Bridge](https://gitlab.com/kkaastr/codex-antigravity-a2a-bridge)
— только транспортная зависимость: он запускает Codex или Antigravity через A2A,
но не хранит правила запахов, не формирует оценки и не знает о чекере.

Сейчас профиль `code_smells` содержит 80 правил. Чекер принимает сниппет или
файл, группирует правила в пакеты, проверяет структурированный ответ
агента, собирает доказательства и рассчитывает оценку. Он только выявляет
проблемы и не изменяет код.

## Установка рядом с Agent Bridge

Сначала запустите серверы из соседнего репозитория `agent-bridge`:

```powershell
Set-Location ..\agent-bridge
& .\Start-Bridge.ps1
Set-Location ..\agent-code-checker
```

Поставьте обе библиотеки в одно окружение (первая команда нужна один раз):

```powershell
& ..\agent-bridge\.venv\Scripts\python.exe -m venv .venv
& .\.venv\Scripts\python.exe -m pip install -e ..\agent-bridge -e .
```

`pyproject.toml` чекера объявляет `codex-antigravity-a2a-bridge` обычной
Python-зависимостью. Локальная editable-установка выше нужна до публикации
отдельных пакетов в индекс.

## CLI

```powershell
$env:BRIDGE_ANTIGRAVITY_URL = 'http://127.0.0.1:8766'
& .\.venv\Scripts\python.exe -m agent_code_checker.cli evaluate file `
  'C:/path/to/project' `
  --provider agent-bridge:antigravity --model gemini-3.8-flash-medium `
  --reasoning-effort medium --batch-size 10 --debug --json --output rls.report.json
```

Для Codex задайте `BRIDGE_CODEX_URL=http://127.0.0.1:8765` и используйте
`--provider agent-bridge:codex --model gpt-5.6-terra --reasoning-effort high`.
Сниппет передаётся как `evaluate snippet --code '...' --language python`.
Отдельные правила выбираются флагом `--rules long_method,duplicate_code`.

## Отладочный прогон четырёх харнессов

[Скрипт](examples/debug_harnesses.py) выполняет две части: запрашивает модели и лимиты через `/bridge/info` и просит каждый харнесс написать стих; затем проверяет один файл на code smells теми же моделями. Codex использует `gpt-6-sol`, Antigravity — доступный `gemini-3.8` (по умолчанию `gemini-3.8-flash-medium`), OpenCode и Claude Code — локальный Ollama `qwen3.5:9b`. Скрипт печатает ошибки каждого харнесса отдельно и продолжает прогон остальных.

Сначала запустите Ollama и четыре сервера Agent Bridge. Команды выполняются в отдельных PowerShell-терминалах. Если Ollama уже работает, повторно запускать её не нужно:

```powershell
# Терминал 1:
& "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe" serve

# Терминал 2, из каталога agent-bridge:
& .\Start-Bridge.ps1

# Терминал 3, из каталога agent-bridge:
$env:PATH = "$env:APPDATA\npm;$env:PATH"
& .\.venv\Scripts\agent-bridge.exe serve profile --profile .\examples\opencode-ollama.json --port 8767

# Терминал 4, из каталога agent-bridge:
& .\.venv\Scripts\agent-bridge.exe serve profile --profile .\examples\claude-code-ollama.json --port 8768
```

Если OpenCode или Claude Code не находятся через `PATH`, укажите полный путь к исполняемому файлу в поле `runtime_command` соответствующего JSON-профиля. На текущей Windows-машине OpenCode установлен как `C:/path/to/project`.

Из каталога `agent-code-checker` запустите полный прогон. По умолчанию файл — прежний `C:/path/to/project`; укажите `--target` для другого файла:

```powershell
& .\.venv\Scripts\python.exe .\examples\debug_harnesses.py --target 'C:/path/to/project'
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

provider = AgentBridgeProvider('http://127.0.0.1:8766', 'antigravity')
report = await EvaluationService(provider).evaluate(
    EvaluationTarget.file('D:/projects/example/service.py'),
    load_code_smells_profile(),
    debug=True,
)
print(report.to_json())
```

MCP-сервер чекера запускается отдельно: `python -m agent_code_checker.mcp_server`.
Его инструмент `evaluate` не входит в MCP-сервер Agent Bridge.
После установки обеих библиотек запустите `& .\Configure-Mcp.ps1`, чтобы
зарегистрировать только MCP-сервер чекера в этом workspace.

## Тесты

```powershell
& .\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Тесты используют fake-провайдер и не расходуют модельную квоту. Архитектурное
описание находится в [docs/evaluation-framework-design.md](docs/evaluation-framework-design.md).
