"""
HTML Explainability Report: browser-friendly rendering of the final
projection + full per-field evidence/confidence/conflicts, as an
alternative to reading raw JSON. Uses plain string templates (no
Jinja2 dependency) to keep the project's dependency footprint small.

All dynamic content is HTML-escaped to keep this safe to open even
when source data (resume/notes free text) is untrusted user input.
"""
from __future__ import annotations

from html import escape
from typing import Any

from src.models import CanonicalCandidate, CandidateProjection
from src.reports.quality import DataQualityReport


def _esc(value: Any) -> str:
    return escape(str(value)) if value is not None else "<span class='muted'>—</span>"


def _confidence_badge(conf: float) -> str:
    if conf >= 0.75:
        cls = "conf-high"
    elif conf >= 0.45:
        cls = "conf-mid"
    else:
        cls = "conf-low"
    return f"<span class='badge {cls}'>{conf:.2f}</span>"


def _evidence_rows(fv) -> str:
    rows = []
    for e in fv.evidence:
        valid_icon = "✅" if e.valid else "❌"
        rows.append(
            f"<tr><td>{_esc(e.source)}</td><td>{_esc(e.extraction_method)}</td>"
            f"<td>{_esc(e.raw_value)}</td><td>{_esc(e.normalized_value)}</td>"
            f"<td>{valid_icon}</td><td>{_esc('; '.join(e.validation_notes))}</td></tr>"
        )
    return "".join(rows)


def _field_section(name: str, fv) -> str:
    conflict_html = ""
    if fv.conflict:
        conflict_html = (
            f"<div class='conflict-box'>⚠ Conflict: winning value "
            f"<code>{_esc(fv.value)}</code> from <b>{_esc(fv.winning_source)}</b> vs "
            f"other value(s): {_esc(', '.join(str(v) for v in fv.conflicting_values))}</div>"
        )
    return f"""
    <div class="field-card">
      <div class="field-header">
        <h3>{_esc(name)}</h3>
        {_confidence_badge(fv.confidence)}
      </div>
      <div class="field-value">{_esc(fv.value)} <span class="muted">(source: {_esc(fv.winning_source)})</span></div>
      {conflict_html}
      <table class="evidence-table">
        <thead><tr><th>Source</th><th>Method</th><th>Raw</th><th>Normalized</th><th>Valid</th><th>Notes</th></tr></thead>
        <tbody>{_evidence_rows(fv)}</tbody>
      </table>
    </div>
    """


def build_html_report(
    canonical: CanonicalCandidate,
    projection: CandidateProjection,
    quality: DataQualityReport,
) -> str:
    field_sections = "".join(
        _field_section(name, fv) for name, fv in sorted(canonical.fields.items())
    )

    warnings_html = "".join(f"<li>{_esc(w)}</li>" for w in quality.cross_field_warnings) or "<li class='muted'>None</li>"
    missing_html = "".join(f"<li>{_esc(m)}</li>" for m in quality.missing_fields) or "<li class='muted'>None</li>"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Candidate Explainability Report — {_esc(projection.candidate_id)}</title>
<style>
  :root {{ --high:#1a7f37; --mid:#9a6700; --low:#cf222e; --bg:#f6f8fa; --card:#fff; --border:#d0d7de; }}
  body {{ font-family: -apple-system, Segoe UI, Roboto, sans-serif; background:var(--bg); color:#1f2328; margin:0; padding:2rem; }}
  h1 {{ margin-bottom:0.2rem; }}
  .muted {{ color:#6e7781; }}
  .summary-grid {{ display:grid; grid-template-columns: repeat(auto-fit, minmax(180px,1fr)); gap:1rem; margin:1.5rem 0; }}
  .stat-card {{ background:var(--card); border:1px solid var(--border); border-radius:8px; padding:1rem; }}
  .stat-card .num {{ font-size:1.8rem; font-weight:700; }}
  .badge {{ display:inline-block; padding:0.15rem 0.55rem; border-radius:999px; font-weight:600; font-size:0.85rem; color:#fff; }}
  .conf-high {{ background:var(--high); }}
  .conf-mid {{ background:var(--mid); }}
  .conf-low {{ background:var(--low); }}
  .field-card {{ background:var(--card); border:1px solid var(--border); border-radius:8px; padding:1rem 1.25rem; margin-bottom:1rem; }}
  .field-header {{ display:flex; align-items:center; justify-content:space-between; }}
  .field-header h3 {{ margin:0; text-transform:capitalize; }}
  .field-value {{ font-size:1.1rem; margin:0.4rem 0 0.7rem; }}
  .conflict-box {{ background:#fff8c5; border:1px solid #d4a72c; border-radius:6px; padding:0.5rem 0.75rem; margin-bottom:0.6rem; font-size:0.9rem; }}
  table.evidence-table {{ width:100%; border-collapse:collapse; font-size:0.85rem; }}
  table.evidence-table th, table.evidence-table td {{ border-bottom:1px solid var(--border); padding:0.4rem 0.5rem; text-align:left; }}
  table.evidence-table th {{ color:#6e7781; font-weight:600; }}
  section {{ margin-bottom:2rem; }}
  .two-col {{ display:grid; grid-template-columns:1fr 1fr; gap:1.5rem; }}
  ul {{ margin:0; padding-left:1.2rem; }}
</style>
</head>
<body>
  <h1>Candidate Explainability Report</h1>
  <div class="muted">candidate_id: {_esc(projection.candidate_id)}</div>

  <div class="summary-grid">
    <div class="stat-card"><div class="muted">Overall Confidence</div><div class="num">{projection.overall_confidence:.2f}</div></div>
    <div class="stat-card"><div class="muted">Data Quality Score</div><div class="num">{quality.overall_quality_score:.1f}/100</div></div>
    <div class="stat-card"><div class="muted">Fields Populated</div><div class="num">{len(canonical.fields)}</div></div>
    <div class="stat-card"><div class="muted">Conflicts Detected</div><div class="num">{len(quality.conflicting_fields)}</div></div>
  </div>

  <section class="two-col">
    <div>
      <h2>Missing Fields</h2>
      <ul>{missing_html}</ul>
    </div>
    <div>
      <h2>Cross-Field Warnings</h2>
      <ul>{warnings_html}</ul>
    </div>
  </section>

  <section>
    <h2>Field-by-Field Evidence</h2>
    {field_sections}
  </section>
</body>
</html>"""
