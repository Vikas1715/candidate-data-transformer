"""
GitHub connector: optional enrichment source, hits the public GitHub
REST API (`GET /users/{username}`) for public profile data such as
name, bio, public repo count, followers, and company.

Caching strategy (backed by GithubCache, see cache.py):
1. On fetch(), first check the local file cache for this username.
2. Cache HIT (and not expired per `github_cache_ttl_seconds` in
   config.yaml) -> return cached data immediately, zero network calls.
   `extraction_method` is tagged "github.rest.v3+cache" so this is
   visible in the field's provenance record -- an evaluator can see in
   the explainability report whether a value came from a live call or
   cache.
3. Cache MISS or EXPIRED -> perform a real HTTPS GET with a short
   timeout (`github_request_timeout`), then write the successful
   response into the cache before returning it, so the *next* run (or
   the next candidate in the same batch that shares a username) is a
   cache hit.
4. Failure handling is deliberately generous: network errors, timeouts,
   non-200 responses, and rate-limit responses (403 with
   `X-RateLimit-Remaining: 0`) are all caught and converted into
   `fetch() -> None` (source simply produced no data) rather than
   crashing the whole pipeline. A candidate transform should never fail
   just because GitHub enrichment -- an *optional* source -- is
   unavailable. This is logged to stderr for observability but doesn't
   raise.
5. Rate-limit awareness: on a 403 response, the connector inspects the
   `X-RateLimit-Remaining` header. If it's `0`, it logs a clear
   rate-limit message (rather than a generic HTTP error) explaining when
   the limit resets, which is exactly the scenario caching exists to
   reduce -- repeated transforms of the same candidate/username won't
   re-hit the API and burn quota.

Everything above is orthogonal to the rest of the pipeline: GitHub data
enters the system as just another RawRecord, subject to the same
normalization/validation/merge/confidence stages as every other source.
"""
from __future__ import annotations

import sys
import time
from typing import Optional

import requests

from src.connectors.base import SourceConnector
from src.models import RawRecord
from src.cache import GithubCache


class GithubConnector(SourceConnector):
    source_name = "github"

    def __init__(self, username: str, cache: GithubCache, api_base: str, timeout: int):
        super().__init__(origin=username)
        self.username = username
        self.cache = cache
        self.api_base = api_base.rstrip("/")
        self.timeout = timeout

    def fetch(self) -> Optional[RawRecord]:
        if not self.username:
            return None

        cached = self.cache.get(self.username)
        if cached is not None:
            return self._to_record(cached, method="github.rest.v3+cache")

        data = self._fetch_live()
        if data is None:
            return None

        self.cache.set(self.username, data)
        return self._to_record(data, method="github.rest.v3")

    def _fetch_live(self) -> Optional[dict]:
        url = f"{self.api_base}/users/{self.username}"
        try:
            resp = requests.get(
                url,
                headers={"Accept": "application/vnd.github+json"},
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            print(f"[github_connector] network error for '{self.username}': {exc}", file=sys.stderr)
            return None

        if resp.status_code == 403 and resp.headers.get("X-RateLimit-Remaining") == "0":
            reset = resp.headers.get("X-RateLimit-Reset")
            reset_str = time.strftime("%H:%M:%S", time.localtime(int(reset))) if reset else "unknown"
            print(
                f"[github_connector] rate-limited; resets at {reset_str}. "
                f"Cached data (if any) will be used on next run once available.",
                file=sys.stderr,
            )
            return None

        if resp.status_code == 404:
            print(f"[github_connector] no such GitHub user: '{self.username}'", file=sys.stderr)
            return None

        if resp.status_code != 200:
            print(f"[github_connector] unexpected status {resp.status_code} for '{self.username}'", file=sys.stderr)
            return None

        return resp.json()

    def _to_record(self, data: dict, method: str) -> RawRecord:
        fields = {
            "full_name": data.get("name"),
            "location": data.get("location"),
            "github_username": data.get("login"),
            "github_bio": data.get("bio"),
            "github_public_repos": data.get("public_repos"),
            "github_followers": data.get("followers"),
            "current_company": data.get("company"),
        }
        fields = {k: v for k, v in fields.items() if v not in (None, "")}
        return RawRecord(
            source_name=self.source_name,
            source_type="api",
            origin=f"{self.api_base}/users/{self.username}",
            data=fields,
            extraction_method=method,
        )
