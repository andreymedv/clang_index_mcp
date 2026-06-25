"""Compilation and libclang parsing context."""

from dataclasses import dataclass
from typing import Optional

from clang.cindex import Index

from .clang_parser import ClangParser
from .compilation_environment import CompilationEnvironment


@dataclass
class CompilationContext:
    """libclang and compile-command related services."""

    index: Index
    compilation_env: Optional[CompilationEnvironment] = None
    clang_parser: Optional[ClangParser] = None
