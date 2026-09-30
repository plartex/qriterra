# Справочник по Python API

[English](../api.md) | [Русский](api.md)

В этом документе представлен подробный справочник по публичному Python API библиотеки **Qriterra**.

Все основные классы, модели и вспомогательные функции импортируются напрямую из корневого пакета или подмодуля `qriterra.providers`:

```python
from qriterra import (
    EvaluationService,
    EvaluationTarget,
    EvaluationProfile,
    EvaluationReport,
    EvaluationSummary,
    CheckResult,
    Evidence,
    ProjectFinding,
    ProjectCoverage,
    RuleDefinition,
    load_code_smells_profile,
    format_text_report,
    CatalogError,
)
from qriterra.providers import (
    AgentBridgeProvider,
    agent_bridge_provider_from_name,
    FakeAgentProvider,
)
```

---

## 1. Доменные модели

### `EvaluationTarget`
Определяет цель анализа. Экземпляры являются неизменяемыми (`frozen`) и создаются через фабричные методы.

```python
@dataclass(frozen=True)
class EvaluationTarget:
    kind: Literal["snippet", "file", "project"]
    content: str | None = None
    path: Path | None = None
    language: str | None = None
```

#### Фабричные методы:
- **`EvaluationTarget.snippet(content: str, language: str | None = None) -> EvaluationTarget`**:
  Создаёт строковую цель в оперативной памяти. Аргумент `content` обязан быть непустой строкой.
- **`EvaluationTarget.file(path: str | Path) -> EvaluationTarget`**:
  Создаёт цель для отдельного файла на диске. Путь немедленно нормализуется в абсолютный и проверяется на существование. Содержимое встраивается в промпт при размере до 1 000 000 байт.
- **`EvaluationTarget.project(path: str | Path) -> EvaluationTarget`**:
  Создаёт цель для каталога проекта. При создании рекурсивно проверяется, что ни одна символическая ссылка не выходит за границы каталога проекта.

#### Свойства:
- `workspace: Path | None`: возвращает `path.parent` для файла, `path` для проекта и `None` для сниппета.

---

### `RuleDefinition`
Представляет отдельное правило проверки, загруженное из каталога.

```python
@dataclass(frozen=True)
class RuleDefinition:
    id: str
    title: str
    title_en: str
    severity: Literal["low", "medium", "high", "critical"]
    scope: str
    category_id: str
    summary: str
    definition: str
    symptoms: tuple[str, ...]
    detection_hints: dict[str, str]
    tags: tuple[str, ...] = ()
    executor: str = "llm"
    criterion_en: str | None = None
    full_english: bool = False
```

- `prompt_dict() -> dict[str, Any]`: подготавливает словарь правила для отправки агенту в промпте. Сохраняет числовые пороги метрик и исключает длинные примеры кода ради экономии токенов.

---

### `Evidence`
Конкретная цитата и локация в коде, доказывающая наличие запаха.

```python
@dataclass(frozen=True)
class Evidence:
    path: str | None
    start_line: int
    end_line: int
    excerpt: str
    reason: str
```
- `path`: `None` для сниппета; относительный POSIX-путь внутри проекта для проекта; полный путь файла для одиночного файла.
- `excerpt`: точный фрагмент исходного кода. Для проекта валидатор строго проверяет наличие цитаты `excerpt` на строках `start_line`–`end_line`.

---

### `ProjectFinding` и `ProjectCoverage`
Используются при проверке проектов (схема 2.0).

```python
@dataclass(frozen=True)
class ProjectFinding:
    summary: str
    evidence: tuple[Evidence, ...]

@dataclass(frozen=True)
class ProjectCoverage:
    status: Literal["complete", "partial"]
    inspected_paths: tuple[str, ...]
    limitations: tuple[str, ...]
```
- `ProjectFinding`: объединяет несколько связанных локаций в одну находку (например, две половины дублирующегося кода в разных файлах).
- `ProjectCoverage`: декларируемый агентом охват проверки. Для статуса `complete` обязательны непустой список `inspected_paths` и пустой список `limitations`.

---

### `CheckResult`
Итог проверки одного конкретного правила.

```python
@dataclass(frozen=True)
class CheckResult:
    rule_id: str
    status: Literal["passed", "failed", "skipped", "inconclusive", "error"]
    severity: Literal["low", "medium", "high", "critical"]
    confidence: float | None = None
    evidence: tuple[Evidence, ...] = ()
    reason: str | None = None
    findings: tuple[ProjectFinding, ...] = ()
    coverage: ProjectCoverage | None = None
```

---

### `EvaluationSummary` и `EvaluationReport`

```python
@dataclass(frozen=True)
class EvaluationSummary:
    total: int
    passed: int
    failed: int
    skipped: int
    inconclusive: int
    errors: int
    findings: int
    quality_score: float | None
    assessment_coverage: float

@dataclass(frozen=True)
class EvaluationReport:
    run_id: str
    profile: EvaluationProfile
    target: EvaluationTarget
    provider: ProviderDescriptor
    summary: EvaluationSummary
    results: tuple[CheckResult, ...]
    warnings: tuple[str, ...]
    debug_trace: tuple[dict[str, Any], ...]
    schema_version: str = "1.0"
```
- `to_dict() -> dict[str, Any]`: сериализует отчёт в словарь (`schema_version` автоматически выставляется в `"2.0"` для проектов и `"1.0"` для сниппетов и файлов).
- `to_json(*, indent: int | None = 2) -> str`: возвращает отформатированную строку JSON.

---

## 2. Сервисы и функции загрузки

### `EvaluationService`
Основной оркестратор процесса проверки.

```python
class EvaluationService:
    def __init__(self, provider: AgentProvider): ...

    async def evaluate(
        self,
        target: EvaluationTarget,
        profile: EvaluationProfile,
        *,
        model: str | None = None,
        reasoning_effort: str | None = None,
        batch_size: int = 10,
        max_project_seconds: float = 1800,
        use_session: bool = True,
        debug: bool = False,
        on_debug_event: Callable[[dict[str, Any]], None] | None = None,
    ) -> EvaluationReport: ...
```

#### Параметры:
- `target`: анализируемый объект `EvaluationTarget`.
- `profile`: профиль проверок `EvaluationProfile`, полученный из `load_code_smells_profile`.
- `model`: идентификатор модели для харнесса (например, `"gpt-6-sol"`).
- `reasoning_effort`: глубина рассуждений модели (`"low"`, `"medium"`, `"high"`).
- `batch_size`: максимальное число правил в одном пакете (по умолчанию: `10`).
- `max_project_seconds`: общий лимит времени в секундах для проектной проверки (по умолчанию: `1800.0`).
- `use_session`: при `True` (по умолчанию) использует одну непрерывную сессию Agent Shuttle для всех пакетов.
- `debug`: при `True` собирает события жизненного цикла и метрики токенов в `report.debug_trace`.
- `on_debug_event`: опциональная функция обратного вызова для потоковой обработки событий в реальном времени.

---

### `load_code_smells_profile`

Загружает и валидирует базу правил.

```python
def load_code_smells_profile(
    catalog_path: str | Path | None = None,
    rule_ids: list[str] | tuple[str, ...] | None = None,
    *,
    prompt_language: str = "auto",
) -> EvaluationProfile: ...
```

- `catalog_path`: путь к пользовательскому JSON-файлу базы правил (по умолчанию используется встроенный `code_smells.min.json`).
- `rule_ids`: список идентификаторов для выборочной проверки (например, `["long_method"]`).
- `prompt_language`: `"auto"`, `"en"` или `"ru"`.
  - `"auto"`: английский язык для встроенной базы, русский — для внешних каталогов.
  - `"en"`: полный английский зеркальный перевод (доступен только для встроенной базы).
  - `"ru"`: оригинальные русские формулировки.

Вызывает исключение `CatalogError`, если файл повреждён, не содержит обязательных полей или если хеш английского перевода не совпадает с исходной базой.

---

### `format_text_report`

```python
def format_text_report(report: EvaluationReport) -> str: ...
```
Преобразует объект `EvaluationReport` в читаемый текстовый отчёт, похожий на вывод тест-раннера.

---

## 3. Провайдеры (Providers)

### `AgentBridgeProvider`

Реализует транспорт поверх сервера Agent Shuttle.

```python
class AgentBridgeProvider:
    def __init__(
        self,
        peer_url: str,
        agent: str,
        timeout_seconds: float = 1800,
        *,
        tool_policy: str | None = None,
    ): ...
```
- `peer_url`: базовый URL сервера Agent Shuttle (например, `"http://127.0.0.1:8765"`).
- `agent`: идентификатор харнесса (`"codex"`, `"antigravity"`, `"opencode"`).
- `tool_policy`: политика инструментов (`"no_tools"`, `"read_only"`, `"workspace_write"`, `"full_access"`).

### `agent_bridge_provider_from_name`

Функция разрешения провайдера по стандартным алиасам и переменным окружения:

```python
def agent_bridge_provider_from_name(
    name: str,
    *,
    peer_url: str | None = None,
    tool_policy: str | None = None,
) -> AgentBridgeProvider: ...
```

Поддерживает имена: `codex`, `antigravity`, `opencode`, `claude_code` или с префиксом `agent-shuttle:codex`. Старый префикс `agent-bridge:` также работает. При отсутствии `peer_url` считывает переменные окружения (`BRIDGE_CODEX_URL`, `BRIDGE_ANTIGRAVITY_URL` и т.д.).

### `FakeAgentProvider`

Mock-провайдер для быстрого и бесплатного оффлайн-тестирования:

```python
class FakeAgentProvider:
    def __init__(
        self,
        handler: Callable[[str, Path | None, str | None], str | ProviderResponse],
        capabilities: ProviderCapabilities | None = None,
    ): ...
```

---

## 4. Пример программного использования

```python
import asyncio
from pathlib import Path
from qriterra import (
    EvaluationService,
    EvaluationTarget,
    format_text_report,
    load_code_smells_profile,
)
from qriterra.providers import AgentBridgeProvider

async def run_check():
    # 1. Подключение к харнессу Codex
    provider = AgentBridgeProvider(
        peer_url="http://127.0.0.1:8765",
        agent="codex",
        tool_policy="read_only",
    )

    # 2. Выбор двух правил на английском языке
    profile = load_code_smells_profile(
        rule_ids=["long_method", "duplicate_code"],
        prompt_language="en",
    )

    # 3. Указание целевого файла
    target = EvaluationTarget.file(Path("src/service.py"))

    # 4. Запуск проверки с отладочной трассировкой
    service = EvaluationService(provider)
    report = await service.evaluate(
        target,
        profile,
        model="gpt-6-sol",
        reasoning_effort="medium",
        debug=True,
    )

    # 5. Вывод отчёта
    print(format_text_report(report))
    if report.summary.errors > 0:
        print("Проверка завершилась с техническими ошибками!")

if __name__ == "__main__":
    asyncio.run(run_check())
```
