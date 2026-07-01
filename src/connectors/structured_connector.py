"""
Structured source connector: CSV or ATS-style JSON.
This is the highest-trust source (system of record), so its extraction
method is a straight structural read -- no free-text parsing, no
ambiguity.
"""
from __future__ import annotations

import csv
import json
import os
from typing import Optional

from src.connectors.base import SourceConnector
from src.models import RawRecord


class StructuredConnector(SourceConnector):
    source_name = "structured"

    def fetch(self) -> Optional[RawRecord]:
        if not self.origin or not os.path.exists(self.origin):
            return None

        ext = os.path.splitext(self.origin)[1].lower()
        if ext == ".csv":
            return self._fetch_csv()
        elif ext == ".json":
            return self._fetch_json()
        else:
            raise ValueError(f"Unsupported structured source extension: {ext}")

    def _fetch_csv(self) -> RawRecord:
        with open(self.origin, newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            row = next(reader, None)
        data = dict(row) if row else {}
        return RawRecord(
            source_name=self.source_name,
            source_type="csv",
            origin=self.origin,
            data=data,
            extraction_method="csv.DictReader",
        )

    def _fetch_json(self) -> RawRecord:
        with open(self.origin, encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, list):
            data = data[0] if data else {}
        return RawRecord(
            source_name=self.source_name,
            source_type="json",
            origin=self.origin,
            data=data,
            extraction_method="json.load",
        )
