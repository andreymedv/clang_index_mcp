"""
Route the four previously unprotected backend calls through _safe_backend_call
(epic clang_index_mcp-ent, child .5, REQ-6.8.7).

save_file_cache, load_file_cache, remove_file_cache, and ensure_schema_current
must return their typed safe values on backend failure and never let exceptions
escape. An AST meta-test proves no ``self.backend`` access in cache_manager.py
bypasses the wrapper.
"""

import ast
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from clang_index_mcp._persistence.cache_manager import CacheManager
from clang_index_mcp._persistence.error_tracking_adapter import ErrorTrackingAdapter
from clang_index_mcp._symbols.model import SymbolInfo

CACHE_MANAGER_PATH = (
    Path(project_root) / "clang_index_mcp" / "_persistence" / "cache_manager.py"
)


def _symbol(name: str = "Foo") -> SymbolInfo:
    return SymbolInfo(
        name=name,
        qualified_name=name,
        kind="class",
        file="a.h",
        line=1,
        column=1,
    )


class TestProtectedBackendCalls(unittest.TestCase):
    """Failure -> typed safe value; success -> unchanged behavior."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.temp_project_dir = Path(self.temp_dir)
        self.cache_managers = []
        self.recovery_adapter = ErrorTrackingAdapter()

    def tearDown(self):
        for cm in self.cache_managers:
            try:
                cm.close()
            except Exception:
                pass
        self.cache_managers.clear()
        if self.temp_dir and os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def _create_cache_manager(self, backend: Mock | None = None) -> CacheManager:
        cm = CacheManager(
            self.temp_project_dir,
            backend=backend,
            recovery=self.recovery_adapter,
        )
        self.cache_managers.append(cm)
        return cm

    def _broken_backend(self, method: str, error: Exception | None = None) -> Mock:
        backend = Mock()
        backend.close = Mock()
        setattr(backend, method, Mock(side_effect=error or OSError("backend down")))
        return backend

    # --- save_file_cache -> False ---------------------------------------

    def test_save_file_cache_failure_returns_false(self):
        cm = self._create_cache_manager(self._broken_backend("save_file_cache"))
        result = cm.save_file_cache("a.h", [_symbol()], "hash")
        self.assertIs(result, False)
        self.assertIsInstance(result, bool)

    def test_save_file_cache_success_returns_backend_value(self):
        backend = Mock()
        backend.close = Mock()
        backend.save_file_cache = Mock(return_value=True)
        cm = self._create_cache_manager(backend)
        self.assertIs(cm.save_file_cache("a.h", [_symbol()], "hash"), True)

    def test_save_file_cache_failure_marks_degraded(self):
        cm = self._create_cache_manager(self._broken_backend("save_file_cache"))
        cm.save_file_cache("a.h", [_symbol()], "hash")
        self.assertTrue(cm.is_degraded("save_file_cache"))
        self.assertIsNotNone(cm.last_error_for("save_file_cache"))

    # --- load_file_cache -> None (cache-miss) ---------------------------

    def test_load_file_cache_failure_returns_none(self):
        cm = self._create_cache_manager(self._broken_backend("load_file_cache"))
        result = cm.load_file_cache("a.h", "hash")
        self.assertIsNone(result)

    def test_load_file_cache_success_returns_dict(self):
        backend = Mock()
        backend.close = Mock()
        backend.load_file_cache = Mock(return_value={"symbols": [], "file_hash": "hash"})
        cm = self._create_cache_manager(backend)
        self.assertEqual(cm.load_file_cache("a.h", "hash"), {"symbols": [], "file_hash": "hash"})

    def test_load_file_cache_success_miss_returns_none(self):
        backend = Mock()
        backend.close = Mock()
        backend.load_file_cache = Mock(return_value=None)
        cm = self._create_cache_manager(backend)
        self.assertIsNone(cm.load_file_cache("a.h", "hash"))
        self.assertFalse(cm.is_degraded("load_file_cache"))

    def test_load_file_cache_failure_logs_warning(self):
        from clang_index_mcp._core import diagnostics

        cm = self._create_cache_manager(self._broken_backend("load_file_cache", OSError("disk down")))
        with unittest.mock.patch.object(diagnostics, "warning") as mock_warning:
            cm.load_file_cache("a.h", "hash")
        messages = " ".join(str(call.args[0]) for call in mock_warning.call_args_list)
        self.assertIn("load_file_cache failed", messages)
        self.assertIn("OSError", messages)

    # --- remove_file_cache -> False ------------------------------------

    def test_remove_file_cache_failure_returns_false(self):
        cm = self._create_cache_manager(self._broken_backend("remove_file_cache"))
        result = cm.remove_file_cache("a.h")
        self.assertIs(result, False)
        self.assertIsInstance(result, bool)

    def test_remove_file_cache_success_returns_backend_value(self):
        backend = Mock()
        backend.close = Mock()
        backend.remove_file_cache = Mock(return_value=True)
        cm = self._create_cache_manager(backend)
        self.assertIs(cm.remove_file_cache("a.h"), True)

    # --- ensure_schema_current -> False --------------------------------

    def test_ensure_schema_current_failure_returns_false(self):
        cm = self._create_cache_manager(self._broken_backend("ensure_schema_current"))
        result = cm.ensure_schema_current()
        self.assertIs(result, False)
        self.assertIsInstance(result, bool)

    def test_ensure_schema_current_success_returns_backend_value(self):
        backend = Mock()
        backend.close = Mock()
        backend.ensure_schema_current = Mock(return_value=True)
        cm = self._create_cache_manager(backend)
        self.assertIs(cm.ensure_schema_current(), True)

    def test_ensure_schema_current_already_current_returns_false(self):
        backend = Mock()
        backend.close = Mock()
        backend.ensure_schema_current = Mock(return_value=False)
        cm = self._create_cache_manager(backend)
        self.assertIs(cm.ensure_schema_current(), False)

    # --- no exception escapes -------------------------------------------

    def test_no_exception_escapes_protected_methods(self):
        error = RuntimeError("exploded")
        backend = Mock()
        backend.close = Mock()
        for name in (
            "save_file_cache",
            "load_file_cache",
            "remove_file_cache",
            "ensure_schema_current",
        ):
            setattr(backend, name, Mock(side_effect=error))
        cm = self._create_cache_manager(backend)

        self.assertIs(cm.save_file_cache("a.h", [], "h"), False)
        self.assertIsNone(cm.load_file_cache("a.h", "h"))
        self.assertIs(cm.remove_file_cache("a.h"), False)
        self.assertIs(cm.ensure_schema_current(), False)

        summary = cm.get_error_summary()
        self.assertEqual(summary["total_errors"], 4)
        self.assertIsNotNone(summary["last_error"])


def _is_self_backend_load(node: ast.AST) -> bool:
    """True for Load-context ``self.backend`` attribute accesses."""
    return (
        isinstance(node, ast.Attribute)
        and node.attr == "backend"
        and isinstance(node.value, ast.Name)
        and node.value.id == "self"
        and isinstance(node.ctx, ast.Load)
    )


def _is_safe_backend_call(node: ast.AST) -> bool:
    """True for ``self._safe_backend_call(...)`` calls."""
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "_safe_backend_call"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "self"
    )


def _inside_safe_backend_call(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> bool:
    """True when node sits inside a ``self._safe_backend_call`` argument tree.

    Covers direct method references (``self.backend.save_cache`` as ``func``)
    and lambda bodies (``lambda: self.backend.foo(...)``).
    """
    current: ast.AST | None = node
    while current is not None:
        parent = parents.get(current)
        if parent is not None and _is_safe_backend_call(parent):
            # Reached the wrapper call by walking up from the access, so the
            # path went through args/keywords (func is ``self._safe_backend_call``).
            return True
        current = parent
    return False


class TestBackendCallRoutingMeta(unittest.TestCase):
    """AST enforcement: no self.backend access bypasses the error wrapper."""

    def test_every_self_backend_access_is_wrapped(self):
        source = CACHE_MANAGER_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source)

        parents: dict[ast.AST, ast.AST] = {}
        for parent in ast.walk(tree):
            for child in ast.iter_child_nodes(parent):
                parents[child] = parent

        violations: list[str] = []
        for node in ast.walk(tree):
            if not _is_self_backend_load(node):
                continue
            if _inside_safe_backend_call(node, parents):
                continue
            violations.append(f"line {getattr(node, 'lineno', '?')}: {ast.dump(node)}")

        self.assertEqual(
            violations,
            [],
            "self.backend Load outside _safe_backend_call (REQ-6.8.7):\n"
            + "\n".join(violations),
        )

    def test_meta_test_detects_a_bypass(self):
        """Sanity-check the walker: an unprotected access must be flagged."""
        bad = ast.parse(
            "class C:\n"
            "    def f(self):\n"
            "        return self.backend.load_file_cache('a', 'h')\n"
        )
        parents: dict[ast.AST, ast.AST] = {}
        for parent in ast.walk(bad):
            for child in ast.iter_child_nodes(parent):
                parents[child] = parent

        loads = [n for n in ast.walk(bad) if _is_self_backend_load(n)]
        self.assertEqual(len(loads), 1)
        self.assertFalse(_inside_safe_backend_call(loads[0], parents))

    def test_meta_test_accepts_lambda_and_method_ref(self):
        good = ast.parse(
            "class C:\n"
            "    def f(self):\n"
            "        return self._safe_backend_call('op', self.backend.load_file_cache)\n"
            "    def g(self):\n"
            "        return self._safe_backend_call('op', lambda: self.backend.save_file_cache())\n"
        )
        parents: dict[ast.AST, ast.AST] = {}
        for parent in ast.walk(good):
            for child in ast.iter_child_nodes(parent):
                parents[child] = parent

        loads = [n for n in ast.walk(good) if _is_self_backend_load(n)]
        self.assertEqual(len(loads), 2)
        for load in loads:
            self.assertTrue(_inside_safe_backend_call(load, parents))


if __name__ == "__main__":
    unittest.main()
