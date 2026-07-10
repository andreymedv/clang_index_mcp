from typing import Any, Callable, List, Optional, Tuple

from clang.cindex import Index, TranslationUnit, TranslationUnitLoadError, Diagnostic

from .._core import diagnostics


class ClangParser:
    """
    Handles libclang Index and TranslationUnit management.

    This parser is intentionally not thread-safe: one instance must be used
    by a single indexing thread/process. The analyzer already creates a
    separate ClangParser per worker process, so no thread-local caching is
    required.
    """

    def __init__(
        self,
        log_parse_error: Callable[[str, Exception, str, Optional[str], int], Any],
    ):
        """
        Initialize ClangParser.

        Args:
            log_parse_error: Callback to log parse errors to cache.
                Signature: (file_path, error, file_hash, compile_args_hash, retry_count) -> Any
        """
        self._log_parse_error = log_parse_error
        self._index: Index = Index.create()

    def try_parse_with_fallback(
        self, file_path: str, args: List[str]
    ) -> Tuple[Optional[TranslationUnit], Optional[str]]:
        """Try parsing with progressive fallback if initial attempt fails."""
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
                tu = self._index.parse(file_path, args=args, options=options)
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
    def _is_system_header_diagnostic(diag: Diagnostic) -> bool:
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

    def _extract_diagnostics(
        self, tu: TranslationUnit
    ) -> Tuple[List[Diagnostic], List[Diagnostic]]:
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
    def _format_diagnostics(diagnostics_list: List[Diagnostic], max_count: int = 5) -> str:
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

    def handle_index_file_diagnostics(
        self,
        file_path: str,
        tu: TranslationUnit,
        current_hash: str,
        compile_args_hash: str,
        retry_count: int,
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
            self._log_parse_error(
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
