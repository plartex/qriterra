"""Native output constraints; evidence is still checked against source files."""

def project_output_schema(rule_ids=None, batch_id=None):
    text = {"type": "string", "minLength": 1}
    evidence = {
        "type": "object", "additionalProperties": False,
        "required": ["path", "start_line", "end_line", "excerpt", "reason"],
        "properties": {
            "path": text, "start_line": {"type": "integer", "minimum": 1},
            "end_line": {"type": "integer", "minimum": 1}, "excerpt": text, "reason": text,
        },
    }
    finding = {
        "type": "object", "additionalProperties": False,
        "required": ["summary", "evidence"],
        "properties": {"summary": text, "evidence": {"type": "array", "minItems": 1, "items": evidence}},
    }
    coverage = {
        "type": "object", "additionalProperties": False,
        "required": ["status", "inspected_paths", "limitations"],
        "properties": {
            "status": {"type": "string", "enum": ["complete", "partial"]},
            "inspected_paths": {"type": "array", "items": text},
            "limitations": {"type": "array", "items": text},
        },
    }
    rule_id = {"type": "string", "minLength": 1}
    if rule_ids is not None:
        rule_id["enum"] = list(rule_ids)
    row = {
        "type": "object", "additionalProperties": False,
        "required": ["rule_id", "status", "confidence", "findings", "coverage"],
        "properties": {
            "rule_id": rule_id,
            "status": {"type": "string", "enum": ["passed", "failed", "skipped", "inconclusive", "error"]},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "findings": {"type": "array", "items": finding},
            "coverage": coverage, "reason": text,
        },
    }
    return {
        "type": "object", "additionalProperties": False,
        "required": ["schema_version", "batch_id", "results"],
        "properties": {
            "schema_version": {"type": "string", "const": "2.0"},
            "batch_id": {"type": "string", **({"const": batch_id} if batch_id else {"minLength": 1})},
            "results": {"type": "array", "items": row,
                        **({"minItems": len(rule_ids), "maxItems": len(rule_ids)}
                           if rule_ids is not None and batch_id is not None else {})},
        },
    }


def response_example(batch_id, rule_ids):
    return {
        "schema_version": "2.0", "batch_id": batch_id,
        "results": [{
            "rule_id": rule_id, "status": "inconclusive", "confidence": 0,
            "reason": "Example only; replace with the actual assessment.",
            "findings": [], "coverage": {"status": "partial", "inspected_paths": [],
                                       "limitations": ["Example only; source has not been assessed."]},
        } for rule_id in rule_ids],
    }
