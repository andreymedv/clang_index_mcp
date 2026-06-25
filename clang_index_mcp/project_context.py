"""Project-wide dependency container for C++ analysis components.

ProjectContext is now a thin facade over focused, cohesive contexts.  Each
component can receive only the context it actually needs, while legacy callers
continue to work through the backward-compatible properties on this class.
"""

from pathlib import Path
from typing import TYPE_CHECKING, Optional

from clang.cindex import Index

if TYPE_CHECKING:
    from ._indexing.refresh_pipeline import RefreshPipeline

from ._core.cancellation_coordinator import CancellationCoordinator
from ._core.concurrency_context import ConcurrencyContext
from ._persistence.error_tracking_adapter import ErrorTrackingAdapter
from ._contexts import ProjectIdentityContext
from ._contexts.runtime_context import RuntimeContext
from ._compilation.clang_parser import ClangParser
from ._compilation.compilation_context import CompilationContext
from ._compilation.compilation_environment import CompilationEnvironment
from .cpp_analyzer_config import CppAnalyzerConfig
from ._indexing.execution_config import ExecutionConfig
from ._indexing.indexing_progress_reporter import IndexingProgressReporter
from ._persistence.cache_manager import CacheManager
from ._persistence.cache_orchestrator import CacheOrchestrator
from ._persistence.persistence_context import PersistenceContext
from ._persistence.project_identity import ProjectIdentity
from ._persistence.sqlite_cache_backend import SqliteCacheBackend
from ._search.call_graph_service import CallGraphService
from ._search.query_context import QueryContext
from ._search.query_engine import QueryEngine
from ._symbols.symbol_context import SymbolContext
from ._symbols.symbol_extractor import SymbolExtractor
from ._symbols.symbol_index_store import SymbolIndexStore


class ProjectContext:
    """
    Mutable container for all services tied to a single analyzed project.

    Components should receive one of the focused contexts (``identity``,
    ``runtime``, ``compilation``, ``persistence``, ``symbols``, ``query``)
    instead of this facade whenever possible.  The properties on this class
    remain for backward compatibility and for the thin ``CppAnalyzer`` shell.
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
        project_root_path = Path(project_root).resolve()
        config_path = Path(config_file).resolve() if config_file else None

        project_identity = ProjectIdentity(project_root_path, config_path)
        config = CppAnalyzerConfig(project_root_path, config_path=config_path)

        cache_dir = CacheManager.compute_cache_dir(project_identity)
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_backend = SqliteCacheBackend(
            cache_dir / "symbols.db",
            skip_schema_recreation=skip_schema_recreation,
        )
        cache_recovery = ErrorTrackingAdapter()
        cache_manager = CacheManager(
            project_identity,
            skip_schema_recreation=skip_schema_recreation,
            backend=cache_backend,
            recovery=cache_recovery,
        )
        concurrency = ConcurrencyContext()
        cancellation = CancellationCoordinator()
        execution = ExecutionConfig(config_max_workers=config.get_max_workers())
        progress_reporter = IndexingProgressReporter()

        self.identity = ProjectIdentityContext(
            project_root=project_root_path,
            project_identity=project_identity,
            config=config,
        )
        self.runtime = RuntimeContext(
            concurrency=concurrency,
            cancellation=cancellation,
            execution=execution,
            progress_reporter=progress_reporter,
        )
        self.compilation = CompilationContext(index=Index.create())
        self.persistence = PersistenceContext(cache_manager=cache_manager)
        self.symbols = SymbolContext()
        self.query = QueryContext()

    # ------------------------------------------------------------------
    # Backward-compatible facade properties
    # ------------------------------------------------------------------

    @property
    def project_root(self) -> Path:
        return self.identity.project_root

    @property
    def project_identity(self) -> ProjectIdentity:
        return self.identity.project_identity

    @property
    def config(self) -> CppAnalyzerConfig:
        return self.identity.config

    @property
    def index(self) -> Index:
        return self.compilation.index

    @property
    def cache_manager(self) -> CacheManager:
        return self.persistence.cache_manager

    @property
    def cache_orchestrator(self) -> Optional[CacheOrchestrator]:
        return self.persistence.cache_orchestrator

    @property
    def concurrency(self) -> ConcurrencyContext:
        return self.runtime.concurrency

    @property
    def cancellation(self) -> CancellationCoordinator:
        return self.runtime.cancellation

    @property
    def execution(self) -> ExecutionConfig:
        return self.runtime.execution

    @property
    def progress_reporter(self) -> IndexingProgressReporter:
        return self.runtime.progress_reporter

    @property
    def call_graph_service(self) -> Optional[CallGraphService]:
        return self.symbols.call_graph_service

    @property
    def symbol_store(self) -> Optional[SymbolIndexStore]:
        return self.symbols.symbol_store

    @property
    def symbol_extractor(self) -> Optional[SymbolExtractor]:
        return self.symbols.symbol_extractor

    @property
    def compilation_env(self) -> Optional[CompilationEnvironment]:
        return self.compilation.compilation_env

    @property
    def clang_parser(self) -> Optional[ClangParser]:
        return self.compilation.clang_parser

    @property
    def query_engine(self) -> Optional[QueryEngine]:
        return self.query.query_engine

    @property
    def refresh_pipeline(self) -> Optional["RefreshPipeline"]:
        return self.persistence.refresh_pipeline

    @property
    def compile_commands_manager(self):
        """Convenience accessor for the compile commands manager."""
        if self.compilation.compilation_env is None:
            return None
        return self.compilation.compilation_env.compile_commands_manager

    def is_compile_commands_enabled(self) -> bool:
        """Return True when compile commands integration is active."""
        return (
            self.compilation.compilation_env is not None
            and self.compilation.compilation_env.has_active_compile_commands()
        )

    @property
    def cache_dir(self) -> Path:
        """Convenience accessor for the cache directory."""
        return self.persistence.cache_manager.cache_dir

    @property
    def file_scanner(self):
        """Convenience accessor for the file scanner."""
        assert self.compilation.compilation_env is not None
        return self.compilation.compilation_env.file_scanner

    @property
    def max_workers(self) -> int:
        """Convenience accessor for the worker pool size."""
        return self.runtime.execution.max_workers

    def build_incremental_context(self):
        """Build an IncrementalContext from the current project state.

        Returns an IncrementalContext with all services needed by incremental
        analysis modules, or None if required services are not yet initialized.
        """
        from ._contexts.incremental_context import IncrementalContext

        compilation_env = self.compilation.compilation_env
        symbol_store = self.symbols.symbol_store
        cache_orchestrator = self.persistence.cache_orchestrator
        call_graph_service = self.symbols.call_graph_service

        if not all([compilation_env, symbol_store, cache_orchestrator, call_graph_service]):
            return None

        return IncrementalContext(
            project_root=self.identity.project_root,
            config=self.identity.config,
            cache_manager=self.persistence.cache_manager,
            cache_orchestrator=cache_orchestrator,
            compilation_env=compilation_env,
            symbol_store=symbol_store,
            concurrency=self.runtime.concurrency,
            call_graph_analyzer=call_graph_service.call_graph_analyzer,
            dependency_graph=call_graph_service.dependency_graph,
            config_file=(
                str(self.identity.project_identity.config_file_path)
                if self.identity.project_identity.config_file_path
                else None
            ),
        )
