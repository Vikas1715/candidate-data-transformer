# DESIGN.md — Architecture Discussion

This document captures every architectural decision, trade-off, and requirement
mapping for the Multi-Source Candidate Data Transformer, in implementation-oriented
terms rather than abstract theory.

## 1. Requirements Checklist → Implementation Mapping

| Requirement | Design/Implementation |
|---|---|
| Deterministic outputs for identical inputs | No randomness, no ML, no wall-clock-dependent logic in identity/merge/confidence. Verified by running the same input twice and diffing output (see README "Determinism check"). |
| High correctness and auditability | Every field carries full `ProvenanceRecord` evidence (`src/models.py`), nothing is discarded on merge. |
| Clear provenance for every field | `FieldValue.evidence: List[ProvenanceRecord]` — source, extraction method, raw value, normalized value, validity, timestamp. |
| Modular, plugin-based architecture | `SourceConnector` ABC (`src/connectors/base.py`); new sources = new subclass, zero changes elsewhere. |
| CLI-first design | `cli.py`, argparse, three subcommands (`transform`, `validate`, `batch`). |
| Clean separation of responsibilities | 10 independent modules: connectors → normalization → validation → identity → merge → confidence → projection → reports. Each is independently unit-tested. |
| Easy addition of new data sources | Implement `fetch() -> RawRecord`, register in `pipeline.CandidateSources` / `fetch_all_sources`. No core pipeline changes. |
| Scale from one candidate to batches | `cli.py batch` reuses `run_single_candidate` per manifest entry; candidates share no mutable state. |
| Deterministic identity, no fuzzy matching | `src/identity.py` — exact-match hierarchy only, tested explicitly (`test_no_fuzzy_matching_used`). |
| Deterministic confidence, no ML/statistics | `src/confidence.py` — pure arithmetic over discrete evidence signals. |
| No silent overwrites in merge | `src/merge.py` keeps all sources' evidence on the `FieldValue` even when they lose. |
| AI never in identity/merge/confidence/canonical mapping | Those four modules have zero AI/LLM calls or imports — verifiable by inspection. Optional AI is not implemented in this build (not required by the current data sources), but the extension point is documented in §8. |
| Data Quality Report | `src/reports/quality.py` |
| Metrics Report | `src/reports/metrics.py`, `MetricsCollector` threaded through `pipeline.py` |
| HTML Explainability Report | `src/reports/html_report.py` |
| GitHub API caching | `src/cache.py` + `src/connectors/github_connector.py` |
| Config-driven trust/precedence/confidence | `config.yaml` + `src/config.py` |

## 2. Internal Model vs. Output Model (Option A vs. Option B)

**Option A — single model for internal + output.** One schema is used both as the
working representation during merge and as what gets serialized to the user.

- *Advantages:* less code, one source of truth, no mapping step.
- *Disadvantages:* the model has to carry both "everything we know" (evidence,
  provenance, conflict flags) and "what the consumer wants" (flat, clean values).
  These pull in opposite directions — evidence is inherently nested/verbose,
  consumer output should be flat and stable.
- *Maintainability:* poor over time — any internal change to how evidence is
  tracked risks silently changing the public output contract.
- *Validation complexity:* one validator has to handle both "is this raw evidence
  well-formed" and "is this a legal thing to hand to a consumer," which are
  different questions with different failure semantics.
- *Projection limitations:* if you later need a second output shape (e.g. an
  ATS-specific export with different field names), you either fork the whole
  model or bolt on conditional serialization logic.
- *Testing:* tests end up asserting on internal implementation details (evidence
  structure) whenever they check output correctness, which is brittle.
- *When appropriate:* small scripts, prototypes, or pipelines with exactly one
  consumer and no expectation of schema evolution.

**Option B — separate `CanonicalCandidate` (internal) and `CandidateProjection`
(output), implemented here.**

- *Advantages:* the canonical model can carry arbitrarily rich provenance without
  affecting the consumer contract. Output schema can gain new projections (e.g.
  `ats_export`, `public_profile`) as pure functions of the canonical model, with
  zero changes to merge/confidence/identity.
- *Disadvantages:* one extra stage (`projection.py`) and the corresponding mapping
  code to maintain; a field added to canonical doesn't appear in output until the
  projection function is updated (this is deliberate, not accidental).
- *Flexibility / schema evolution:* projection schema is versioned
  (`SCHEMA_VERSION` in `models.py`) independently from internal representation.
- *Output customization:* trivial — add a new function in `projection.py`.
- *Testing:* canonical-model tests (merge/confidence correctness) and
  projection-schema tests (`validate_projection_schema`) are fully independent.
- *When preferable:* any system expected to grow more than one source, more than
  one consumer, or evolve its output contract over time — i.e. this project.

**Recommendation: Option B.** The assignment explicitly asks for extensibility,
schema evolution, and a projection layer — Option A cannot satisfy those without
eventually degrading into Option B anyway.

## 3. Identity Resolution: Hierarchy vs. Composite Score

Both are implemented (`src/identity.py`, toggle via `identity_strategy` in
`config.yaml`). Neither uses fuzzy/similarity matching — every comparison is an
exact match on a normalized, validated identifier.

**Option A — deterministic hierarchy** (explicit ID → email → phone → GitHub
username → unresolved synthetic ID).

- *Benefits:* trivial to explain ("first identifier found in priority order
  wins"), O(1) mental model, very fast, easy to unit test exhaustively (5 cases
  cover the whole space).
- *Limitations:* stops at the first hit — if a validated email is present but
  wrong (e.g. a typo that still happens to pass the regex), the hierarchy has no
  way to notice that a *different*, more strongly corroborated identifier (say,
  phone number, agreed by two sources) exists. It's "first match", not "best
  match".

**Option B — composite deterministic identity score.** Every validated
identifier that's *corroborated by ≥2 independent sources* contributes a fixed
weight (email 0.5, phone 0.3, GitHub username 0.2); total must clear a threshold
(0.5 by default) to count as resolved.

- *Advantages:* rewards cross-source agreement specifically, which is a stronger
  identity signal than a single source's say-so; still 100% deterministic (fixed
  weights, exact-match corroboration check, no similarity thresholds).
- *Risks:* more parameters to tune (weights, threshold) — a badly-chosen
  threshold could make identity resolution the same as hierarchy is trying to
  strengthen (over-rejection) or too permissive (under-rejection).
- *Complexity:* more moving parts than hierarchy; harder to explain in one
  sentence to a non-engineer.
- *Failure modes:* if no field is corroborated by 2+ sources (single-source
  candidate profiles), composite score always falls back to hierarchy anyway —
  so it strictly needs hierarchy as a fallback, not a replacement.

**Recommendation: hierarchy as the default** (`identity_strategy: hierarchy`).
It is simpler, fully covers the required data sources (structured source is
almost always present and trustworthy), and composite score's main benefit
(rewarding corroboration) is *already* captured downstream in the Confidence
Engine's `corroboration` signal — so composite score would be solving a problem
the pipeline already solves elsewhere, at the cost of extra complexity in the one
place (identity) that most benefits from being trivially explainable. Composite
score remains available via config for deployments where corroboration-based
identity is specifically desired (e.g. deduplicating candidates across many
low-trust free-text sources with no structured system of record).

## 4. Confidence Model: Weighted Average vs. Evidence-Based Aggregation

**Why evidence-based aggregation (implemented) is not a cosmetic variant of a
weighted average:**

A weighted average combines several *scores of the same kind* (e.g. "source A's
confidence in this field" and "source B's confidence in this field") into one
number by `Σ(w_i * score_i) / Σ(w_i)`. It has no vocabulary for:

1. **Cross-source agreement as its own signal.** Two independent sources
   producing the identical normalized value is categorically different evidence
   than one source being "very confident" — a weighted average can't represent
   "two weak-trust sources agreeing" as stronger evidence than "one high-trust
   source alone," but the evidence-based model can and does (`corroboration`
   term, computed as *fraction of sources that agree with the winner*, entirely
   separate from `source_trust`).
2. **Negative evidence (penalties).** A weighted average of positive terms cannot
   express "this field is in active conflict across sources" as a *subtraction*.
   This implementation explicitly subtracts `conflict_penalty * num_conflicting_values`
   from the aggregate — a distinct evidence class, not folded into any weight.
3. **Heterogeneous evidence types.** `validation_pass` is binary evidence about
   the *value's* well-formedness; `freshness` is evidence about *when* the data
   was captured; `completeness` is evidence about whether the field was supplied
   at all. A weighted average of "source confidences" has no field for any of
   these — they're not comparable to a per-source score, they're independent
   axes of evidence. This implementation sums five *independently derived*
   signals (`src/confidence.py`), each computed by different logic, rather than
   averaging N instances of the same thing.

In short: a weighted average asks "how much should I trust each source's number?"
This model asks "how much total evidence exists for this field, across five
different *kinds* of evidence?" — that's a structurally different question, not
a relabeling of the same one.

## 5. Data Modeling & Validation

- **Single canonical schema:** `CanonicalCandidate` with a fixed `CANONICAL_FIELDS`
  list (`src/models.py`). Adding a field means adding it to this list plus one
  entry each in `normalization.NORMALIZERS` and (optionally) `validation.VALIDATORS`.
- **Validation strategy:** two-tier. Field-level (`validate_field`) checks a value
  in isolation (regex/range checks); cross-field (`cross_field_validate`) checks
  relationships between already-normalized fields (e.g. "Senior" title with <3
  years experience). Field-level failures affect confidence directly; cross-field
  failures are warnings surfaced in the Data Quality Report, not hard failures —
  they often indicate something worth a human glance, not necessarily bad data.
- **Normalization rules:** pure, field-keyed functions (`normalization.NORMALIZERS`)
  — email lowercased/trimmed, phone digits-only with optional leading `+`, names
  title-cased, lists split/trimmed. Runs independently per source, before merge,
  so merge only ever compares already-normalized values.
- **Schema evolution:** `CandidateProjection` is versioned (`SCHEMA_VERSION`);
  canonical model fields can be added freely without touching the output contract
  until a projection function chooses to expose them.
- **Projection layer:** `src/projection.py` — a pure function `project()` plus a
  structural `validate_projection_schema()` pass that runs immediately before
  output is written, so malformed output is caught at the source rather than
  discovered downstream.
- **Future extensibility:** new source = new connector; new output field = new
  entry in `CANONICAL_FIELDS` + normalizer + (optional) validator; new output
  shape = new projection function.

**Recommended design:** the two-tier validation + separate canonical/projection
split above (already implemented) — it's the minimum structure that satisfies
every explicit assignment requirement without over-engineering (no schema
registry, no plugin discovery magic, no dynamic field definitions — all of which
would add complexity this project's scope doesn't yet justify).

## 6. Parallel Processing

- **Independent source parsing:** each source (CSV, resume, notes, GitHub) is
  fetched by an independent `SourceConnector.fetch()` call with no shared state.
- **`ThreadPoolExecutor` for I/O-bound work:** `pipeline.fetch_all_sources` submits
  every connector's `fetch()` to a `ThreadPoolExecutor`. This is genuinely
  I/O-bound work (disk reads, one HTTP call) — threads are correct here;
  multiprocessing would add pickling overhead for no CPU-bound benefit, and
  `asyncio` would require every connector (including `pypdf`, `csv`, `requests`)
  to be rewritten as async, which none of them are natively.
- **Synchronization before merge:** `as_completed()` is fully drained (every
  future resolved or excepted) before identity resolution or merge ever runs.
  This is what keeps the pipeline deterministic — merge never sees a
  partially-populated source set depending on network timing.
- **Worker pools / streaming readers / chunk-based processing:** not needed at
  current scale (single candidate = 4 small files/one API call), but the same
  `ThreadPoolExecutor` pattern generalizes directly: for very large resume PDFs
  or CSV files with many candidate rows, `StructuredConnector` could be extended
  to a streaming `csv.reader` that yields rows in chunks rather than
  `next(reader)`, without changing any other stage.
- **Where parallelism helps:** fetching multiple *independent* sources for one
  candidate, or processing multiple *independent* candidates in a batch.
- **Where sequential execution is preferable:** everything after fetch — identity
  resolution, merge, confidence, projection — is CPU-light, fast, and *depends*
  on having the complete fetched set, so parallelizing it would add
  synchronization complexity for negligible speedup.

## 7. Scalability

**Current implementation** (what's built): single machine, CLI-driven,
`ThreadPoolExecutor` for per-candidate I/O concurrency, sequential loop across
candidates in `batch` mode. This comfortably handles "thousands of candidates"
in a single run because each candidate's work is small (a handful of file
reads/regexes plus one cached-when-possible API call) and memory use is O(1) per
candidate (nothing is accumulated across the batch except summary metrics).

**Future architecture** (not built, by design — see "recommended, not
required over-engineering" in §5): the exact same `run_single_candidate()`
function used by `batch` today has **zero shared mutable state** between
candidates, which is precisely what makes it horizontally scalable without
touching business logic:
- **Chunk processing:** a batch manifest could be split into N chunks, each
  processed by a separate worker — no change to `run_single_candidate`.
- **Distributed workers / queue-ready design:** `run_single_candidate(sources,
  config, cache_dir)` is a pure function of its inputs (plus the shared,
  read-mostly GitHub cache) — it could be dropped directly into a task-queue
  consumer (Celery/RQ/SQS worker) as the task body with no modification.
- **Horizontal scaling:** because there's no in-memory cross-candidate state,
  scaling out is "run more workers pulling from the same queue," not a
  redesign. The one shared resource, `GithubCache`, is already file-based and
  would need to move to a shared store (Redis/S3) in a truly distributed
  deployment — this is the single documented seam where current design would
  need to change, and it's isolated entirely inside `cache.py`.

## 8. Merge Strategy

- **Deterministic rules:** for each field, rank all sources' (validity, trust,
  precedence) and take the top-ranked value (`merge.merge_field`). No randomness,
  no "most recent wins" heuristic (which would be non-deterministic given
  same-second timestamps) unless trust/precedence are tied.
- **Conflict handling:** any field where sources disagree after normalization is
  flagged `conflict=True`; conflicting values are recorded on the `FieldValue`,
  not discarded.
- **Evidence preservation:** *every* source's `ProvenanceRecord` for a field is
  kept in `FieldValue.evidence`, win or lose.
- **Field precedence:** `config.yaml: source_precedence`, used only as a
  tie-breaker after trust score and validity.
- **Auditability / explainability:** the HTML report renders every field's full
  evidence table, including losing values and why they lost.
- **No silent overwrites:** by construction — there is no code path in
  `merge.py` that discards a source's contribution; it always ends up in
  `evidence`, even when it doesn't win.

## 9. Provenance

Every `ProvenanceRecord` (`src/models.py`) captures: `source`, `extraction_method`,
`raw_value`, `normalized_value`, `valid`, `validation_notes`, `timestamp`. This is
computed once in `merge.build_provenance` and reused by the Confidence Engine, the
Data Quality Report, and the HTML report — a single source of truth for "what do
we know about this value and where did it come from."

## 10. Optional AI — Boundary and Extension Point

**Not implemented in this build** (none of the four current sources — CSV/JSON,
resume text, recruiter notes, GitHub API — strictly require it; the regex-based
extraction in `resume_connector.py` and `notes_connector.py` already satisfies
"free-text extraction" deterministically for the fields required).

If added later, the boundary is: an AI-assisted extractor would be a *connector*
(or a helper called inside one), returning a `RawRecord` exactly like every other
source — flowing through the same normalization → validation → merge →
confidence pipeline. Concretely, it would live in something like
`src/connectors/ai_resume_enrichment.py`, tag its `extraction_method` with an
`"ai:"` prefix (e.g. `"ai:llm_entity_extraction"`) so it's visibly distinguishable
in every provenance record and the HTML report, and set `source_trust` for that
source deliberately low/explicit in `config.yaml` by default. It would **never**
be called from `identity.py`, `merge.py`, or `confidence.py` — those three modules
have no AI dependency today and none should be added; this is enforced by code
review / inspection rather than a runtime check, since the requirement is
architectural (AI must not participate in those decisions), not something a unit
test can fully guarantee.

## 11. Testing Strategy

40 unit tests across 6 files (`tests/`), run via `python3 -m unittest discover -s tests`:

| File | Covers |
|---|---|
| `test_normalization.py` | Field normalizers (email, phone, name, list) |
| `test_validation.py` | Field-level + cross-field validators |
| `test_identity.py` | Both identity strategies, explicitly asserts no fuzzy matching |
| `test_merge_confidence.py` | Conflict resolution, evidence preservation, confidence scoring, agreement vs. conflict |
| `test_projection_and_quality.py` | Canonical → projection mapping, schema validation, quality report scoring |
| `test_cache.py` | GitHub cache hit/miss/expiry/corruption handling |

Not included as automated tests (exercised manually, documented in README):
CLI smoke tests (`transform`/`validate`/`batch` all run successfully against
`sample_data/`) and an explicit determinism check (same input run twice → byte-
identical projection output modulo timestamps).

## 12. Summary of Deliberate Non-Choices

To keep the codebase "easy to build, no compromise on requirements" rather than
over-engineered:
- No pydantic/heavy validation framework — plain `dataclasses` + explicit
  validator functions give full control and zero extra dependencies (the
  container this was built in had no network access to install pydantic, which
  also validates the choice: the project runs with only `pyyaml`, `pypdf`, and
  `requests`, all genuinely necessary).
- No Jinja2 for the HTML report — plain f-string templates with HTML-escaping
  are sufficient for one report type.
- No plugin auto-discovery/registry for connectors — four sources don't justify
  it; explicit imports in `pipeline.py` are simpler to read and debug.
- No distributed queue/worker implementation — not required at "thousands of
  candidates on a single machine" scale; the seam to add it later is documented
  in §7 rather than built speculatively.
