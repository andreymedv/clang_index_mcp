"""
Project-wide dependency container for C++ analysis components.

ProjectContext holds the shared services and configuration that the indexing,
refresh, and query pipelines need.  It is intentionally a plain data container:
no behavior lives here except trivial delegations to the owned components.
"""

from dataclasses import dataclass, field
from pathlib import Path

from clang.cindex import Index

from .cache_manager import CacheManager
from .cache_orchestrator import CacheOrchestrator
from .call_graph_service import CallGraphService
from .cancellation_coordinator import CancellationCoordinator
from .clang_parser import ClangParser
from .compilation_environment import CompilationEnvironment
from .concurrency_context import ConcurrencyContext
from .cpp_analyzer_config import CppAnalyzerConfig
from .execution_config import ExecutionConfig
from .indexing_progress_reporter import IndexingProgressReporter
from .project_identity import ProjectIdentity
from .query_engine import QueryEngine
from .symbol_extractor import SymbolExtractor
from .symbol_index_store import SymbolIndexStore


@dataclass
class ProjectContext:
    """
    Immutable-ish container for all services tied to a single analyzed project.

    Components receive this object instead of the full CppAnalyzer, which makes
    dependencies explicit and simplifies unit testing.  Backward-compatible
    properties on CppAnalyzer still expose the same services.
    """

    project_root: Path
    project_identity: ProjectIdentity
    config: CppAnalyzerConfig
    index: Index
    skip_schema_recreation: bool

    # Core parsing and symbol extraction
    clang_parser: ClangParser
    symbol_extractor: SymbolExtractor

    # Index and graph stores
    symbol_store: SymbolIndexStore
    call_graph_service: CallGraphService
    query_engine: QueryEngine

    # Caching and compilation environment
    cache_manager: CacheManager
    cache_orchestrator: CacheOrchestrator
    compilation_env: CompilationEnvironment

    # Execution and concurrency
    concurrency: ConcurrencyContext
    execution: ExecutionConfig
    cancellation: CancellationCoordinator

    # Progress reporting (lightweight helper, safe to share)
    progress_reporter: IndexingProgressReporter = field(default_factory=IndexingProgressReporter)

    @property
    def compile_commands_manager(self):
        """Convenience accessor for the compile commands manager."""
        return self.compilation_env.compile_commands_manager

    @property
    def cache_dir(self) -> Path:
        """Convenience accessor for the cache directory."""
        return self.cache_manager.cache_dir
