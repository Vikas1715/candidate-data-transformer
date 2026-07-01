"""
Pipeline orchestrator.

Parallelism strategy (see DESIGN.md "Parallel Processing" for full
discussion):
- Fetching each source (CSV read, PDF parse, notes read, GitHub HTTP
  call) is independent, I/O-bound work -> a ThreadPoolExecutor (not
  multiprocessing -- these are I/O waits, not CPU-bound work, so
  threads are the right tool and avoid pickling overhead) fetches all
  sources for one candidate concurrently.
- A hard synchronization point exists before merge: `as_completed()` is
  fully drained so identity resolution and merging only ever see a
  complete, consistent set of source results for one candidate. This
  is what keeps output deterministic -- merge never races against a
  still-in-flight fetch.
- For BATCH runs (many candidates), the same executor pattern applies
  one level up: candidates are independent of each other, so a batch
  can also be parallelized across candidates. This implementation
  parallelizes within a candidate (source fetch) by default; batch
  mode reuses `run_single_candidate` sequentially per candidate for
  simplicity, but this loop is trivially parallelizable to a
  process/worker pool since candidates share no state -- exactly what
  makes it "queue-ready" per the Scalability discussion.
"""
from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Optional

from src.config import Config
from src.models import CanonicalCandidate, RawRecord, CANONICAL_FIELDS
from src.connectors.structured_connector import StructuredConnector
from src.connectors.resume_connector import ResumeConnector
from src.connectors.notes_connector import NotesConnector
from src.connectors.github_connector import GithubConnector
from src.cache import GithubCache
from src.identity import resolve_identity
from src.merge import merge_all_fields
from src.confidence import score_all
from src.projection import project, validate_projection_schema
from src.reports.quality import build_quality_report
from src.reports.metrics import MetricsCollector
from src.reports.html_report import build_html_report


class CandidateSources:
    def __init__(self, structured: Optional[str] = None, resume: Optional[str] = None,
                 notes: Optional[str] = None, github_username: Optional[str] = None):
        self.structured = structured
        self.resume = resume
        self.notes = notes
        self.github_username = github_username


def _fetch_one(connector) -> Optional[RawRecord]:
    return connector.fetch()


def fetch_all_sources(
    sources: CandidateSources,
    config: Config,
    cache_dir: str,
    metrics: MetricsCollector,
) -> List[RawRecord]:
    """Fetches every configured source in parallel (ThreadPoolExecutor),
    synchronizes fully before returning."""
    connectors = []
    if sources.structured:
        connectors.append(StructuredConnector(sources.structured))
    if sources.resume:
        connectors.append(ResumeConnector(sources.resume))
    if sources.notes:
        connectors.append(NotesConnector(sources.notes))
    if sources.github_username:
        cache = GithubCache(cache_dir, config.github_cache_ttl_seconds)
        had_cache_before = cache.get(sources.github_username) is not None
        connectors.append(GithubConnector(
            sources.github_username, cache, config.github_api_base, config.github_request_timeout
        ))
        if had_cache_before:
            metrics.github_cache_hits += 1
        else:
            metrics.github_cache_misses += 1

    records: List[RawRecord] = []
    metrics.start_stage("fetch_sources")
    if connectors:
        with ThreadPoolExecutor(max_workers=max(1, len(connectors))) as executor:
            future_map = {executor.submit(_fetch_one, c): c for c in connectors}
            # Synchronization point: drain every future before proceeding.
            for future in as_completed(future_map):
                connector = future_map[future]
                try:
                    record = future.result()
                    if record is not None:
                        records.append(record)
                        metrics.record_source_result(success=True)
                        metrics.fields_extracted += len(record.data)
                    else:
                        metrics.record_source_result(success=False)
                except Exception as exc:  # noqa: BLE001 - isolate one bad source
                    metrics.record_source_result(success=False)
                    metrics.record_error(f"{connector.source_name} connector failed: {exc}")
    metrics.end_stage("fetch_sources")
    return records


def run_single_candidate(
    sources: CandidateSources,
    config: Config,
    cache_dir: str,
    metrics: Optional[MetricsCollector] = None,
) -> Dict:
    metrics = metrics or MetricsCollector()

    records = fetch_all_sources(sources, config, cache_dir, metrics)

    metrics.start_stage("identity_resolution")
    sources_raw = {r.source_name: r.data for r in records}
    identity = resolve_identity(sources_raw, strategy=config.identity_strategy)
    metrics.end_stage("identity_resolution")

    metrics.start_stage("merge_and_confidence")
    merged_fields = merge_all_fields(records, config, CANONICAL_FIELDS)
    score_all(merged_fields, config)
    metrics.fields_merged += len(merged_fields)
    metrics.conflicts_detected += sum(1 for fv in merged_fields.values() if fv.conflict)
    metrics.end_stage("merge_and_confidence")

    canonical = CanonicalCandidate(
        fields=merged_fields,
        identity_resolution={
            "candidate_id": identity.candidate_id,
            "strategy": identity.strategy,
            "resolved": identity.resolved,
            "resolution_path": identity.resolution_path,
            "composite_score": identity.composite_score,
        },
        sources_seen=[r.source_name for r in records],
    )

    metrics.start_stage("projection")
    projection = project(canonical)
    schema_errors = validate_projection_schema(projection)
    metrics.end_stage("projection")

    quality = build_quality_report(canonical, identity.candidate_id)

    metrics.candidates_processed += 1
    metrics.files_processed += sum(
        1 for x in (sources.structured, sources.resume, sources.notes) if x
    )

    return {
        "canonical": canonical,
        "projection": projection,
        "quality": quality,
        "schema_errors": schema_errors,
        "metrics": metrics,
    }


def write_outputs(result: Dict, out_dir: str) -> Dict[str, str]:
    os.makedirs(out_dir, exist_ok=True)
    cid = result["projection"].candidate_id.replace("/", "_").replace(":", "_")
    paths = {}

    projection_path = os.path.join(out_dir, f"{cid}.projection.json")
    with open(projection_path, "w", encoding="utf-8") as fh:
        json.dump(result["projection"].to_dict(), fh, indent=2, default=str)
    paths["projection"] = projection_path

    canonical_path = os.path.join(out_dir, f"{cid}.canonical.json")
    with open(canonical_path, "w", encoding="utf-8") as fh:
        json.dump(result["canonical"].to_dict(), fh, indent=2, default=str)
    paths["canonical"] = canonical_path

    quality_path = os.path.join(out_dir, f"{cid}.quality.json")
    with open(quality_path, "w", encoding="utf-8") as fh:
        json.dump(result["quality"].to_dict(), fh, indent=2, default=str)
    paths["quality"] = quality_path

    metrics_path = os.path.join(out_dir, f"{cid}.metrics.json")
    with open(metrics_path, "w", encoding="utf-8") as fh:
        json.dump(result["metrics"].to_dict(), fh, indent=2, default=str)
    paths["metrics"] = metrics_path

    html = build_html_report(result["canonical"], result["projection"], result["quality"])
    html_path = os.path.join(out_dir, f"{cid}.report.html")
    with open(html_path, "w", encoding="utf-8") as fh:
        fh.write(html)
    paths["html_report"] = html_path

    return paths
