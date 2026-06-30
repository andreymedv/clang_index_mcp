"""Port for extracting include directives from a parsed translation unit."""

from typing import List, Protocol

from clang.cindex import TranslationUnit


class IncludeExtractor(Protocol):
    """Extract absolute include paths from a parsed translation unit."""

    def extract_includes(self, tu: TranslationUnit, source_file: str) -> List[str]:
        """
        Return a list of absolute paths of files included by ``source_file``
        according to the parsed translation unit ``tu``.
        """
        ...
