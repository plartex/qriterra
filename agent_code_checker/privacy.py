"""Minimize external diagnostics; provide an explicit report export filter."""

import os
import re
from pathlib import Path


def diagnostic_error(exc):
    """Never persist arbitrary provider output, even for unknown token formats."""
    from .validation import BatchProtocolError
    if isinstance(exc, BatchProtocolError):
        detail = "outside the project target" if "outside the project target" in str(exc) else "invalid response schema or evidence"
        return f"BatchProtocolError: {detail}"
    category = "Provider native turn failed" if type(exc).__name__ == "ProviderExecutionError" else "Evaluation failed"
    # These fixed codes help recovery without copying the surrounding CLI output.
    codes = [code for code in ("outside_workspace", "permission_denied", "timeout")
             if code in str(exc).lower()]
    return f"{type(exc).__name__}: {category}" + (" (" + ", ".join(codes) + ")" if codes else "")


def diagnostic_details(value):
    """Only counters and explicit probe accounting are safe diagnostic metadata."""
    if not isinstance(value, dict):
        return None
    result = {}
    for key in ("policy_probe_usage", "usage_includes_policy_probe"):
        item = value.get(key)
        if key == "policy_probe_usage" and isinstance(item, dict):
            result[key] = {k: v for k, v in item.items()
                           if k in {"input_tokens", "output_tokens", "total_tokens"}
                           and type(v) is int and v >= 0}
        elif key == "usage_includes_policy_probe" and type(item) is bool:
            result[key] = item
    return result


def assessment_error(message):
    """Retain fixed validation categories, never arbitrary response text."""
    categories = ("outside the project target", "cannot pass", "excerpt")
    return "Invalid assessment: " + next((code for code in categories if code in (message or "")),
                                         "provider reported an assessment error")


def redact_text(text, *, workspace=None):
    for key, value in os.environ.items():
        if len(value) >= 8 and re.search(r"TOKEN|SECRET|PASSWORD|API_?KEY|PRIVATE_?KEY", key, re.I):
            text = text.replace(value, "[redacted]")
    if workspace is not None:
        for prefix in (str(workspace), Path(workspace).as_posix()):
            text = text.replace(prefix, "<target>")
    text = re.sub(r"(?i)\b[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\b", "[session-id]", text)
    text = re.sub(r"(?i)(?:[a-z]:[\\/]|/(?:home|Users|tmp|var|opt)/)[^\s\"'<>]*", "[local-path]", text)
    text = re.sub(r"(?i)\b(?:glpat-[\w.-]+|gh[pousr]_[\w]+|github_pat_[\w]+|sk-[\w-]{12,})", "[redacted]", text)
    text = re.sub(r"(?i)(authorization\s*[:=]\s*(?:bearer|basic)\s+)\S+", r"\1[redacted]", text)
    text = re.sub(r"(?i)(https?://)[^\s/@:]+:[^\s/@]+@", r"\1[redacted]@", text)
    text = re.sub(r'''(?i)((?:api[_-]?key|password|secret|access[_-]?token)["']?\s*[:=]\s*["']?)[^\s,"'}]+''', r"\1[redacted]", text)
    return text


def shareable_report(value, *, workspace=None):
    if isinstance(value, dict):
        return {key: shareable_report(item, workspace=workspace) for key, item in value.items()
                if key not in {"debug_trace", "run_id", "session_id", "conversation_id", "task_id"}}
    if isinstance(value, (list, tuple)):
        return [shareable_report(item, workspace=workspace) for item in value]
    return redact_text(value, workspace=workspace) if isinstance(value, str) else value
