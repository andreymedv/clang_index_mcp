import threading
from typing import Any, List, Optional, Tuple

from clang.cindex import Index, TranslationUnit, TranslationUnitLoadError

from . import diagnostics


class ClangParser:
    """
    Handles libclang Index and TranslationUnit management.
    """

    def __init__(self, analyzer: Any):
        """
        Initialize ClangParser.

        Args:
            analyzer: Reference to the CppAnalyzer instance for access to config and cache_manager.
        """
        self.analyzer = analyzer
        self._thread_local = threading.local()

    def _get_thread_index(self) -> Index:
        """Return a thread-local libclang Index instance."""
        index = getattr(self._thread_local, "index", None)
        if index is None:
            index = Index.create()
            self._thread_local.index = index
        return index

    def _try_parse_with_fallback(
        self, file_path: str, args: List[str]
    ) -> Tuple[Optional[Any], Optional[str]]:
        """Try parsing with progressive fallback if initial attempt fails."""
        index = self._get_thread_index()
        parse_options_attempts = [
            (
                TranslationUnit.PARSE_INCOMPLETE | TranslationUnit.PARSE_DETAILED_PROCESSING_RECORD,
                "full detailed processing",
            ),
            (TranslationUnit.PARSE_INCOMPLETE, "incomplete parsing"),
            (0, "minimal options"),
        ]

        last_error = None
        for options, description in parse_options_attempts:
            try:
                tu = index.parse(file_path, args=args, options=options)
                if tu:
                    if description != "full detailed processing":
                        diagnostics.debug(f"{file_path}: parsed with {description}")
                    return tu, None
            except TranslationUnitLoadError as e:
                last_error = e
                continue

        error_msg = (
            f"TranslationUnitLoadError: {last_error}" if last_error else "libclang returned None"
        )
        return None, error_msg

    @staticmethod
    def _is_system_header_diagnostic(diag: Any) -> bool:
        """Check if a diagnostic originates from a system header."""
        if not diag.location.file:
            return False

        file_path = str(diag.location.file)

        # Check for common system header patterns
        system_patterns = [
            "/usr/include/",
            "/usr/local/include/",
            "lib/clang/",  # Clang builtin headers (e.g., arm_acle.h, arm_neon.h)
            "/Library/Developer/CommandLineTools/usr/lib/clang/",  # macOS
            "/Library/Developer/CommandLineTools/SDKs/",  # macOS SDK
            "C:\\Program Files",  # Windows system
            "/opt/homebrew/",  # macOS Homebrew
        ]

        return any(pattern in file_path for pattern in system_patterns)

    def _extract_diagnostics(self, tu: Any) -> Tuple[List[Any], List[Any]]:
        """Extract error and warning diagnostics from translation unit."""
        error_diagnostics = []
        warning_diagnostics = []

        if tu and hasattr(tu, "diagnostics"):
            for diag in tu.diagnostics:
                severity = diag.severity
                # Severity levels: Ignored=0, Note=1, Warning=2, Error=3, Fatal=4

                # Filter out errors from system headers
                if severity >= 3:  # Error or Fatal
                    if not self._is_system_header_diagnostic(diag):
                        error_diagnostics.append(diag)
                    else:
                        # Downgrade system header errors to warnings for logging
                        warning_diagnostics.append(diag)
                elif severity == 2:  # Warning
                    warning_diagnostics.append(diag)

        return error_diagnostics, warning_diagnostics

    @staticmethod
    def _format_diagnostics(diagnostics_list: List[Any], max_count: int = 5) -> str:
        """Format libclang diagnostics into a readable string."""
        if not diagnostics_list:
            return ""

        messages = []
        for diag in diagnostics_list[:max_count]:
            # Format location
            if diag.location.file:
                location = f"{diag.location.file}:{diag.location.line}:{diag.location.column}"
            else:
                location = "unknown location"

            # Get severity name
            severity_names = {0: "ignored", 1: "note", 2: "warning", 3: "error", 4: "fatal"}
            severity_name = severity_names.get(diag.severity, "unknown")

            messages.append(f"[{severity_name}] {location}: {diag.spelling}")

        total = len(diagnostics_list)
        if total > max_count:
            messages.append(f"... and {total - max_count} more")

        return "\n".join(messages)

    def _handle_index_file_diagnostics(
        self, file_path: str, tu: Any, current_hash: str, compile_args_hash: str, retry_count: int
    ) -> Optional[str]:
        """Extract and process diagnostics. Returns error message if any."""
        error_diagnostics, warning_diagnostics = self._extract_diagnostics(tu)
        cache_error_msg = None

        if error_diagnostics:
            formatted_errors = self._format_diagnostics(error_diagnostics, max_count=5)
            full_error_msg = (
                f"libclang parsing errors ({len(error_diagnostics)} total):\n{formatted_errors}"
            )
            cache_error_msg = full_error_msg[:200]

            parse_error = Exception(full_error_msg)
            self.analyzer.cache_manager.log_parse_error(
                file_path, parse_error, current_hash, compile_args_hash, retry_count
            )

            diagnostics.warning(
                f"{file_path}: Continuing despite {len(error_diagnostics)} error(s):\n{cache_error_msg}"
            )

        if warning_diagnostics:
            formatted_warnings = self._format_diagnostics(warning_diagnostics, max_count=3)
            diagnostics.debug(
                f"{file_path}: {len(warning_diagnostics)} warning(s):\n{formatted_warnings}"
            )

        return cache_error_msg
