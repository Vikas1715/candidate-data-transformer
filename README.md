# Multi-Source Candidate Data Transformer

A production-oriented, deterministic pipeline that consolidates candidate data
from heterogeneous sources (structured CSV/ATS JSON, resume, recruiter notes,
GitHub API) into a single, fully-auditable canonical profile — with confidence
scoring, conflict tracking, and full field-level provenance.

CLI-first. No machine learning, no fuzzy matching, no non-determinism anywhere
in identity resolution, merging, or confidence scoring.

Full architecture discussion, trade-offs, and requirement-by-requirement mapping:
see **[`docs/DESIGN.md`](docs/DESIGN.md)**.

---

## What's new in this version

1. **Data Quality Report** — per-candidate summary of missing, invalid,
   conflicting fields, cross-field warnings, and a 0–100 overall quality score.
   (`*.quality.json`)
2. **Metrics Report** — execution time per pipeline stage, files processed,
   sources succeeded/failed, fields extracted/merged, conflicts detected,
   GitHub cache hit/miss counts. (`*.metrics.json`, plus `batch.metrics.json`
   for batch runs)
3. **HTML Explainability Report** — a browser-friendly page per candidate
   showing the final profile, per-field confidence badges, full evidence
   tables, and conflict call-outs. (`*.report.html`)
4. **GitHub API caching** — repeated lookups of the same username reuse a
   local on-disk cache instead of hitting the API again. See
   [GitHub connector details](#github-connector-in-detail) below.
5. **Externalized configuration** — source trust scores, source precedence,
   and confidence weights now live in `config.yaml`, not hardcoded in Python.

---

## Project layout

```
candidate_transformer/
├── cli.py                      # CLI entrypoint (transform / validate / batch)
├── config.yaml                 # trust scores, precedence, confidence weights, cache TTL
├── requirements.txt
├── src/
│   ├── config.py                # loads + defaults config.yaml
│   ├── models.py                 # RawRecord, ProvenanceRecord, FieldValue, CanonicalCandidate, CandidateProjection
│   ├── normalization.py          # per-field normalizers
│   ├── validation.py             # field-level + cross-field validators
│   ├── identity.py                # deterministic identity resolution (hierarchy + composite score)
│   ├── merge.py                   # deterministic merge engine + conflict tracking
│   ├── confidence.py              # evidence-based confidence engine
│   ├── projection.py              # canonical -> output schema + schema validation
│   ├── cache.py                   # file-based GitHub API cache (TTL)
│   ├── pipeline.py                # orchestration, ThreadPoolExecutor parallel fetch
│   ├── connectors/
│   │   ├── base.py                     # SourceConnector ABC — subclass to add a new source
│   │   ├── structured_connector.py     # CSV / ATS JSON
│   │   ├── resume_connector.py         # PDF / TXT resume, regex extraction
│   │   ├── notes_connector.py          # recruiter notes (.txt)
│   │   └── github_connector.py         # GitHub REST API + caching
│   └── reports/
│       ├── quality.py              # Data Quality Report
│       ├── metrics.py              # Metrics Report / MetricsCollector
│       └── html_report.py          # HTML Explainability Report
├── tests/                        # 40 unit tests, `python3 -m unittest discover -s tests`
├── sample_data/                  # example CSV / resume / notes / batch manifest
├── docs/DESIGN.md                # full architecture discussion (read this for "why")
├── cache_dir/                    # GitHub API cache lives here (auto-created)
└── output/                       # default output directory (auto-created)
```

---

## Setup

Requires **Python 3.9+**.

```bash
cd candidate_transformer
python3 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

Dependencies are intentionally minimal: `pyyaml` (config), `pypdf` (PDF resume
text extraction), `requests` (GitHub API). No pydantic, no web framework, no
database — this is a standalone CLI tool by design.

---

## Usage

### Transform a single candidate

```bash
python3 cli.py transform \
  --csv sample_data/candidate1.csv \
  --resume sample_data/candidate1_resume.txt \
  --notes sample_data/candidate1_notes.txt \
  --github-username janedoe-dev \
  --out output
```

Any of `--csv`/`--json-source`, `--resume`, `--notes`, `--github-username` can be
omitted — the pipeline works with however many sources you actually have. Use
`--json-source path.json` instead of `--csv` for an ATS-style JSON structured
source.

This writes five files per candidate into `--out` (default `output/`):

| File | Contents |
|---|---|
| `<id>.projection.json` | Final flat candidate profile + confidence scores (the main deliverable) |
| `<id>.canonical.json` | Full internal model: every field's complete evidence/provenance trail |
| `<id>.quality.json` | Data Quality Report |
| `<id>.metrics.json` | Metrics Report for this run |
| `<id>.report.html` | HTML Explainability Report — open this in a browser |

### Validate sources without merging

```bash
python3 cli.py validate --csv sample_data/candidate2.csv --resume sample_data/candidate2_resume.txt --notes sample_data/candidate2_notes.txt
```

Fetches and runs normalization + field-level validation only, printing OK/INVALID
per field per source — useful for checking input data quality before committing
to a full transform. Exit code is non-zero if any field failed validation.

### Batch mode

```bash
python3 cli.py batch --manifest sample_data/batch_manifest.json --out output
```

`--manifest` is a JSON list, each entry taking the same keys as the `transform`
flags (`csv`/`json_source`, `resume`, `notes`, `github_username`). See
`sample_data/batch_manifest.json` for an example. Writes per-candidate outputs
plus one `batch.metrics.json` aggregate.

### Running tests

```bash
python3 -m unittest discover -s tests -v
```

### Determinism check (manual, documented in DESIGN.md §12)

Running `transform` twice on the same inputs produces byte-identical
`projection.json` output (aside from the metrics file, which naturally records
different run timestamps) — there is no source of randomness anywhere in
identity resolution, merge, or confidence scoring.

---

## Configuration

Edit `config.yaml` to change behavior without touching code:

```yaml
source_trust:
  structured: 0.95
  github: 0.85
  resume: 0.65
  notes: 0.40

source_precedence: [structured, github, resume, notes]

confidence_weights:
  validation_pass: 0.30
  corroboration: 0.30
  source_trust: 0.20
  completeness: 0.10
  freshness: 0.10

conflict_penalty: 0.15
github_cache_ttl_seconds: 86400
identity_strategy: hierarchy   # or "composite_score"
```

Pass a different file with `--config path/to/other.yaml` on any CLI command.

---

## GitHub Connector — In Detail

File: `src/connectors/github_connector.py`, backed by `src/cache.py`.

### What it does

Calls the public GitHub REST API (`GET https://api.github.com/users/{username}`)
to enrich a candidate profile with: display name, location, bio, public repo
count, follower count, and current company (all fields GitHub exposes on a
public profile). This is an **optional** source — a candidate transform never
fails just because GitHub enrichment is unavailable.

### Caching strategy — why and how

**Why file-based, not in-memory:** the CLI is a short-lived process — one run
transforms one candidate or one batch, then exits. An in-memory cache would be
empty on every invocation and would never actually save an API call. A
file-based cache (`cache_dir/github_<username>.json`) persists *across* CLI
invocations, so it actually reduces calls in the realistic use case: re-running
a transform after fixing a typo in a CSV, or batch-processing many candidates
who happen to share a GitHub org/username.

**Read path** (`GithubConnector.fetch()`):
1. Check `GithubCache.get(username)`.
2. **Cache hit** (entry exists and is younger than `github_cache_ttl_seconds`,
   default 24h) → return the cached JSON immediately. Zero network calls. The
   resulting field's `extraction_method` provenance is tagged
   `"github.rest.v3+cache"` so you can see in the HTML/canonical report exactly
   whether a value came from a live call or the cache.
3. **Cache miss or expired** → perform a real HTTPS GET with an 8-second timeout
   (`github_request_timeout` in config), then `GithubCache.set(username, data)`
   writes the fresh response to disk before returning it — so the *next* run
   (or the next candidate in the same batch sharing that username) becomes a
   cache hit.

**Write path** (`GithubCache.set`): writes to a `.tmp` file first, then
`os.replace()`s it into place — an atomic rename on POSIX systems, which avoids
ever leaving a half-written, corrupt cache file if the process is killed
mid-write. `GithubCache.get` also treats a JSON-decode failure on a cache file as
a plain cache miss (not a crash) — a corrupted cache entry just gets silently
re-fetched and overwritten, it never blocks the pipeline.

**TTL enforcement is on read, not via background eviction:** there's no cron job
or cleanup thread; an entry that's past its TTL is simply treated as absent the
next time it's read, and gets overwritten on the next successful fetch. This
keeps the cache correct with zero moving parts.

### Failure handling / rate limits

The connector is deliberately generous about failure — an optional enrichment
source should never take down the whole transform:

- **Network errors / timeouts** (`requests.RequestException`) → logged to
  stderr, `fetch()` returns `None`, pipeline proceeds without GitHub data for
  that field set.
- **404** (no such user) → logged, `None` returned.
- **403 with `X-RateLimit-Remaining: 0`** → specifically detected (not treated as
  a generic error) — the connector reads the `X-RateLimit-Reset` header and logs
  a human-readable local time for when the limit resets. This is exactly the
  scenario the cache exists to reduce: once a username has been successfully
  fetched once, subsequent runs (within the TTL) don't touch the API at all,
  so rate limits are hit far less often in repeated/batch usage.
- **Any other non-200 status** → logged with the status code, `None` returned.

### Extending it

The unauthenticated GitHub REST API has a low rate limit (60 req/hour per IP).
To support authenticated requests (5,000 req/hour), add an `Authorization:
Bearer <token>` header in `_fetch_live()`, reading the token from an environment
variable — this is a small, isolated change that doesn't touch caching or any
other part of the pipeline, since caching, retry, and provenance tagging are all
already handled generically above the actual HTTP call.

---

## Design highlights (see `docs/DESIGN.md` for full reasoning)

- **Deterministic identity resolution**, no fuzzy name matching: explicit ID →
  email → phone → GitHub username → unresolved (stable synthetic ID). A second
  "composite deterministic score" strategy is also implemented and selectable
  via config, but hierarchy is the recommended default.
- **Deterministic, evidence-based confidence scoring** — not a weighted
  average. Combines five independently-derived signals (validation pass,
  cross-source corroboration, source trust, completeness, freshness) additively,
  then subtracts a conflict penalty. No ML, no statistics, no learned
  parameters. See DESIGN.md §4 for why this is structurally different from a
  weighted average, not a cosmetic variant of one.
- **Nothing is silently overwritten on merge** — every source's contribution to
  every field is retained as evidence, whether it won or lost.
- **Separate internal (`CanonicalCandidate`) and output (`CandidateProjection`)
  models** — output schema can evolve independently of internal representation.
- **`ThreadPoolExecutor` for parallel, I/O-bound source fetching**, with a hard
  synchronization point (`as_completed()` fully drained) before merge — this is
  what keeps the pipeline deterministic despite fetching sources concurrently.
