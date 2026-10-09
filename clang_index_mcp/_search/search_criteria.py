"""DTO describing search criteria for symbol lookups."""

from dataclasses import dataclass


@dataclass
class SearchCriteria:
    """Search parameters forwarded from QueryEngine to SearchEngine."""

    pattern: str = ""
    project_only: bool = True
    class_name: str | None = None
    file_name: str | None = None
    namespace: str | None = None
    max_results: int | None = None
    signature_pattern: str | None = None
    include_attributes: bool = False
    include_base_classes: bool = True
    symbol_types: list[str] | None = None
