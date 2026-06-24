"""libclang-based implementation of the IncludeExtractor port."""

from pathlib import Path
from typing import Any, List

from .._core import diagnostics


class ClangIncludeExtractor:
    """Extract include directives from a libclang TranslationUnit."""

    def extract_includes(self, tu: Any, source_file: str) -> List[str]:
        """
        Return absolute paths of all files included by ``source_file`` according
        to the parsed translation unit ``tu``.
        """
        includes: List[str] = []

        try:
            for include in tu.get_includes():
                included_path = str(include.include.name)

                try:
                    included_path = str(Path(included_path).resolve())
                except Exception:
                    pass

                if included_path not in includes:
                    includes.append(included_path)

        except Exception as e:
            diagnostics.warning(f"Failed to extract includes from {source_file}: {e}")
            return []

        diagnostics.debug(f"Extracted {len(includes)} includes from {source_file}")
        return includes
