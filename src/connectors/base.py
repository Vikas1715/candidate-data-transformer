"""
Connector base class.

Adding a NEW data source (DOCX, XML, LinkedIn-shaped JSON, another API)
only requires subclassing SourceConnector and implementing `fetch()` --
nothing else in the pipeline changes. This satisfies the "plugin-based,
easy to extend" requirement without a plugin registry/metaclass system,
which would be overkill for the current number of sources.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from src.models import RawRecord


class SourceConnector(ABC):
    source_name: str = "base"
    source_type: str = "unknown"

    def __init__(self, origin: str):
        self.origin = origin

    @abstractmethod
    def fetch(self) -> Optional[RawRecord]:
        """
        Read from self.origin and return a RawRecord, or None if the
        source is unavailable/empty. Must never raise for "source not
        present" -- only for genuine I/O errors, which callers catch.
        """
        raise NotImplementedError
