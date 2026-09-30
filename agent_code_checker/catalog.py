"""Load evaluation profiles from knowledge-base JSON files."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import replace
from pathlib import Path
from typing import cast

from .models import EvaluationProfile, RuleDefinition, Severity, VALID_SEVERITIES


DEFAULT_CODE_SMELLS_CATALOG = Path(__file__).parent / "profiles" / "data" / "code_smells.min.json"
DEFAULT_ENGLISH_PROFILE = Path(__file__).parent / "profiles" / "data" / "code_smells.en.json"
DEFAULT_ENGLISH_SOURCE_HASH = Path(__file__).parent / "profiles" / "data" / "code_smells.en.sha256"
_CYRILLIC = re.compile(r"[\u0400-\u04ff]")


class CatalogError(ValueError):
    pass


def load_code_smells_profile(
    catalog_path: str | Path | None = None,
    rule_ids: list[str] | tuple[str, ...] | None = None,
    *,
    prompt_language: str = "auto",
) -> EvaluationProfile:
    if prompt_language not in {"auto", "en", "ru"}:
        raise CatalogError("prompt_language must be auto, en, or ru")
    path = Path(catalog_path) if catalog_path is not None else DEFAULT_CODE_SMELLS_CATALOG
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise CatalogError(f"Cannot read code smells catalog {path}: {exc}") from exc
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CatalogError(f"Invalid JSON catalog {path}: {exc}") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("smells"), list):
        raise CatalogError("Catalog must be an object with a smells array")
    meta = payload.get("meta")
    if not isinstance(meta, dict):
        raise CatalogError("Catalog meta must be an object")

    rules: list[RuleDefinition] = []
    seen: set[str] = set()
    for index, source in enumerate(payload["smells"]):
        if not isinstance(source, dict):
            raise CatalogError(f"smells[{index}] must be an object")
        rule_id = _required_text(source, "id", index)
        if rule_id in seen:
            raise CatalogError(f"Duplicate rule id: {rule_id}")
        seen.add(rule_id)
        severity = _required_text(source, "severity", index)
        if severity not in VALID_SEVERITIES:
            raise CatalogError(f"Rule {rule_id} has invalid severity: {severity}")
        symptoms = source.get("symptoms")
        hints = source.get("detection_metrics")
        if not isinstance(symptoms, list) or not all(isinstance(item, str) and item.strip() for item in symptoms):
            raise CatalogError(f"Rule {rule_id} must have nonempty string symptoms")
        if not isinstance(hints, dict) or not all(
            isinstance(key, str) and isinstance(value, str) for key, value in hints.items()
        ):
            raise CatalogError(f"Rule {rule_id} detection_metrics must be a string map")
        tags = source.get("tags", [])
        if not isinstance(tags, list) or not all(isinstance(item, str) for item in tags):
            raise CatalogError(f"Rule {rule_id} tags must be strings")
        rules.append(
            RuleDefinition(
                id=rule_id,
                title=_required_text(source, "name", index),
                title_en=_required_text(source, "name_en", index),
                severity=cast(Severity, severity),
                scope=_required_text(source, "level", index),
                category_id=_required_text(source, "category_id", index),
                summary=_required_text(source, "summary", index),
                definition=_required_text(source, "definition", index),
                symptoms=tuple(item.strip() for item in symptoms),
                detection_hints={key: value for key, value in hints.items()},
                tags=tuple(tags),
            )
        )

    declared_total = meta.get("total_smells")
    if declared_total != len(rules):
        raise CatalogError(f"Catalog declares {declared_total} smells but contains {len(rules)}")

    bundled = path.resolve() == DEFAULT_CODE_SMELLS_CATALOG.resolve()
    language = "en" if prompt_language == "en" or (prompt_language == "auto" and bundled) else "ru"
    if language == "en":
        if not bundled:
            raise CatalogError("English prompt profile is only available for the bundled catalog")
        english = _load_english_profile(hashlib.sha256(raw).hexdigest(), payload, rules)
        rules = [
            replace(
                rule,
                summary=english[rule.id]["summary"],
                definition=english[rule.id]["definition"],
                symptoms=tuple(english[rule.id]["symptoms"]),
                detection_hints=dict(english[rule.id]["detection_metrics"]),
                criterion_en=english[rule.id]["definition"],
                full_english=True,
            )
            for rule in rules
        ]

    if rule_ids is not None:
        requested = list(dict.fromkeys(rule_ids))
        unknown = [rule_id for rule_id in requested if rule_id not in seen]
        if unknown:
            raise CatalogError(f"Unknown rule ids: {', '.join(unknown)}")
        requested_set = set(requested)
        rules = [rule for rule in rules if rule.id in requested_set]

    version = meta.get("version")
    title = meta.get("title")
    if not isinstance(version, str) or not version.strip():
        raise CatalogError("Catalog meta.version must be a nonempty string")
    if not isinstance(title, str) or not title.strip():
        raise CatalogError("Catalog meta.title must be a nonempty string")
    return EvaluationProfile(
        id="code_smells",
        title="Code Smells",
        version=version.strip(),
        catalog_sha256=hashlib.sha256(raw).hexdigest(),
        rules=tuple(rules),
        prompt_language=language,
    )


def _load_english_profile(
    source_sha256: str, source: dict, rules: list[RuleDefinition],
) -> dict[str, dict]:
    try:
        payload = json.loads(DEFAULT_ENGLISH_PROFILE.read_text(encoding="utf-8"))
        recorded_sha256 = DEFAULT_ENGLISH_SOURCE_HASH.read_text(encoding="ascii").strip()
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CatalogError(f"Cannot load English prompt profile: {exc}") from exc
    if recorded_sha256 != source_sha256:
        raise CatalogError("English prompt profile is stale; regenerate it from the current catalog")
    _validate_translation_shape(source, payload)
    items = payload["smells"]
    if [item.get("id") for item in items if isinstance(item, dict)] != [rule.id for rule in rules]:
        raise CatalogError("English prompt profile rule IDs or order do not match the catalog")
    return {item["id"]: item for item in items}


def _validate_translation_shape(source, translated, path: str = "") -> None:
    """Ensure the English mirror loses no field and never changes code or IDs."""
    if isinstance(source, dict):
        if not isinstance(translated, dict) or source.keys() != translated.keys():
            raise CatalogError(f"English catalog fields differ at {path or '/'}")
        for key, value in source.items():
            _validate_translation_shape(value, translated[key], f"{path}/{key}")
    elif isinstance(source, list):
        if not isinstance(translated, list) or len(source) != len(translated):
            raise CatalogError(f"English catalog array differs at {path}")
        for index, value in enumerate(source):
            _validate_translation_shape(value, translated[index], f"{path}/{index}")
    elif isinstance(source, str):
        if not isinstance(translated, str) or not translated.strip():
            raise CatalogError(f"English catalog has empty text at {path}")
        if path.endswith("/code") or not _CYRILLIC.search(source):
            if translated != source:
                raise CatalogError(f"English catalog changed non-translatable content at {path}")
        elif _CYRILLIC.search(translated) or "\ufffd" in translated:
            raise CatalogError(f"English catalog contains untranslated text at {path}")
    elif translated != source or type(translated) is not type(source):
        raise CatalogError(f"English catalog changed metadata at {path}")


def _required_text(source: dict, key: str, index: int) -> str:
    value = source.get(key)
    if not isinstance(value, str) or not value.strip():
        raise CatalogError(f"smells[{index}].{key} must be a nonempty string")
    return value.strip()
