"""
Project-wide dependency container for C++ analysis components.

ProjectContext holds the shared services and configuration that the indexing,
refresh, and query pipelines need.  It is intentionally a plain data container:
no behavior lives here except trivial delegations to the owned components.
"""

from pathlib import Path
from typing import TYPE_CHECKING, Optional

from clang.cindex import Index

from ._persistence.cache_manager import CacheManager
from ._persistence.cache_orchestrator import CacheOrchestrator
from ._search.call_graph_service import CallGraphService
from ._core.cancellation_coordinator import CancellationCoordinator
from ._compilation.clang_parser import ClangParser
from ._compilation.compilation_environment import CompilationEnvironment
from ._core.concurrency_context import ConcurrencyContext
from .cpp_analyzer_config import CppAnalyzerConfig
from ._indexing.execution_config import ExecutionConfig
from ._indexing.indexing_progress_reporter import IndexingProgressReporter
from ._persistence.project_identity import ProjectIdentity
from ._search.query_engine import QueryEngine
from ._symbols.symbol_extractor import SymbolExtractor
from ._symbols.symbol_index_store import SymbolIndexStore

if TYPE_CHECKING:
    from ._indexing.refresh_pipeline import RefreshPipeline


class ProjectContext:
    """
    Mutable container for all services tied to a single analyzed project.

    Components receive this object instead of the full CppAnalyzer, which makes
    dependencies explicit and simplifies unit testing.  Backward-compatible
    properties on CppAnalyzer still expose the same services.

    The container is mutable so that components can be wired incrementally during
    the one-by-one migration away from CppAnalyzer references.
    """

    def __init__(
        self,
        project_root: str,
        config_file: Optional[str] = None,
        skip_schema_recreation: bool = False,
    ):
        """
        Initialize the project context with core services that have no circular
        dependencies during construction.

        Args:
            project_root: Path to project source directory.
            config_file: Optional path to configuration file for project identity.
            skip_schema_recreation: Passed to CacheManager for worker processes.
        """
        self.project_root = Path(project_root).resolve()
        self.index = Index.create()
        self._skip_schema_recreation = skip_schema_recreation

        config_path = Path(config_file).resolve() if config_file else None
        self.project_identity = ProjectIdentity(self.project_root, config_path)
        self.config = CppAnalyzerConfig(self.project_root, config_path=config_path)

        # Core services with no circular construction dependencies.
        self.cache_manager = CacheManager(
            self.project_identity, skip_schema_recreation=self._skip_schema_recreation
        )
        self.concurrency = ConcurrencyContext()
        self.cancellation = CancellationCoordinator()
        self.execution = ExecutionConfig(config_max_workers=self.config.get_max_workers())
        self.progress_reporter = IndexingProgressReporter()

        # Components populated after the context is created so they can depend on
        # the context instead of the full CppAnalyzer.
        self.clang_parser: Optional[ClangParser] = None
        self.symbol_extractor: Optional[SymbolExtractor] = None
        self.symbol_store: Optional[SymbolIndexStore] = None
        self.call_graph_service: Optional[CallGraphService] = None
        self.query_engine: Optional[QueryEngine] = None
        self.compilation_env: Optional[CompilationEnvironment] = None
        self.cache_orchestrator: Optional[CacheOrchestrator] = None
        self.refresh_pipeline: Optional["RefreshPipeline"] = None

    @property
    def compile_commands_manager(self):
        """Convenience accessor for the compile commands manager."""
        if self.compilation_env is None:
            return None
        return self.compilation_env.compile_commands_manager

    def is_compile_commands_enabled(self) -> bool:
        """Return True when compile commands integration is active."""
        return (
            self.compilation_env is not None and self.compilation_env.has_active_compile_commands()
        )

    @property
    def cache_dir(self) -> Path:
        """Convenience accessor for the cache directory."""
        return self.cache_manager.cache_dir

    @property
    def file_scanner(self):
        """Convenience accessor for the file scanner."""
        assert self.compilation_env is not None
        return self.compilation_env.file_scanner

    @property
    def max_workers(self) -> int:
        """Convenience accessor for the worker pool size."""
        return self.execution.max_workers

    @property
    def use_processes(self) -> bool:
        """Convenience accessor for the process-vs-thread execution mode."""
        return self.execution.use_processes
