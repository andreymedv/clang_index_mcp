"""Incremental analysis context.

Focused context for incremental analysis modules, replacing the dependency
on the CppAnalyzer facade.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from typing import TYPE_CHECKING

from .._core.concurrency_context import ConcurrencyContext
from ..cpp_analyzer_config import CppAnalyzerConfig
from .._persistence.cache_manager import CacheManager
from .._persistence.cache_orchestrator import CacheOrchestrator
from .._compilation.compilation_environment import CompilationEnvironment
from .._symbols.symbol_index_store import SymbolIndexStore

if TYPE_CHECKING:
    from .._search.call_graph import CallGraphAnalyzer
    from .._search.dependency_graph import DependencyGraphBuilder


@dataclass
class IncrementalContext:
    """Services required by incremental analysis modules.

    This context replaces the dependency on the CppAnalyzer facade,
    providing only the specific services that incremental modules need.
    """

    project_root: Path
    config: CppAnalyzerConfig
    cache_manager: CacheManager
    cache_orchestrator: CacheOrchestrator
    compilation_env: CompilationEnvironment
    symbol_store: SymbolIndexStore
    concurrency: ConcurrencyContext
    call_graph_analyzer: "CallGraphAnalyzer"
    dependency_graph: "DependencyGraphBuilder"
    config_file: Optional[str] = None
