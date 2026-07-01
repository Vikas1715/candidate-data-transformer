"""
Validation: field-level checks (does this normalized value look correct
in isolation?) and cross-field checks (are two canonical fields
mutually consistent?).

Validation results feed directly into the Confidence Engine
(`validation_pass` weight) and into the Data Quality Report -- this is
the single source of truth for "is this value trustworthy", so it's
kept in one module rather than duplicated in the confidence engine.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field as dc_field
from typing import Any, Dict, List

EMAIL_RE = re.compile(r"^[\w.+-]+@[\w-]+\.[\w.-]+$")
PHONE_RE = re.compile(r"^\+?\d{7,15}$")


@dataclass
class ValidationResult:
    valid: bool
    notes: List[str] = dc_field(default_factory=list)


def validate_email(value: Any) -> ValidationResult:
    if value is None:
        return ValidationResult(False, ["missing"])
    if EMAIL_RE.match(str(value)):
        return ValidationResult(True)
    return ValidationResult(False, ["does not match email pattern"])


def validate_phone(value: Any) -> ValidationResult:
    if value is None:
        return ValidationResult(False, ["missing"])
    if PHONE_RE.match(str(value)):
        return ValidationResult(True)
    return ValidationResult(False, ["does not match E.164-like phone pattern"])


def validate_years_experience(value: Any) -> ValidationResult:
    if value is None:
        return ValidationResult(False, ["missing"])
    try:
        n = float(value)
    except (TypeError, ValueError):
        return ValidationResult(False, ["not numeric"])
    if 0 <= n <= 60:
        return ValidationResult(True)
    return ValidationResult(False, [f"out of plausible range: {n}"])


def validate_non_empty(value: Any) -> ValidationResult:
    if value is None or value == "" or value == []:
        return ValidationResult(False, ["missing"])
    return ValidationResult(True)


# Field name -> validator. Fields without an explicit entry fall back to
# "non-empty" validation, which is enough for free-text fields like
# `summary`, `github_bio`, etc.
VALIDATORS = {
    "email": validate_email,
    "phone": validate_phone,
    "years_experience": validate_years_experience,
    "full_name": validate_non_empty,
    "candidate_id": validate_non_empty,
}


def validate_field(field_name: str, normalized_value: Any) -> ValidationResult:
    fn = VALIDATORS.get(field_name, validate_non_empty)
    return fn(normalized_value)


def cross_field_validate(fields: Dict[str, Any]) -> List[str]:
    """
    Checks relationships between multiple fields. Returns a list of
    human-readable warnings (does not hard-fail the pipeline -- these are
    surfaced in the Data Quality Report for human review).
    """
    warnings: List[str] = []

    years = fields.get("years_experience")
    title = fields.get("current_title")
    if years is not None and title and re.search(r"\bsenior\b|\blead\b|\bstaff\b|\bprincipal\b", title, re.I):
        if years < 3:
            warnings.append(
                f"Title '{title}' suggests seniority but years_experience is only {years}"
            )

    email = fields.get("email")
    if email and "@" in str(email):
        domain = str(email).split("@")[-1]
        if domain in {"example.com", "test.com", "domain.com"}:
            warnings.append(f"email domain '{domain}' looks like a placeholder")

    gh_repos = fields.get("github_public_repos")
    if gh_repos is not None and gh_repos < 0:
        warnings.append("github_public_repos is negative")

    return warnings
