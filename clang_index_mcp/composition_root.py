"""
Composition root for the C++ Analyzer.

This module contains the CompositionRoot class, which is responsible for
creating and wiring all concrete implementations of the application's
components. It follows the Dependency Inversion Principle by centralizing
all concrete instantiation in one place.

CppAnalyzer delegates to CompositionRoot for initialization, keeping itself
as a thin facade over the composed services.
"""

from typing import Optional

from ._compilation.clang_parser import ClangParser
from ._compilation.clang_symbol_parser import ClangSymbolParser
from ._compilation.compile_commands_manager import CompileCommandsManager
from ._compilation.compilation_environment import CompilationEnvironment
from ._compilation.include_extractor import ClangIncludeExtractor
from ._core import diagnostics
from ._indexing.indexing_orchestrator import ProjectIndexingOrchestrator
from ._indexing.indexing_pipeline import SingleFileIndexingPipeline
from ._indexing.indexing_task_submitter import IndexingTaskSubmitter
from ._indexing.refresh_pipeline import RefreshPipeline
from ._indexing.worker_result_merger import WorkerResultMerger
from ._persistence.cache_orchestrator import CacheOrchestrator
from ._persistence.repositories.dependency_repository import SqliteDependencyRepository
from ._persistence.sqlite_cache_backend import SqliteCacheBackend
from ._search.call_graph_service import CallGraphService
from ._search.dependency_graph import DependencyGraphBuilder
from ._search.query_engine import QueryEngine
from ._symbols.symbol_extractor import SymbolExtractor
from ._symbols.symbol_index_store import SymbolIndexStore
from .project_context import ProjectContext


class CompositionRoot:
    """
    Central place for creating and wiring all concrete implementations.

    This class follows the Composition Root pattern from Clean Architecture.
    All dependency wiring happens here, making it easy to:
    - Understand the full object graph
    - Swap implementations
    - Test with mock implementations

    The CompositionRoot extracts core contexts from ProjectContext and wires
    all concrete implementations. CppAnalyzer delegates to this class.
    """

    def __init__(
        self,
        project_root: str,
        config_file: Optional[str] = None,
        skip_schema_recreation: bool = False,
        use_compile_commands_manager: bool = True,
    ):
        """
        Initialize the composition root.

        Args:
            project_root: Path to project source directory.
            config_file: Optional path to configuration file for project identity.
            skip_schema_recreation: If True, skip database recreation on schema mismatch.
                                   Used by worker processes to avoid race conditions.
            use_compile_commands_manager: If False, skip CompileCommandsManager initialization.
                                         Used by worker processes that receive precomputed args.
        """
        # Build ProjectContext first — it owns the core contexts (concurrency,
        # cancellation, execution, cache_manager, etc.).  CompositionRoot
        # extracts them and uses the same instances throughout.
        self.context = ProjectContext(
            project_root,
            config_file=config_file,
            skip_schema_recreation=skip_schema_recreation,
        )

        # Extract core attributes from ProjectContext so every downstream
        # component receives the exact same instances.
        self.project_root = self.context.project_root
        self.project_identity = self.context.project_identity
        self.config = self.context.config
        self.cache_manager = self.context.cache_manager
        self.concurrency = self.context.concurrency
        self.cancellation = self.context.cancellation
        self.execution = self.context.execution
        self.progress_reporter = self.context.progress_reporter
        self.index = self.context.index

        # Wire services in dependency order

        # 1. CallGraphService (needs persistence context)
        self.call_graph_service = CallGraphService(self.context.persistence)
        self.context.symbols.call_graph_service = self.call_graph_service

        # 2. SymbolIndexStore (needs concurrency and call graph)
        self.symbol_store = SymbolIndexStore(
            get_lock=self.concurrency.get_lock,
            index_lock=self.concurrency.index_lock,
            get_thread_local_buffers=self.concurrency.get_thread_local_buffers,
            cache_manager=self.cache_manager,
            call_graph_port=self.call_graph_service.call_graph_analyzer,
        )
        self.context.symbols.symbol_store = self.symbol_store

        # 3. CompilationEnvironment (needs identity, symbols, persistence)
        self.compilation_env = CompilationEnvironment(
            self.context.identity,
            self.context.symbols,
            self.context.persistence,
        )
        self.context.compilation.compilation_env = self.compilation_env

        # 4. QueryEngine (needs symbol_store, cache, concurrency, compilation, call_graph)
        self.query_engine = QueryEngine(
            symbol_store=self.symbol_store,
            cache_manager=self.cache_manager,
            concurrency=self.concurrency,
            compilation_env=self.compilation_env,
            call_graph_service=self.call_graph_service,
            project_root=self.project_root,
        )
        self.context.query.query_engine = self.query_engine

        # Break circular dependency: CallGraphService needs symbol_store/query_engine
        self.call_graph_service.set_dependencies(self.symbol_store, self.query_engine)

        # 5. CacheOrchestrator
        self.cache_orchestrator = CacheOrchestrator(
            cache_manager=self.cache_manager,
            config=self.config,
            project_root=self.project_root,
            symbol_store=self.symbol_store,
            compilation_env=self.compilation_env,
            call_graph_service=self.call_graph_service,
        )
        self.context.persistence.cache_orchestrator = self.cache_orchestrator

        # Wire call graph service to SQLite cache backend
        self.call_graph_service.setup_cache_backend()

        # Initialize compile commands manager only if needed
        if use_compile_commands_manager:
            compile_commands_config = self.config.get_compile_commands_config()
            self.compilation_env.compile_commands_manager = CompileCommandsManager(
                self.project_root,
                compile_commands_config,
                cache_dir=self.cache_manager.cache_dir,
                cache_backend=self.cache_manager.backend,
            )

        # Initialize dependency graph and header tracking
        backend = self.cache_manager.backend
        if isinstance(backend, SqliteCacheBackend):
            repository = SqliteDependencyRepository(lambda: backend.get_connection())
            extractor = ClangIncludeExtractor()
            self.call_graph_service.set_dependency_graph(
                DependencyGraphBuilder(repository, extractor)
            )
        else:
            self.call_graph_service.set_dependency_graph(None)
        self.cache_orchestrator.calculate_compile_commands_hash()
        self.cache_orchestrator.restore_or_reset_header_tracking()

        # 6. ClangParser (needs persistence context)
        self.clang_parser = ClangParser(self.context.persistence)
        self.context.compilation.clang_parser = self.clang_parser

        # 7. SymbolExtractor
        self.symbol_extractor = SymbolExtractor(
            symbol_store=self.symbol_store,
            concurrency=self.concurrency,
            compilation_env=self.compilation_env,
            cache_orchestrator=self.cache_orchestrator,
            call_graph_service=self.call_graph_service,
            parser=ClangSymbolParser(
                compilation_env=self.compilation_env,
                symbol_store=self.symbol_store,
                cache_orchestrator=self.cache_orchestrator,
            ),
        )
        self.context.symbols.symbol_extractor = self.symbol_extractor

        # 8. Indexing pipeline components
        self.task_submitter = IndexingTaskSubmitter(
            project_root=self.project_root,
            project_identity=self.project_identity,
            execution=self.execution,
            compilation_env=self.compilation_env,
        )
        self.worker_result_merger = WorkerResultMerger(
            concurrency=self.concurrency,
            symbol_store=self.symbol_store,
            call_graph_service=self.call_graph_service,
            cache_orchestrator=self.cache_orchestrator,
        )
        self.indexing_pipeline = SingleFileIndexingPipeline(
            clang_parser=self.clang_parser,
            symbol_extractor=self.symbol_extractor,
            compilation_env=self.compilation_env,
            cache_orchestrator=self.cache_orchestrator,
            cache_manager=self.cache_manager,
            concurrency=self.concurrency,
            symbol_store=self.symbol_store,
        )
        self.refresh_pipeline = RefreshPipeline(
            compilation_env=self.compilation_env,
            execution=self.execution,
            cache_manager=self.cache_manager,
            cache_orchestrator=self.cache_orchestrator,
            symbol_extractor=self.symbol_extractor,
            symbol_store=self.symbol_store,
            progress_reporter=self.progress_reporter,
            task_submitter=self.task_submitter,
            worker_result_merger=self.worker_result_merger,
        )
        self.context.persistence.refresh_pipeline = self.refresh_pipeline
        self.indexing_orchestrator = ProjectIndexingOrchestrator(
            cancellation=self.cancellation,
            concurrency=self.concurrency,
            execution=self.execution,
            compilation_env=self.compilation_env,
            cache_orchestrator=self.cache_orchestrator,
            cache_manager=self.cache_manager,
            symbol_extractor=self.symbol_extractor,
            symbol_store=self.symbol_store,
            progress_reporter=self.progress_reporter,
            task_submitter=self.task_submitter,
            worker_result_merger=self.worker_result_merger,
            refresh_pipeline=self.refresh_pipeline,
        )

        diagnostics.debug(f"CompositionRoot initialized for project: {self.project_root}")

        if self.compilation_env.has_active_compile_commands():
            compile_commands_config = self.config.get_compile_commands_config()
            cc_path = self.project_root / compile_commands_config.compile_commands_path
            if cc_path.exists():
                diagnostics.debug(
                    f"Compile commands enabled: using {compile_commands_config.compile_commands_path}"
                )
            else:
                diagnostics.debug(
                    f"Compile commands enabled: {compile_commands_config.compile_commands_path} not found, will use fallback args"
                )
        elif self.compilation_env.compile_commands_manager is None:
            diagnostics.debug("Worker mode: using precomputed compile args from main process")
        else:
            diagnostics.debug("Compile commands disabled in configuration")
