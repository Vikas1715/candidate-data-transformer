"""
Configuration loader.

All "tunable" business values (source trust scores, source precedence,
confidence weights, cache TTL, validation regexes that are likely to change)
live in config.yaml instead of being hardcoded across the codebase.

This module loads that file once and exposes a typed, read-only Config object.
Falls back to sane built-in defaults if a key is missing, so the system never
crashes due to a partially-filled config file.
"""
from __future__ import annotations

import os
import yaml
from dataclasses import dataclass, field
from typing import Dict, List


DEFAULT_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "config.yaml")


@dataclass(frozen=True)
class Config:
    # Source trust scores: higher = more authoritative when merging conflicts.
    source_trust: Dict[str, float] = field(default_factory=lambda: {
        "structured": 0.95,
        "github": 0.85,
        "resume": 0.65,
        "notes": 0.40,
    })

    # Deterministic precedence order used as a tie-breaker when trust scores
    # are equal, or when a field is simply missing from the highest-trust
    # source. Earlier entries win.
    source_precedence: List[str] = field(default_factory=lambda: [
        "structured", "github", "resume", "notes"
    ])

    # Weights for the evidence-based confidence model. These are
    # *contributions*, not a weighted-average denominator -- see DESIGN.md.
    confidence_weights: Dict[str, float] = field(default_factory=lambda: {
        "validation_pass": 0.30,
        "corroboration": 0.30,
        "source_trust": 0.20,
        "completeness": 0.10,
        "freshness": 0.10,
    })

    conflict_penalty: float = 0.15          # subtracted per unresolved conflicting source
    min_confidence: float = 0.05
    max_confidence: float = 0.99

    github_cache_ttl_seconds: int = 86400   # 24h
    github_api_base: str = "https://api.github.com"
    github_request_timeout: int = 8

    identity_strategy: str = "hierarchy"    # "hierarchy" | "composite_score"

    @staticmethod
    def load(path: str = DEFAULT_CONFIG_PATH) -> "Config":
        defaults = Config()
        if not os.path.exists(path):
            return defaults
        with open(path, "r", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh) or {}

        return Config(
            source_trust={**defaults.source_trust, **raw.get("source_trust", {})},
            source_precedence=raw.get("source_precedence", defaults.source_precedence),
            confidence_weights={**defaults.confidence_weights, **raw.get("confidence_weights", {})},
            conflict_penalty=raw.get("conflict_penalty", defaults.conflict_penalty),
            min_confidence=raw.get("min_confidence", defaults.min_confidence),
            max_confidence=raw.get("max_confidence", defaults.max_confidence),
            github_cache_ttl_seconds=raw.get("github_cache_ttl_seconds", defaults.github_cache_ttl_seconds),
            github_api_base=raw.get("github_api_base", defaults.github_api_base),
            github_request_timeout=raw.get("github_request_timeout", defaults.github_request_timeout),
            identity_strategy=raw.get("identity_strategy", defaults.identity_strategy),
        )
