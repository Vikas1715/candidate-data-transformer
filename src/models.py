"""
Core data models.

Design decision (see DESIGN.md "Architecture Discussion" for full reasoning):
We use plain `dataclasses` rather than a framework like pydantic so the
project has zero heavyweight dependencies and the validation layer is
fully explicit and inspectable (validation.py), rather than implicit
inside model `__init__`. This keeps parsing/validation/projection as
separate, testable stages instead of collapsing them into one model
(this is "Option B" in the design brief: separate internal canonical
model vs. external projection model).

Field-level provenance is mandatory: every value that ends up in the
canonical model carries a ProvenanceRecord so the pipeline is fully
auditable and explainable.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Stage 1: raw, source-level data
# ---------------------------------------------------------------------------

@dataclass
class RawRecord:
    """Output of a Source Connector: one source's raw extracted key/values."""
    source_name: str            # "structured" | "resume" | "notes" | "github"
    source_type: str            # "csv" | "json" | "pdf" | "txt" | "api"
    origin: str                 # file path or URL the data came from
    data: Dict[str, Any]        # extracted field_name -> raw_value
    extraction_method: str      # e.g. "csv.DictReader", "regex:email", "github.rest.v3"
    fetched_at: float = field(default_factory=time.time)


# ---------------------------------------------------------------------------
# Stage 2: per-field provenance + evidence
# ---------------------------------------------------------------------------

@dataclass
class ProvenanceRecord:
    """Full audit trail for a single field's contribution from one source."""
    source: str
    extraction_method: str
    raw_value: Any
    normalized_value: Any
    valid: bool
    validation_notes: List[str] = field(default_factory=list)
    timestamp: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class FieldValue:
    """
    A single canonical field after merge + confidence scoring.
    `evidence` retains every contributing source's provenance, even ones
    that lost the merge -- nothing is silently discarded.
    """
    name: str
    value: Any
    confidence: float
    winning_source: Optional[str]
    evidence: List[ProvenanceRecord] = field(default_factory=list)
    conflict: bool = False
    conflicting_values: List[Any] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "value": self.value,
            "confidence": round(self.confidence, 4),
            "winning_source": self.winning_source,
            "conflict": self.conflict,
            "conflicting_values": self.conflicting_values,
            "evidence": [e.to_dict() for e in self.evidence],
        }


# ---------------------------------------------------------------------------
# Stage 3: canonical candidate (internal representation)
# ---------------------------------------------------------------------------

CANONICAL_FIELDS = [
    "candidate_id", "full_name", "email", "phone", "location",
    "current_title", "current_company", "years_experience",
    "skills", "education", "github_username", "github_public_repos",
    "github_followers", "github_bio", "summary",
]


@dataclass
class CanonicalCandidate:
    """
    Internal, fully-detailed representation. NOT what gets emitted directly --
    the Projection Engine maps this into one or more output schemas.
    """
    fields: Dict[str, FieldValue] = field(default_factory=dict)
    identity_resolution: Dict[str, Any] = field(default_factory=dict)
    sources_seen: List[str] = field(default_factory=list)

    def get(self, name: str) -> Optional[FieldValue]:
        return self.fields.get(name)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "identity_resolution": self.identity_resolution,
            "sources_seen": self.sources_seen,
            "fields": {k: v.to_dict() for k, v in self.fields.items()},
        }


# ---------------------------------------------------------------------------
# Stage 4: projection / output models
# ---------------------------------------------------------------------------

@dataclass
class CandidateProjection:
    """
    Flat, consumer-facing schema. This is intentionally decoupled from
    CanonicalCandidate so output shape can evolve (e.g. add a new export
    format for an ATS integration) without touching merge/confidence logic.
    """
    candidate_id: str
    full_name: Optional[str]
    email: Optional[str]
    phone: Optional[str]
    location: Optional[str]
    current_title: Optional[str]
    current_company: Optional[str]
    years_experience: Optional[float]
    skills: List[str]
    education: List[str]
    github_username: Optional[str]
    overall_confidence: float
    field_confidence: Dict[str, float]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


SCHEMA_VERSION = "1.0.0"
