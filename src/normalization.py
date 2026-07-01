"""
Normalization: pure functions that turn a raw extracted value into a
canonical representation, per field. Kept separate from validation
(a value can be normalized but still invalid, e.g. a well-formed but
undeliverable email) and separate from merging (normalization runs on
every source's value independently, before any cross-source decision
is made).
"""
from __future__ import annotations

import re
from typing import Any, List, Optional


def normalize_email(value: Any) -> Optional[str]:
    if not value:
        return None
    return str(value).strip().lower()


def normalize_phone(value: Any) -> Optional[str]:
    if not value:
        return None
    digits = re.sub(r"[^\d+]", "", str(value))
    # Keep a leading + if present, strip everything else non-numeric.
    if digits.startswith("+"):
        return "+" + re.sub(r"\D", "", digits[1:])
    return re.sub(r"\D", "", digits)


def normalize_name(value: Any) -> Optional[str]:
    if not value:
        return None
    parts = str(value).strip().split()
    return " ".join(p.capitalize() for p in parts) if parts else None


def normalize_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    return str(value).strip() or None


def normalize_list(value: Any) -> Optional[List[str]]:
    if value is None:
        return None
    if isinstance(value, list):
        items = value
    else:
        items = str(value).split(",")
    cleaned = [str(i).strip() for i in items if str(i).strip()]
    return cleaned or None


def normalize_number(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def normalize_int(value: Any) -> Optional[int]:
    n = normalize_number(value)
    return int(n) if n is not None else None


# Field name -> normalizer function. New fields just add an entry here.
NORMALIZERS = {
    "full_name": normalize_name,
    "email": normalize_email,
    "phone": normalize_phone,
    "location": normalize_text,
    "current_title": normalize_text,
    "current_company": normalize_text,
    "years_experience": normalize_number,
    "skills": normalize_list,
    "education": normalize_list,
    "github_username": normalize_text,
    "github_public_repos": normalize_int,
    "github_followers": normalize_int,
    "github_bio": normalize_text,
    "summary": normalize_text,
    "candidate_id": normalize_text,
}


def normalize_field(field_name: str, value: Any) -> Any:
    fn = NORMALIZERS.get(field_name, normalize_text)
    return fn(value)
