"""
Recruiter notes connector (.txt free text). Lowest-trust source: no
structural cues expected at all, so extraction leans even harder on
loose regexes and is expected to corroborate (not lead) other sources.
"""
from __future__ import annotations

import os
import re
from typing import Optional

from src.connectors.base import SourceConnector
from src.models import RawRecord
from src.connectors.resume_connector import EMAIL_RE, PHONE_RE, GITHUB_RE

LOCATION_RE = re.compile(r"(?:based in|located in|location)\s*[:\-]?\s*([A-Za-z ,]+)", re.I)


class NotesConnector(SourceConnector):
    source_name = "notes"

    def fetch(self) -> Optional[RawRecord]:
        if not self.origin or not os.path.exists(self.origin):
            return None
        with open(self.origin, encoding="utf-8") as fh:
            text = fh.read()

        data = {}
        m = EMAIL_RE.search(text)
        if m:
            data["email"] = m.group(0)
        m = PHONE_RE.search(text)
        if m:
            data["phone"] = m.group(1).strip()
        m = GITHUB_RE.search(text)
        if m:
            data["github_username"] = m.group(1)
        m = LOCATION_RE.search(text)
        if m:
            data["location"] = m.group(1).strip().rstrip(".")
        if text.strip():
            data["summary"] = text.strip()[:400]

        return RawRecord(
            source_name=self.source_name,
            source_type="txt",
            origin=self.origin,
            data=data,
            extraction_method="regex:notes_freetext",
        )
