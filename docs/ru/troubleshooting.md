# Диагностика и устранение неполадок

[English](../troubleshooting.md) | [Русский](troubleshooting.md)

В этом руководстве описаны инструменты отладки в реальном времени, структура событий трассировки, а также типичные ошибки и способы их устранения.

---

## 1. Отладка в реальном времени с флагом `--debug`

При запуске через CLI или Python API флаг `--debug` (или аргумент `debug=True`) включает потоковый вывод JSON-событий в `stderr` и сохраняет полную историю в поле `report.debug_trace`:

```powershell
qriterra evaluate file src/service.py --provider agent-shuttle:codex --debug
```

### События жизненного цикла

| Название события | Описание |
|---|---|
| `run_started` | Параметры запуска, общее число правил, план пакетов и лимиты времени. |
| `session_opened` | Открытие сессии A2A на сервере Agent Shuttle (`session_id`). |
| `batch_started` | Начало обработки пакета правил (`batch_id`, `scope`, `rule_ids`). |
| `agent_request` | Отправка промпта агенту (номер попытки `attempt`, размер `prompt_bytes`). |
| `agent_waiting` | Периодическое уведомление (каждые 10 секунд) в процессе генерации ответа моделью. |
| `agent_response` | Получение ответа от агента (размер `response_bytes`, расход токенов `usage`). |
| `validated` | Успешная валидация структурированного JSON-ответа. |
| `validation_failed` | Нарушение схемы ответа; инициирует разовый запрос на исправление (repair). |
| `batch_finished` | Завершение обработки пакета (`duration_seconds`, распределение статусов). |
| `batch_budget_exhausted` | Превышение лимита времени проверки; правила пакета получают `inconclusive`. |
| `session_closed` | Закрытие сессии диалога в Agent Shuttle. |
| `run_finished` | Итоги выполнения (суммарный расход токенов `usage_totals`, длительность). |

---

## 2. Типичные ошибки и их решение

### 1. `Bridge workspace ... does not match project ...`
- **Причина**: Сервер Agent Shuttle был запущен в каталоге, отличном от целевого проекта.
- **Решение**: Запустите Agent Shuttle с параметром `--workspace <путь-к-проекту>` либо опустите флаг `--agent-url`, чтобы CLI автоматически поднял временный сервер в нужной папке.

### 2. `Antigravity project evaluation requires full_access`
- **Причина**: Попытка проверки проекта через Google Antigravity без флага `full_access`.
- **Решение**: Antigravity CLI не поддерживает песочницу `read_only` при headless-запуске. Укажите `--tool-policy full_access`:
  ```powershell
  qriterra evaluate project path/to/project `
    --provider agent-shuttle:antigravity --tool-policy full_access
  ```

### 3. `Project evaluation requires agent tools; no_tools cannot inspect the project`
- **Причина**: Для проверки проекта была задана политика `no_tools`.
- **Решение**: Проектный режим требует инструментов чтения и поиска файлов. Используйте `read_only` (по умолчанию для Codex, OpenCode, Claude Code) или `full_access` (для Antigravity).

### 4. `Project evaluation requires one persistent agent session`
- **Причина**: Флаг `--no-session` был передан для цели `project`.
- **Решение**: Для анализа связей между модулями требуется непрерывная сессия диалога, сохраняющая контекст проекта между пакетами. Уберите флаг `--no-session`.

### 5. `file target is ... bytes; the inline limit is 1000000 bytes`
- **Причина**: Размер файла превышает 1 МБ. Проверка одиночного файла встраивает его код напрямую в промпт.
- **Решение**: Разбейте файл на части, проверьте отдельные функции через `evaluate snippet` или запустите проектную проверку каталога.

### 6. `project contains a symlink outside its boundary: ...`
- **Причина**: Внутри каталога проекта обнаружена символическая ссылка, ведущая за пределы репозитория.
- **Решение**: Удалите внешнюю ссылку или укажите в качестве цели родительский каталог, охватывающий оба пути.

### 7. `Rule ... cannot pass with partial coverage`
- **Причина**: Модель вернула статус `passed`, одновременно указав частичный охват (`coverage.status: "partial"`).
- **Объяснение**: Чекер запрещает утверждать об отсутствии дефекта, если проект был исследован лишь частично. Валидатор отправляет запрос на исправление; при повторном нарушении правило получает статус `error`.

### 8. `Rule ... evidence excerpt does not match source lines`
- **Причина**: Модель сгенерировала цитату `excerpt`, которой нет на строках `start_line`–`end_line` в указанном файле.
- **Объяснение**: Валидатор физически проверяет строки файла на диске. Ошибка отправляется модели на автоматическое исправление.

### 9. `English prompt profile is stale; regenerate it from the current catalog`
- **Причина**: Файл `code_smells.min.json` был изменён, но файлы `code_smells.en.json` и `code_smells.en.sha256` не обновлены.
- **Решение**: Запустите генератор перевода:
  ```powershell
  python scripts/translate_catalog.py
  ```

---

## 3. Почему оценка качества равна `N/A` (`null`)?

Показатель `quality_score` отражает степень уверенности в качестве кода. Он намеренно отключается (`null`), если запуск был неполным или завершился с техническими сбоями:
1. **Любая ошибка**: если `report.summary.errors > 0`, оценка равна `null`.
2. **Неполный охват в проекте**: если хотя бы одно правило получило `coverage.status: "partial"`, оценка равна `null`.
3. **Неопределённые проверки**: для расчёта оценки все правила проекта должны получить подтверждённый статус `passed` или `failed` с полным охватом.
4. **Отсутствие оценённых правил**: если все правила были пропущены (`skipped`), оценка равна `null`.

В таких случаях ориентируйтесь на метрику `assessment_coverage` и изучите секцию **Unresolved checks** в отчёте.

---

## 4. Сбор и отображение расхода токенов

В отчёте `report.debug_trace` и консольном выводе:
- **Codex и Antigravity**: возвращают точный расход токенов (input, output, cache read) через Agent Shuttle, который суммируется в блоке `usage_totals`.
- **Локальная Ollama (OpenCode)**: профили Ollama не возвращают данные о квотах (`usage.available=false`), поэтому значения токенов в отладке будут равны `null`.
