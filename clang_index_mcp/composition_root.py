"""
Composition root for the C++ Analyzer.

This module contains the CompositionRoot class, which is responsible for
creating and wiring all concrete implementations of the application's
components. It follows the Dependency Inversion Principle by centralizing
all concrete instantiation in one place.

CppAnalyzer delegates to CompositionRoot for initialization, keeping itself
as a thin facade over the composed services.
"""

from pathlib import Path
from typing import Optional

from clang.cindex import Index

from ._compilation.clang_parser import ClangParser
from ._compilation.clang_symbol_parser import ClangSymbolParser
from ._compilation.compile_commands_manager import CompileCommandsManager
from ._compilation.compilation_environment import CompilationEnvironment
from ._core import diagnostics
from ._core.cancellation_coordinator import CancellationCoordinator
from ._core.concurrency_context import ConcurrencyContext
from ._indexing.execution_config import ExecutionConfig
from ._indexing.indexing_orchestrator import ProjectIndexingOrchestrator
from ._indexing.indexing_pipeline import SingleFileIndexingPipeline
from ._indexing.indexing_progress_reporter import IndexingProgressReporter
from ._indexing.indexing_task_submitter import IndexingTaskSubmitter
from ._indexing.refresh_pipeline import RefreshPipeline
from ._indexing.worker_result_merger import WorkerResultMerger
from ._persistence.cache_manager import CacheManager
from ._persistence.cache_orchestrator import CacheOrchestrator
from ._persistence.project_identity import ProjectIdentity
from ._search.call_graph_service import CallGraphService
from ._search.query_engine import QueryEngine
from ._symbols.symbol_extractor import SymbolExtractor
from ._symbols.symbol_index_store import SymbolIndexStore
from .cpp_analyzer_config import CppAnalyzerConfig
from .project_context import ProjectContext


class CompositionRoot:
    """
    Central place for creating and wiring all concrete implementations.

    This class follows the Composition Root pattern from Clean Architecture.
    All dependency wiring happens here, making it easy to:
    - Understand the full object graph
    - Swap implementations
    - Test with mock implementations

    The CompositionRoot creates and holds references to all composed services.
    CppAnalyzer delegates to this class for initialization.
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
        self._skip_schema_recreation = skip_schema_recreation

        # Resolve paths
        project_root_path = Path(project_root).resolve()
        config_path = Path(config_file).resolve() if config_file else None

        # Create project identity and config
        project_identity = ProjectIdentity(project_root_path, config_path)
        config = CppAnalyzerConfig(project_root_path, config_path=config_path)

        # Create core contexts
        cache_manager = CacheManager(
            project_identity, skip_schema_recreation=skip_schema_recreation
        )
        concurrency = ConcurrencyContext()
        cancellation = CancellationCoordinator()
        execution = ExecutionConfig(config_max_workers=config.get_max_workers())
        progress_reporter = IndexingProgressReporter()

        # Build ProjectContext (thin facade over focused contexts)
        self.context = ProjectContext(
            project_root,
            config_file=config_file,
            skip_schema_recreation=skip_schema_recreation,
        )

        # Expose core attributes
        self.project_root = project_root_path
        self.project_identity = project_identity
        self.config = config
        self.cache_manager = cache_manager
        self.concurrency = concurrency
        self.cancellation = cancellation
        self.execution = execution
        self.progress_reporter = progress_reporter
        self.index = Index.create()

        # Wire services in dependency order

        # 1. CallGraphService (needs persistence context)
        self.call_graph_service = CallGraphService(self.context.persistence)
        self.context.symbols.call_graph_service = self.call_graph_service

        # 2. SymbolIndexStore (needs concurrency and call graph)
        self.symbol_store = SymbolIndexStore(
            get_lock=concurrency.get_lock,
            index_lock=concurrency.index_lock,
            get_thread_local_buffers=concurrency.get_thread_local_buffers,
            cache_manager=cache_manager,
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
            cache_manager=cache_manager,
            concurrency=concurrency,
            compilation_env=self.compilation_env,
            call_graph_service=self.call_graph_service,
            project_root=project_root_path,
        )
        self.context.query.query_engine = self.query_engine

        # Break circular dependency: CallGraphService needs symbol_store/query_engine
        self.call_graph_service.set_dependencies(self.symbol_store, self.query_engine)

        # 5. CacheOrchestrator (needs cache, config, project_root, symbol_store, compilation, call_graph)
        self.cache_orchestrator = CacheOrchestrator(
            cache_manager=cache_manager,
            config=config,
            project_root=project_root_path,
            symbol_store=self.symbol_store,
            compilation_env=self.compilation_env,
            call_graph_service=self.call_graph_service,
        )
        self.context.persistence.cache_orchestrator = self.cache_orchestrator

        # Wire call graph service to SQLite cache backend
        self.call_graph_service.setup_cache_backend()

        # Initialize compile commands manager only if needed
        if use_compile_commands_manager:
            compile_commands_config = config.get_compile_commands_config()
            self.compilation_env.compile_commands_manager = CompileCommandsManager(
                project_root_path,
                compile_commands_config,
                cache_dir=cache_manager.cache_dir,
                cache_backend=cache_manager.backend,
            )

        # Initialize dependency graph and header tracking
        self.call_graph_service.init_dependency_graph()
        self.cache_orchestrator._calculate_compile_commands_hash()
        self.cache_orchestrator._restore_or_reset_header_tracking()

        # 6. ClangParser (needs persistence context)
        self.clang_parser = ClangParser(self.context.persistence)
        self.context.compilation.clang_parser = self.clang_parser

        # 7. SymbolExtractor (needs symbol_store, concurrency, compilation, cache_orchestrator, call_graph, parser)
        self.symbol_extractor = SymbolExtractor(
            symbol_store=self.symbol_store,
            concurrency=concurrency,
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
            project_root=project_root_path,
            project_identity=project_identity,
            execution=execution,
            compilation_env=self.compilation_env,
        )
        self.worker_result_merger = WorkerResultMerger(
            concurrency=concurrency,
            symbol_store=self.symbol_store,
            call_graph_service=self.call_graph_service,
            cache_orchestrator=self.cache_orchestrator,
        )
        self.indexing_pipeline = SingleFileIndexingPipeline(
            clang_parser=self.clang_parser,
            symbol_extractor=self.symbol_extractor,
            compilation_env=self.compilation_env,
            cache_orchestrator=self.cache_orchestrator,
            cache_manager=cache_manager,
            concurrency=concurrency,
            symbol_store=self.symbol_store,
        )
        self.refresh_pipeline = RefreshPipeline(
            compilation_env=self.compilation_env,
            execution=execution,
            cache_manager=cache_manager,
            cache_orchestrator=self.cache_orchestrator,
            symbol_extractor=self.symbol_extractor,
            symbol_store=self.symbol_store,
            progress_reporter=progress_reporter,
            task_submitter=self.task_submitter,
            worker_result_merger=self.worker_result_merger,
        )
        self.context.persistence.refresh_pipeline = self.refresh_pipeline
        self.indexing_orchestrator = ProjectIndexingOrchestrator(
            cancellation=cancellation,
            concurrency=concurrency,
            execution=execution,
            compilation_env=self.compilation_env,
            cache_orchestrator=self.cache_orchestrator,
            cache_manager=cache_manager,
            symbol_extractor=self.symbol_extractor,
            symbol_store=self.symbol_store,
            progress_reporter=progress_reporter,
            task_submitter=self.task_submitter,
            worker_result_merger=self.worker_result_merger,
            refresh_pipeline=self.refresh_pipeline,
        )

        # Log initialization
        diagnostics.debug(f"CompositionRoot initialized for project: {project_root_path}")
        diagnostics.debug(
            f"Concurrency mode: ProcessPool (spawn, GIL bypass) with {execution.max_workers} workers"
        )

        # Log compile commands status
        if self.compilation_env.has_active_compile_commands():
            compile_commands_config = config.get_compile_commands_config()
            cc_path = project_root_path / compile_commands_config.compile_commands_path
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
