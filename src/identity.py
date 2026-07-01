"""
Identity Resolution.

The assignment explicitly forbids fuzzy name matching. This module
implements Option A from DESIGN.md: a deterministic hierarchy of
identifiers, tried in a fixed order until one resolves. Option B
(composite deterministic identity score) is implemented alongside it
behind `identity_strategy` in config.yaml, but hierarchy is the
recommended default -- see DESIGN.md for the full comparison.

Hierarchy order:
  1. Explicit candidate_id  (if the structured source supplies one)
  2. Normalized, validated email
  3. Normalized, validated phone
  4. GitHub username
  5. Unresolved -> a deterministic synthetic id is generated from a
     stable hash of whatever weak signals exist, so downstream stages
     never see a None identity, but the result is flagged
     `resolved: False` for human review.

No probabilistic scoring, no ML, no similarity thresholds anywhere in
this module -- every decision is a simple, explainable if/else.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from src.normalization import normalize_email, normalize_phone
from src.validation import validate_email, validate_phone


@dataclass
class IdentityResolution:
    candidate_id: str
    strategy: str
    resolved: bool
    resolution_path: List[str] = field(default_factory=list)
    composite_score: Optional[float] = None


def _stable_hash(*parts: Any) -> str:
    joined = "|".join(str(p) for p in parts if p)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:12]


def resolve_hierarchy(sources_raw: Dict[str, Dict[str, Any]]) -> IdentityResolution:
    """
    sources_raw: {source_name: raw_data_dict}
    """
    path: List[str] = []

    # 1. Explicit ID from the structured/system-of-record source.
    structured = sources_raw.get("structured", {})
    explicit_id = structured.get("candidate_id") or structured.get("id")
    if explicit_id:
        path.append("explicit_id")
        return IdentityResolution(str(explicit_id), "hierarchy", True, path)

    # 2. Email, across all sources, first valid one wins (structured
    #    precedence is enforced by iteration order).
    for src_name in ("structured", "github", "resume", "notes"):
        raw = sources_raw.get(src_name, {})
        email = normalize_email(raw.get("email"))
        if email and validate_email(email).valid:
            path.append(f"email:{src_name}")
            return IdentityResolution(email, "hierarchy", True, path)

    # 3. Phone.
    for src_name in ("structured", "github", "resume", "notes"):
        raw = sources_raw.get(src_name, {})
        phone = normalize_phone(raw.get("phone"))
        if phone and validate_phone(phone).valid:
            path.append(f"phone:{src_name}")
            return IdentityResolution(phone, "hierarchy", True, path)

    # 4. GitHub username.
    for src_name in ("structured", "github", "resume", "notes"):
        raw = sources_raw.get(src_name, {})
        gh = raw.get("github_username")
        if gh:
            path.append(f"github_username:{src_name}")
            return IdentityResolution(f"gh:{gh}", "hierarchy", True, path)

    # 5. Unresolved -> deterministic synthetic id from whatever weak
    #    signals exist, so re-runs on the same input are still stable.
    name = structured.get("full_name") or sources_raw.get("resume", {}).get("full_name")
    synthetic = "unresolved:" + _stable_hash(name, *[sources_raw.get(s, {}).get("email") for s in sources_raw])
    path.append("unresolved_synthetic")
    return IdentityResolution(synthetic, "hierarchy", False, path)


def resolve_composite_score(sources_raw: Dict[str, Dict[str, Any]], threshold: float = 0.5) -> IdentityResolution:
    """
    Option B: composite deterministic identity score. Each validated
    identifier that's consistent *across at least two sources*
    contributes a fixed weight; total score must clear `threshold` to
    count as resolved. Still fully deterministic (no probability, no
    similarity/fuzzy matching) -- it just aggregates multiple exact-match
    signals instead of stopping at the first hit.
    """
    weights = {"email": 0.5, "phone": 0.3, "github_username": 0.2}
    score = 0.0
    path: List[str] = []

    def values_for(field_name: str, normalizer=None):
        vals = []
        for src, raw in sources_raw.items():
            v = raw.get(field_name)
            if normalizer:
                v = normalizer(v)
            if v:
                vals.append((src, v))
        return vals

    email_vals = values_for("email", normalize_email)
    if len({v for _, v in email_vals}) == 1 and len(email_vals) >= 2 and validate_email(email_vals[0][1]).valid:
        score += weights["email"]
        path.append("email_corroborated")

    phone_vals = values_for("phone", normalize_phone)
    if len({v for _, v in phone_vals}) == 1 and len(phone_vals) >= 2 and validate_phone(phone_vals[0][1]).valid:
        score += weights["phone"]
        path.append("phone_corroborated")

    gh_vals = values_for("github_username")
    if len({v for _, v in gh_vals}) == 1 and len(gh_vals) >= 2:
        score += weights["github_username"]
        path.append("github_username_corroborated")

    resolved = score >= threshold
    if resolved:
        anchor = (email_vals[0][1] if email_vals else None) or (phone_vals[0][1] if phone_vals else None) or f"gh:{gh_vals[0][1]}"
        cid = str(anchor)
    else:
        # fall back to hierarchy for an id even if confidence threshold not met
        fallback = resolve_hierarchy(sources_raw)
        cid = fallback.candidate_id

    return IdentityResolution(cid, "composite_score", resolved, path, composite_score=score)


def resolve_identity(sources_raw: Dict[str, Dict[str, Any]], strategy: str = "hierarchy") -> IdentityResolution:
    if strategy == "composite_score":
        return resolve_composite_score(sources_raw)
    return resolve_hierarchy(sources_raw)
