"""
Merge Engine.

For every canonical field, gathers every source's normalized value +
provenance, then applies deterministic merge rules:

  1. If only one source supplied a (valid) value, it wins trivially.
  2. If multiple sources agree (same normalized value) -> no conflict,
     that value wins, and agreement later boosts confidence
     ("corroboration").
  3. If sources disagree -> this is a genuine conflict. It is resolved
     by source trust score (config.yaml `source_trust`), with
     `source_precedence` as a deterministic tie-breaker. The losing
     values are NOT discarded -- they remain attached as `evidence`
     with `conflict=True` and `conflicting_values` populated, so the
     decision is fully auditable and nothing is silently overwritten.
  4. Invalid values are deprioritized versus valid ones from a
     lower-trust source, but never deleted -- they're kept as evidence
     with `valid=False`.

This module contains zero AI/ML and zero probabilistic logic, per the
assignment's requirement that identity resolution, merge decisions,
confidence scoring, and canonical mapping never involve AI.
"""
from __future__ import annotations

from typing import Any, Dict, List

from src.models import FieldValue, ProvenanceRecord, RawRecord
from src.normalization import normalize_field
from src.validation import validate_field
from src.config import Config


def build_provenance(records: List[RawRecord], field_name: str) -> List[ProvenanceRecord]:
    provenance = []
    for rec in records:
        if field_name not in rec.data:
            continue
        raw_value = rec.data[field_name]
        normalized = normalize_field(field_name, raw_value)
        result = validate_field(field_name, normalized)
        provenance.append(ProvenanceRecord(
            source=rec.source_name,
            extraction_method=rec.extraction_method,
            raw_value=raw_value,
            normalized_value=normalized,
            valid=result.valid,
            validation_notes=result.notes,
            timestamp=rec.fetched_at,
        ))
    return provenance


def merge_field(field_name: str, records: List[RawRecord], config: Config) -> FieldValue:
    provenance = build_provenance(records, field_name)

    if not provenance:
        return FieldValue(name=field_name, value=None, confidence=0.0, winning_source=None)

    # Prefer valid entries; among those, pick by (source_trust desc, precedence asc).
    def sort_key(p: ProvenanceRecord):
        trust = config.source_trust.get(p.source, 0.0)
        try:
            precedence_rank = config.source_precedence.index(p.source)
        except ValueError:
            precedence_rank = len(config.source_precedence)
        return (not p.valid, -trust, precedence_rank)  # False sorts before True -> valid first

    ranked = sorted(provenance, key=sort_key)
    winner = ranked[0]

    def _hashable(v):
        return tuple(v) if isinstance(v, list) else v

    seen = {}
    for p in provenance:
        if p.normalized_value is not None:
            seen[_hashable(p.normalized_value)] = p.normalized_value
    distinct_values = list(seen.values())
    conflict = len(distinct_values) > 1
    winner_key = _hashable(winner.normalized_value)
    conflicting_values = sorted(
        (v for k, v in seen.items() if k != winner_key),
        key=lambda x: str(x),
    ) if conflict else []

    return FieldValue(
        name=field_name,
        value=winner.normalized_value,
        confidence=0.0,  # filled in by ConfidenceEngine
        winning_source=winner.source,
        evidence=provenance,
        conflict=conflict,
        conflicting_values=conflicting_values,
    )


def merge_all_fields(records: List[RawRecord], config: Config, field_names: List[str]) -> Dict[str, FieldValue]:
    result = {}
    for fname in field_names:
        merged = merge_field(fname, records, config)
        if merged.evidence:  # only include fields that at least one source attempted
            result[fname] = merged
    return result
