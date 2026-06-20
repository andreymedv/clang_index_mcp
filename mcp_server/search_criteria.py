"""DTO describing search criteria for symbol lookups."""

from dataclasses import dataclass
from typing import List, Optional


@dataclass
class SearchCriteria:
    """Search parameters forwarded from QueryEngine to SearchEngine."""

    pattern: str = ""
    project_only: bool = True
    class_name: Optional[str] = None
    file_name: Optional[str] = None
    namespace: Optional[str] = None
    max_results: Optional[int] = None
    signature_pattern: Optional[str] = None
    include_attributes: bool = False
    include_base_classes: bool = True
    symbol_types: Optional[List[str]] = None
