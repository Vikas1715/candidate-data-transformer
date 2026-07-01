"""
GithubCache: a small, dependency-free, file-based cache for GitHub API
responses.

Why file-based and not in-memory:
- The CLI is a short-lived process (one run = one or a handful of
  candidates). An in-memory cache would be useless -- it would be empty
  every time the process starts. A file-based cache is what actually
  saves API calls across *separate* CLI invocations (e.g. re-running a
  batch after fixing a CSV typo, or transforming several candidates that
  happen to share a GitHub username).
- It requires no external service (no Redis, no DB) so the project stays
  "single machine, zero infra" as required for the current scope, while
  still being a drop-in interface that could be swapped for a real
  cache/queue-backed store later (see DESIGN.md, Scalability).

Cache entry format (one JSON file per username, keyed by a sanitized
filename): {"fetched_at": <epoch seconds>, "data": {...raw github json...}}

TTL is enforced on read: an expired entry is treated as a cache miss so
the connector re-fetches and overwrites it. This keeps cache invalidation
trivial and correct without a background eviction process.
"""
from __future__ import annotations

import json
import os
import re
import time
from typing import Any, Optional

_SAFE_RE = re.compile(r"[^A-Za-z0-9_\-.]")


class GithubCache:
    def __init__(self, cache_dir: str, ttl_seconds: int):
        self.cache_dir = cache_dir
        self.ttl_seconds = ttl_seconds
        os.makedirs(self.cache_dir, exist_ok=True)

    def _path_for(self, username: str) -> str:
        safe = _SAFE_RE.sub("_", username.lower())
        return os.path.join(self.cache_dir, f"github_{safe}.json")

    def get(self, username: str) -> Optional[dict]:
        path = self._path_for(username)
        if not os.path.exists(path):
            return None
        try:
            with open(path, encoding="utf-8") as fh:
                entry = json.load(fh)
        except (json.JSONDecodeError, OSError):
            return None  # corrupt cache entry -> treat as miss, will be overwritten

        age = time.time() - entry.get("fetched_at", 0)
        if age > self.ttl_seconds:
            return None  # expired -> miss
        return entry.get("data")

    def set(self, username: str, data: Any) -> None:
        path = self._path_for(username)
        entry = {"fetched_at": time.time(), "data": data}
        tmp_path = path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as fh:
            json.dump(entry, fh, indent=2)
        os.replace(tmp_path, path)  # atomic on POSIX, avoids torn writes

    def stat(self, username: str) -> Optional[dict]:
        """Returns cache metadata (hit/age) without touching TTL logic, for metrics."""
        path = self._path_for(username)
        if not os.path.exists(path):
            return None
        with open(path, encoding="utf-8") as fh:
            entry = json.load(fh)
        return {"fetched_at": entry.get("fetched_at"), "age_seconds": time.time() - entry.get("fetched_at", 0)}
