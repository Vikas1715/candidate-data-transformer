"""
Confidence Engine: evidence-based aggregation (Option B from DESIGN.md),
NOT a plain weighted average.

Why this is meaningfully different from a weighted average (not cosmetic):
A weighted average combines a fixed set of *sub-scores of the same
field* (e.g. average of "source A's confidence" and "source B's
confidence"). It has no way to reward independent agreement, and it
treats every field's evidence set as the same shape.

This model instead computes five *independent, differently-derived*
signals per field and *additively* combines them, each capturing a
distinct kind of evidence:

  - validation_pass:  did the winning value pass field-level validation?
                       (binary evidence about the value itself)
  - corroboration:    what fraction of *all sources that attempted this
                       field* agree with the winning value? This is
                       evidence about cross-source agreement, which a
                       weighted average of per-source scores cannot
                       represent at all -- two sources agreeing is
                       categorically different evidence than one source
                       being individually "confident".
  - source_trust:     the configured trust score of the winning source
                       (evidence about provenance quality).
  - completeness:     was the field actually supplied (vs missing
                       entirely from every source)?
  - freshness:        how recent is the winning source's data, if a
                       timestamp is available (evidence about recency).

Conflicts are then *subtracted* as an explicit penalty per unresolved
conflicting distinct value, which a weighted average also cannot
express (there's no "penalty" term, only an average of positives).

The result is clamped to [min_confidence, max_confidence] from
config.yaml. Every step here is deterministic arithmetic -- no ML, no
statistical model, no learned parameters.
"""
from __future__ import annotations

import time
from typing import Dict

from src.models import FieldValue
from src.config import Config


def _corroboration_fraction(field_value: FieldValue) -> float:
    attempts = [e for e in field_value.evidence if e.normalized_value is not None]
    if not attempts:
        return 0.0
    agreeing = sum(1 for e in attempts if e.normalized_value == field_value.value)
    return agreeing / len(attempts)


def _freshness_score(field_value: FieldValue) -> float:
    winner_evidence = next((e for e in field_value.evidence if e.source == field_value.winning_source), None)
    if not winner_evidence or not winner_evidence.timestamp:
        return 0.5  # neutral if unknown, rather than penalizing
    age_seconds = max(0.0, time.time() - winner_evidence.timestamp)
    # Full score if fetched within the last hour of this pipeline run,
    # decaying linearly to 0 over 30 days. Same-run data is always fresh,
    # so this mostly matters for cached GitHub data.
    thirty_days = 30 * 24 * 3600
    return max(0.0, 1.0 - min(age_seconds, thirty_days) / thirty_days)


def score_field(field_value: FieldValue, config: Config) -> float:
    if field_value.value is None:
        return 0.0

    winner_evidence = next((e for e in field_value.evidence if e.source == field_value.winning_source), None)
    validation_pass = 1.0 if (winner_evidence and winner_evidence.valid) else 0.0
    corroboration = _corroboration_fraction(field_value)
    source_trust = config.source_trust.get(field_value.winning_source, 0.0)
    completeness = 1.0  # evidence exists -> field was supplied by at least one source
    freshness = _freshness_score(field_value)

    w = config.confidence_weights
    raw_score = (
        w.get("validation_pass", 0.30) * validation_pass
        + w.get("corroboration", 0.30) * corroboration
        + w.get("source_trust", 0.20) * source_trust
        + w.get("completeness", 0.10) * completeness
        + w.get("freshness", 0.10) * freshness
    )

    if field_value.conflict:
        num_conflicting_distinct_values = len(field_value.conflicting_values)
        raw_score -= config.conflict_penalty * num_conflicting_distinct_values

    return max(config.min_confidence, min(config.max_confidence, raw_score))


def score_all(fields: Dict[str, FieldValue], config: Config) -> None:
    """Mutates each FieldValue in place, setting `.confidence`."""
    for fv in fields.values():
        fv.confidence = score_field(fv, config)


def overall_confidence(fields: Dict[str, FieldValue]) -> float:
    scored = [fv.confidence for fv in fields.values() if fv.value is not None]
    if not scored:
        return 0.0
    return round(sum(scored) / len(scored), 4)
