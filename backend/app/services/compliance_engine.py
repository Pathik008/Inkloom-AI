"""Deterministic brand-compliance engine.

Pure functions only: no database, no network, no AI. Every finding is derived from a
real match (or a verified absence) of an APPROVED rule against the submitted text, so
nothing is fabricated. Findings that represent a *missing* element carry `start=None`,
`end=None`, `matched_text=None` and `evidence_excerpt=None` because there is no text to point at.
"""
from __future__ import annotations

import difflib
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable

ENGINE_VERSION = "1.0.0"

MAX_CONTENT_CHARS = 50_000
MAX_PATTERN_CHARS = 300
EVIDENCE_CONTEXT_CHARS = 60

# Transparent scoring model: score = max(0, 100 - sum(penalty per finding)).
SEVERITY_PENALTIES = {"CRITICAL": 40, "HIGH": 20, "MEDIUM": 10, "LOW": 5, "INFO": 0}
PASS_THRESHOLD = 70
BLOCKING_SEVERITIES = ("CRITICAL", "HIGH")

DEFAULT_PRICE_PATTERN = r"(?:[$€£₹]|Rs\.?|INR|USD)\s?\d[\d,]*(?:\.\d+)?"

_NESTED_QUANTIFIER = re.compile(r"\((?:[^()\\]|\\.)*[+*](?:[^()\\]|\\.)*\)\s*[+*{]")


class RuleDefinitionError(ValueError):
    """Raised when a rule's pattern cannot be safely evaluated."""


@dataclass(frozen=True)
class RuleSpec:
    """Engine-facing snapshot of a ComplianceRule (decoupled from the ORM)."""

    id: str
    rule_code: str
    rule_type: str
    severity: str
    title: str
    description: str
    target_pattern: str
    match_mode: str
    required_disclaimer_text: str | None = None
    suggested_replacement: str | None = None
    config: dict[str, Any] = field(default_factory=dict)


def validate_pattern(pattern: str, match_mode: str) -> None:
    """Reject empty, oversized or catastrophic-backtracking-prone patterns."""
    if not pattern or not pattern.strip():
        raise RuleDefinitionError("Pattern must not be empty.")
    if len(pattern) > MAX_PATTERN_CHARS:
        raise RuleDefinitionError(f"Pattern exceeds {MAX_PATTERN_CHARS} characters.")
    if match_mode == "REGEX":
        if _NESTED_QUANTIFIER.search(pattern):
            raise RuleDefinitionError("Regex contains nested quantifiers that risk catastrophic backtracking.")
        try:
            re.compile(pattern)
        except re.error as exc:
            raise RuleDefinitionError(f"Invalid regular expression: {exc}") from exc


def _compile(pattern: str, match_mode: str) -> re.Pattern[str]:
    validate_pattern(pattern, match_mode)
    if match_mode == "EXACT":
        return re.compile(re.escape(pattern))
    if match_mode == "CASE_INSENSITIVE":
        return re.compile(re.escape(pattern), re.IGNORECASE)
    if match_mode == "WORD_BOUNDARY":
        return re.compile(r"(?<!\w)" + re.escape(pattern) + r"(?!\w)", re.IGNORECASE)
    if match_mode == "REGEX":
        return re.compile(pattern, re.IGNORECASE)
    raise RuleDefinitionError(f"Unsupported match mode: {match_mode}")


def _excerpt(text: str, start: int, end: int) -> str:
    lo = max(0, start - EVIDENCE_CONTEXT_CHARS)
    hi = min(len(text), end + EVIDENCE_CONTEXT_CHARS)
    return ("…" if lo > 0 else "") + text[lo:hi] + ("…" if hi < len(text) else "")


def _normalise_ws(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().lower()


def _finding(
    rule: RuleSpec,
    *,
    kind: str,
    explanation: str,
    recommended_correction: str,
    start: int | None = None,
    end: int | None = None,
    text: str = "",
    replacement: str | None = None,
    append_text: str | None = None,
) -> dict[str, Any]:
    matched = text[start:end] if start is not None and end is not None else None
    return {
        "finding_id": str(uuid.uuid4()),
        "rule_id": rule.id,
        "rule_code": rule.rule_code,
        "rule_type": rule.rule_type,
        "rule_title": rule.title,
        "severity": rule.severity,
        "kind": kind,
        "matched_text": matched,
        "start": start,
        "end": end,
        "evidence_excerpt": _excerpt(text, start, end) if matched is not None else None,
        "explanation": explanation,
        "recommended_correction": recommended_correction,
        # Machine-applicable fix: replace [start, end) with `replacement`, or append `append_text`.
        "correction": {"replacement": replacement, "append_text": append_text},
    }


def _trigger_matches(rule: RuleSpec, text: str) -> tuple[bool, re.Match[str] | None]:
    trigger = (rule.config or {}).get("trigger_pattern")
    if not trigger:
        return True, None
    mode = (rule.config or {}).get("trigger_match_mode", "CASE_INSENSITIVE")
    m = _compile(str(trigger), mode).search(text)
    return (m is not None), m


def _evaluate_matching_rule(rule: RuleSpec, text: str) -> list[dict[str, Any]]:
    """PROHIBITED_TERM, RESTRICTED_CLAIM, TONE_CONSTRAINT: every occurrence is a finding."""
    findings = []
    for m in _compile(rule.target_pattern, rule.match_mode).finditer(text):
        if m.start() == m.end():
            continue
        if rule.suggested_replacement:
            fix = f'Replace "{m.group(0)}" with "{rule.suggested_replacement}".'
        else:
            fix = f'Remove or rephrase "{m.group(0)}".'
        findings.append(
            _finding(
                rule,
                kind="PROHIBITED_MATCH",
                explanation=f"{rule.title}: {rule.description}",
                recommended_correction=fix,
                start=m.start(),
                end=m.end(),
                text=text,
                replacement=rule.suggested_replacement if rule.suggested_replacement else "",
            )
        )
    return findings


def _evaluate_disclaimer(rule: RuleSpec, text: str) -> list[dict[str, Any]]:
    required = (rule.required_disclaimer_text or rule.target_pattern).strip()
    triggered, trig = _trigger_matches(rule, text)
    if not triggered:
        return []
    if _normalise_ws(required) in _normalise_ws(text):
        return []
    why = f"{rule.title}: {rule.description}"
    start = end = None
    if trig is not None:
        why += f' Required because the text contains "{trig.group(0)}".'
        start, end = trig.start(), trig.end()
    f = _finding(
        rule,
        kind="MISSING_DISCLAIMER",
        explanation=why,
        recommended_correction=f'Add the required disclaimer: "{required}"',
        text=text,
        append_text=required,
    )
    if start is not None:
        # Trigger evidence is real text: expose it as context without claiming it is the violation.
        f["trigger_text"] = text[start:end]
        f["trigger_start"] = start
        f["trigger_end"] = end
    return [f]


def _evaluate_terminology(rule: RuleSpec, text: str) -> list[dict[str, Any]]:
    triggered, _ = _trigger_matches(rule, text)
    if not triggered:
        return []
    if _compile(rule.target_pattern, rule.match_mode).search(text):
        return []
    term = rule.suggested_replacement or rule.target_pattern
    return [
        _finding(
            rule,
            kind="MISSING_TERMINOLOGY",
            explanation=f"{rule.title}: {rule.description}",
            recommended_correction=f'Include the required terminology "{term}".',
            text=text,
            append_text=term if rule.match_mode != "REGEX" or rule.suggested_replacement else None,
        )
    ]


def _extract_prices(value: str) -> list[str]:
    return [re.sub(r"[\s,]", "", p).lower() for p in re.findall(DEFAULT_PRICE_PATTERN, value)]


def _evaluate_price_integrity(rule: RuleSpec, text: str, approved_prices: set[str]) -> list[dict[str, Any]]:
    """Flag price mentions absent from the approved PRICING facts. Silent when no facts exist."""
    if not approved_prices:
        return []
    pattern = rule.target_pattern if rule.match_mode == "REGEX" else DEFAULT_PRICE_PATTERN
    findings = []
    for m in _compile(pattern, "REGEX").finditer(text):
        normalised = re.sub(r"[\s,]", "", m.group(0)).lower()
        if normalised in approved_prices:
            continue
        findings.append(
            _finding(
                rule,
                kind="UNAPPROVED_PRICE",
                explanation=f'{rule.title}: "{m.group(0)}" does not match any approved pricing fact.',
                recommended_correction="Use a price from the approved brand facts or remove the price claim.",
                start=m.start(),
                end=m.end(),
                text=text,
                replacement=None,
            )
        )
    return findings


def score_findings(findings: Iterable[dict[str, Any]]) -> dict[str, Any]:
    findings = list(findings)
    counts = {s: 0 for s in SEVERITY_PENALTIES}
    for f in findings:
        counts[f["severity"]] = counts.get(f["severity"], 0) + 1
    breakdown = [
        {
            "severity": s,
            "count": counts[s],
            "penalty_each": SEVERITY_PENALTIES[s],
            "penalty_total": counts[s] * SEVERITY_PENALTIES[s],
        }
        for s in SEVERITY_PENALTIES
    ]
    total = sum(b["penalty_total"] for b in breakdown)
    score = max(0, 100 - total)
    blocking = sum(counts.get(s, 0) for s in BLOCKING_SEVERITIES)
    passed = blocking == 0 and score >= PASS_THRESHOLD
    return {
        "score": score,
        "result": "PASS" if passed else "FAIL",
        "formula": "score = max(0, 100 - sum(severity penalties))",
        "pass_rule": f"PASS requires score >= {PASS_THRESHOLD} and zero CRITICAL/HIGH findings",
        "breakdown": breakdown,
        "total_penalty": total,
        "blocking_findings": blocking,
        "findings_by_severity": counts,
    }


def analyze(
    text: str,
    rules: Iterable[RuleSpec],
    *,
    approved_prices: Iterable[str] = (),
) -> dict[str, Any]:
    """Evaluate `text` against `rules` and return findings plus a transparent score."""
    if len(text) > MAX_CONTENT_CHARS:
        raise ValueError(f"Content exceeds {MAX_CONTENT_CHARS} characters.")
    price_set = {re.sub(r"[\s,]", "", p).lower() for p in approved_prices}
    findings: list[dict[str, Any]] = []
    evaluated = 0
    for rule in rules:
        evaluated += 1
        rt = rule.rule_type
        if rt == "MANDATORY_DISCLAIMER":
            findings.extend(_evaluate_disclaimer(rule, text))
        elif rt == "MANDATORY_TERMINOLOGY":
            findings.extend(_evaluate_terminology(rule, text))
        elif rt == "PRICE_INTEGRITY":
            findings.extend(_evaluate_price_integrity(rule, text, price_set))
        else:  # PROHIBITED_TERM, RESTRICTED_CLAIM, TONE_CONSTRAINT
            findings.extend(_evaluate_matching_rule(rule, text))

    findings.sort(
        key=lambda f: (
            list(SEVERITY_PENALTIES).index(f["severity"]),
            f["start"] if f["start"] is not None else 10**9,
            f["rule_code"],
        )
    )
    scoring = score_findings(findings)
    return {
        "engine_version": ENGINE_VERSION,
        "analysed_at": datetime.now(timezone.utc).isoformat(),
        "rules_evaluated": evaluated,
        "findings": findings,
        "scoring": scoring,
        "score": scoring["score"],
        "result": scoring["result"],
    }


def apply_corrections(text: str, findings: list[dict[str, Any]], finding_ids: set[str] | None = None) -> dict[str, Any]:
    """Apply machine-applicable corrections to `text`.

    Span replacements are applied right-to-left and overlapping spans are skipped (reported in
    `skipped`). Missing-element corrections are appended once each, de-duplicated.
    """
    selected = [f for f in findings if finding_ids is None or f["finding_id"] in finding_ids]
    span_fixes = sorted(
        (f for f in selected if f["start"] is not None and f["correction"]["replacement"] is not None),
        key=lambda f: f["start"],
        reverse=True,
    )
    applied: list[str] = []
    skipped: list[dict[str, str]] = []
    out = text
    lowest_start = len(text) + 1
    for f in span_fixes:
        if f["end"] > lowest_start:
            skipped.append({"finding_id": f["finding_id"], "reason": "Overlaps another correction."})
            continue
        out = out[: f["start"]] + f["correction"]["replacement"] + out[f["end"] :]
        lowest_start = f["start"]
        applied.append(f["finding_id"])

    out = re.sub(r"[ \t]{2,}", " ", out) if applied else out
    appended: list[str] = []
    for f in selected:
        add = f["correction"].get("append_text")
        if add and f["start"] is None and add not in appended and _normalise_ws(add) not in _normalise_ws(out):
            appended.append(add)
            applied.append(f["finding_id"])
    if appended:
        out = out.rstrip() + "\n\n" + "\n".join(appended)
    for f in selected:
        if f["finding_id"] not in applied and not any(s["finding_id"] == f["finding_id"] for s in skipped):
            skipped.append({"finding_id": f["finding_id"], "reason": "No automatic correction available."})
    return {"corrected_text": out, "applied_finding_ids": applied, "skipped": skipped}


def compare_analyses(
    before_text: str,
    before: dict[str, Any],
    after_text: str,
    after: dict[str, Any],
) -> dict[str, Any]:
    """Describe the difference between an original and a corrected analysis."""

    def key(f: dict[str, Any]) -> tuple[str, str, str]:
        return (f["rule_code"], f["kind"], (f["matched_text"] or "").lower())

    before_keys = {key(f): f for f in before["findings"]}
    after_keys = {key(f): f for f in after["findings"]}
    resolved = [f for k, f in before_keys.items() if k not in after_keys]
    remaining = [f for k, f in after_keys.items() if k in before_keys]
    introduced = [f for k, f in after_keys.items() if k not in before_keys]
    diff = list(
        difflib.unified_diff(
            before_text.splitlines(), after_text.splitlines(), "original", "corrected", lineterm="", n=2
        )
    )
    return {
        "score_before": before["score"],
        "score_after": after["score"],
        "score_delta": after["score"] - before["score"],
        "result_before": before["result"],
        "result_after": after["result"],
        "resolved_findings": resolved,
        "remaining_findings": remaining,
        "new_findings": introduced,
        "text_diff": diff,
    }
