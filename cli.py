#!/usr/bin/env python3
"""
Multi-Source Candidate Data Transformer -- CLI (primary interface).

Commands:
  transform   Transform one candidate's sources into a canonical profile
              + projection JSON + quality report + metrics report + HTML
              explainability report.
  validate    Run only fetch + validation for a candidate's sources and
              print field-level validation results (no merge/output
              files written) -- useful for checking input data quality
              before a real transform.
  batch       Transform every candidate described in a batch manifest
              JSON (list of the same args `transform` takes).

Run `python cli.py <command> --help` for per-command options.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.config import Config
from src.pipeline import CandidateSources, run_single_candidate, write_outputs, fetch_all_sources
from src.reports.metrics import MetricsCollector


def cmd_transform(args: argparse.Namespace) -> int:
    config = Config.load(args.config)
    sources = CandidateSources(
        structured=args.csv or args.json_source,
        resume=args.resume,
        notes=args.notes,
        github_username=args.github_username,
    )
    result = run_single_candidate(sources, config, cache_dir=args.cache_dir)
    paths = write_outputs(result, args.out)

    print(f"Candidate ID:      {result['projection'].candidate_id}")
    print(f"Overall confidence: {result['projection'].overall_confidence:.2f}")
    print(f"Quality score:      {result['quality'].overall_quality_score:.1f}/100")
    if result["schema_errors"]:
        print("Schema validation errors:", result["schema_errors"], file=sys.stderr)
    print("\nOutputs written:")
    for label, path in paths.items():
        print(f"  {label:12s} -> {path}")

    if args.verbose:
        print("\n--- Metrics ---")
        print(json.dumps(result["metrics"].to_dict(), indent=2))

    return 0 if not result["schema_errors"] else 2


def cmd_validate(args: argparse.Namespace) -> int:
    config = Config.load(args.config)
    sources = CandidateSources(
        structured=args.csv or args.json_source,
        resume=args.resume,
        notes=args.notes,
        github_username=args.github_username,
    )
    metrics = MetricsCollector()
    records = fetch_all_sources(sources, config, cache_dir=args.cache_dir, metrics=metrics)

    from src.normalization import normalize_field
    from src.validation import validate_field

    if not records:
        print("No sources produced any data.")
        return 1

    any_invalid = False
    for rec in records:
        print(f"\n=== Source: {rec.source_name} ({rec.origin}) ===")
        for field_name, raw_value in rec.data.items():
            normalized = normalize_field(field_name, raw_value)
            result = validate_field(field_name, normalized)
            status = "OK" if result.valid else "INVALID"
            if not result.valid:
                any_invalid = True
            notes = f" ({'; '.join(result.notes)})" if result.notes else ""
            print(f"  [{status:7s}] {field_name}: {raw_value!r} -> {normalized!r}{notes}")

    return 1 if any_invalid else 0


def cmd_batch(args: argparse.Namespace) -> int:
    config = Config.load(args.config)
    with open(args.manifest, encoding="utf-8") as fh:
        manifest = json.load(fh)

    overall_metrics = MetricsCollector()
    exit_code = 0
    for i, entry in enumerate(manifest):
        sources = CandidateSources(
            structured=entry.get("csv") or entry.get("json_source"),
            resume=entry.get("resume"),
            notes=entry.get("notes"),
            github_username=entry.get("github_username"),
        )
        try:
            result = run_single_candidate(sources, config, cache_dir=args.cache_dir)
            paths = write_outputs(result, args.out)
            overall_metrics.candidates_processed += 1
            print(f"[{i+1}/{len(manifest)}] {result['projection'].candidate_id}: "
                  f"confidence={result['projection'].overall_confidence:.2f} "
                  f"quality={result['quality'].overall_quality_score:.1f} -> {paths['projection']}")
            if result["schema_errors"]:
                exit_code = 2
        except Exception as exc:  # noqa: BLE001
            overall_metrics.record_error(f"candidate[{i}] failed: {exc}")
            print(f"[{i+1}/{len(manifest)}] FAILED: {exc}", file=sys.stderr)
            exit_code = 1

    batch_metrics_path = os.path.join(args.out, "batch.metrics.json")
    os.makedirs(args.out, exist_ok=True)
    with open(batch_metrics_path, "w", encoding="utf-8") as fh:
        json.dump(overall_metrics.to_dict(), fh, indent=2)
    print(f"\nBatch metrics -> {batch_metrics_path}")
    return exit_code


def _add_source_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--csv", help="Path to structured CSV source")
    p.add_argument("--json-source", dest="json_source", help="Path to structured ATS-style JSON source")
    p.add_argument("--resume", help="Path to resume file (.pdf or .txt)")
    p.add_argument("--notes", help="Path to recruiter notes .txt file")
    p.add_argument("--github-username", help="GitHub username for API enrichment")
    p.add_argument("--config", default=os.path.join(os.path.dirname(__file__), "config.yaml"),
                    help="Path to config.yaml")
    p.add_argument("--cache-dir", default=os.path.join(os.path.dirname(__file__), "cache_dir"),
                    help="Directory for the GitHub API cache")


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="cli.py",
        description="Multi-Source Candidate Data Transformer",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_transform = sub.add_parser("transform", help="Transform one candidate's sources")
    _add_source_args(p_transform)
    p_transform.add_argument("--out", default="output", help="Output directory")
    p_transform.add_argument("--verbose", action="store_true")
    p_transform.set_defaults(func=cmd_transform)

    p_validate = sub.add_parser("validate", help="Validate one candidate's sources without merging")
    _add_source_args(p_validate)
    p_validate.set_defaults(func=cmd_validate)

    p_batch = sub.add_parser("batch", help="Transform every candidate in a manifest JSON")
    p_batch.add_argument("--manifest", required=True, help="Path to batch manifest JSON (list of source specs)")
    p_batch.add_argument("--config", default=os.path.join(os.path.dirname(__file__), "config.yaml"))
    p_batch.add_argument("--cache-dir", default=os.path.join(os.path.dirname(__file__), "cache_dir"))
    p_batch.add_argument("--out", default="output")
    p_batch.set_defaults(func=cmd_batch)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
