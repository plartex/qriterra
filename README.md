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

Для встроенного каталога агенту по умолчанию передаются краткие английские
критерии из `agent_code_checker/profiles/data/code_smells.en.json`. Исходный
русский `code_smells.min.json` сохранён без изменений и используется для
человекочитаемого отчёта; английский профиль привязан к SHA-256 источника и
содержит те же 80 ID. Флаг `--prompt-language ru` возвращает прежние полные
русские описания для сравнения результатов. Для `--catalog` с внешним файлом
режим `auto` использует его исходные формулировки.

На файле `rls.py` суммарный размер 13 промптов уменьшился с 207 342 до
105 050 байт (−49,3%). Это сравнение текста промптов, не обещание такой же
экономии фактически учтённых провайдером токенов; перед внедрением в массовый
скан сравните точность и `--debug` usage на своём коде.

`--debug` немедленно печатает в stderr начало и конец каждого пакета, ожидание,
размер запроса, статусы, длительность и предоставленные провайдером токены.
Трасса также попадает в JSON-поле `debug_trace`. Токены Antigravity CLI и
Codex передаются через Bridge по каждому вызову.

Файл до 1 МБ встраивается в каждый пакет. Поэтому пакетная проверка одного
файла может тратить заметную квоту. Режим `project` пока отклоняется до вызова
модели: оптимизированное сканирование проекта ещё не реализовано.
Чекер пока использует отдельные вызовы AB для пакетов; сессии AB доступны в
его Python API, но к `evaluate` ещё не подключены.

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
