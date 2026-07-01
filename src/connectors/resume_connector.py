"""
Resume connector: PDF (or .txt for easy local testing without a real PDF).

Extraction method is deterministic regex-based free-text parsing -- this
is intentionally simple and auditable rather than ML-based, because the
assignment requires the *pipeline's* identity/merge/confidence logic to
stay deterministic. (Optional AI enrichment, if enabled, only ever adds
extra candidate fields for the confidence engine to score -- it never
performs identity resolution, merging, or confidence scoring itself.)
"""
from __future__ import annotations

import os
import re
from typing import Optional

from src.connectors.base import SourceConnector
from src.models import RawRecord

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
PHONE_RE = re.compile(r"(\+?\d[\d\-\s()]{8,}\d)")
YEARS_RE = re.compile(r"(\d+(?:\.\d+)?)\+?\s*years?\s+(?:of\s+)?experience", re.I)
TITLE_RE = re.compile(r"^(?:Title|Current Title|Role)\s*[:\-]\s*(.+)$", re.I | re.M)
COMPANY_RE = re.compile(r"^(?:Company|Current Company|Employer)\s*[:\-]\s*(.+)$", re.I | re.M)
NAME_RE = re.compile(r"^(?:Name)\s*[:\-]\s*(.+)$", re.I | re.M)
SKILLS_RE = re.compile(r"^(?:Skills)\s*[:\-]\s*(.+)$", re.I | re.M)
EDU_RE = re.compile(r"^(?:Education)\s*[:\-]\s*(.+)$", re.I | re.M)
GITHUB_RE = re.compile(r"github\.com/([A-Za-z0-9\-]+)", re.I)


class ResumeConnector(SourceConnector):
    source_name = "resume"

    def fetch(self) -> Optional[RawRecord]:
        if not self.origin or not os.path.exists(self.origin):
            return None

        ext = os.path.splitext(self.origin)[1].lower()
        if ext == ".pdf":
            text = self._extract_pdf_text()
            method = "pypdf.extract_text"
        elif ext == ".txt":
            with open(self.origin, encoding="utf-8") as fh:
                text = fh.read()
            method = "plaintext.read"
        else:
            raise ValueError(f"Unsupported resume extension: {ext}")

        data = self._extract_fields(text)
        return RawRecord(
            source_name=self.source_name,
            source_type="pdf" if ext == ".pdf" else "txt",
            origin=self.origin,
            data=data,
            extraction_method=f"regex:{method}",
        )

    def _extract_pdf_text(self) -> str:
        try:
            from pypdf import PdfReader
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "pypdf is required to parse PDF resumes. pip install pypdf"
            ) from exc
        reader = PdfReader(self.origin)
        return "\n".join(page.extract_text() or "" for page in reader.pages)

    @staticmethod
    def _extract_fields(text: str) -> dict:
        data = {}

        def first(pattern, cast=lambda x: x.strip()):
            m = pattern.search(text)
            return cast(m.group(1)) if m else None

        data["full_name"] = first(NAME_RE)
        m_email = EMAIL_RE.search(text)
        data["email"] = m_email.group(0) if m_email else None
        m_phone = PHONE_RE.search(text)
        data["phone"] = m_phone.group(1).strip() if m_phone else None
        data["current_title"] = first(TITLE_RE)
        data["current_company"] = first(COMPANY_RE)
        years = YEARS_RE.search(text)
        data["years_experience"] = float(years.group(1)) if years else None
        skills_line = first(SKILLS_RE)
        data["skills"] = [s.strip() for s in skills_line.split(",")] if skills_line else None
        edu_line = first(EDU_RE)
        data["education"] = [s.strip() for s in edu_line.split(";")] if edu_line else None
        gh = GITHUB_RE.search(text)
        data["github_username"] = gh.group(1) if gh else None
        data["summary"] = text.strip()[:400] or None

        return {k: v for k, v in data.items() if v not in (None, "", [])}
