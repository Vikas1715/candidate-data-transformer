"""
Metrics Report: observability for a pipeline run. A MetricsCollector is
threaded through pipeline.py, updated at each stage boundary, and
serialized to JSON at the end alongside the candidate output(s).

Kept intentionally dependency-free (no APM/tracing library) since the
CLI is meant to run standalone -- but the schema below is stable enough
to be piped into a real metrics system later (e.g. by shipping the JSON
file to a log collector) without changing the pipeline.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class MetricsCollector:
    started_at: float = field(default_factory=time.perf_counter)
    stage_durations_seconds: Dict[str, float] = field(default_factory=dict)
    files_processed: int = 0
    sources_attempted: int = 0
    sources_succeeded: int = 0
    sources_failed: int = 0
    fields_extracted: int = 0
    conflicts_detected: int = 0
    fields_merged: int = 0
    candidates_processed: int = 0
    github_cache_hits: int = 0
    github_cache_misses: int = 0
    errors: List[str] = field(default_factory=list)
    _stage_start: Dict[str, float] = field(default_factory=dict, repr=False)

    def start_stage(self, name: str) -> None:
        self._stage_start[name] = time.perf_counter()

    def end_stage(self, name: str) -> None:
        if name in self._stage_start:
            self.stage_durations_seconds[name] = round(
                time.perf_counter() - self._stage_start[name], 6
            )

    def record_source_result(self, success: bool) -> None:
        self.sources_attempted += 1
        if success:
            self.sources_succeeded += 1
        else:
            self.sources_failed += 1

    def record_error(self, message: str) -> None:
        self.errors.append(message)

    def total_elapsed_seconds(self) -> float:
        return round(time.perf_counter() - self.started_at, 6)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_elapsed_seconds": self.total_elapsed_seconds(),
            "stage_durations_seconds": self.stage_durations_seconds,
            "candidates_processed": self.candidates_processed,
            "files_processed": self.files_processed,
            "sources": {
                "attempted": self.sources_attempted,
                "succeeded": self.sources_succeeded,
                "failed": self.sources_failed,
            },
            "fields_extracted": self.fields_extracted,
            "fields_merged": self.fields_merged,
            "conflicts_detected": self.conflicts_detected,
            "github_cache": {
                "hits": self.github_cache_hits,
                "misses": self.github_cache_misses,
            },
            "errors": self.errors,
        }
