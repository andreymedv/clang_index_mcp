"""
Typed safe-value mapping for CacheManager wrappers (epic clang_index_mcp-ent,
child .4, REQ-6.8.4).

Each of the eight _safe_backend_call wrappers must return its declared safe
value on backend failure — never leak None into non-Optional returns — and
mark the error-state channel so "empty" can be told from "unavailable".
"""

import os
import shutil
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path
from unittest.mock import Mock

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from clang_index_mcp._persistence.cache_manager import CacheManager
from clang_index_mcp._persistence.error_tracking_adapter import ErrorTrackingAdapter
from clang_index_mcp._symbols.ports.parser import TypeAliasRecord


def _alias(name: str = "Alias", canonical: str = "int") -> TypeAliasRecord:
    return TypeAliasRecord(
        alias_name=name,
        qualified_name=name,
        target_type=canonical,
        canonical_type=canonical,
        file="a.h",
        line=1,
        column=1,
        alias_kind="using",
        namespace="",
        is_template_alias=False,
    )


class TestWrapperSafeValueMapping(unittest.TestCase):
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

    # --- #1 save_cache -> False -----------------------------------------

    def test_save_cache_failure_returns_false(self):
        cm = self._create_cache_manager(self._broken_backend("save_cache"))
        result = cm.save_cache(
            class_index={}, function_index={}, file_hashes={}, indexed_file_count=0
        )
        self.assertIs(result, False)
        self.assertIsInstance(result, bool)

    def test_save_cache_success_returns_backend_value(self):
        backend = Mock()
        backend.close = Mock()
        backend.save_cache = Mock(return_value=True)
        cm = self._create_cache_manager(backend)
        result = cm.save_cache(
            class_index={}, function_index={}, file_hashes={}, indexed_file_count=0
        )
        self.assertIs(result, True)

    # --- #2 load_cache -> None (cache-miss) -----------------------------

    def test_load_cache_failure_returns_none(self):
        cm = self._create_cache_manager(self._broken_backend("load_cache"))
        result = cm.load_cache()
        self.assertIsNone(result)

    def test_load_cache_success_returns_dict(self):
        backend = Mock()
        backend.close = Mock()
        backend.load_cache = Mock(return_value={"file_hashes": {}})
        cm = self._create_cache_manager(backend)
        self.assertEqual(cm.load_cache(), {"file_hashes": {}})

    def test_load_cache_success_miss_returns_none(self):
        backend = Mock()
        backend.close = Mock()
        backend.load_cache = Mock(return_value=None)
        cm = self._create_cache_manager(backend)
        self.assertIsNone(cm.load_cache())

    def test_load_cache_failure_logs_warning(self):
        from clang_index_mcp._core import diagnostics

        cm = self._create_cache_manager(self._broken_backend("load_cache", OSError("disk down")))
        with unittest.mock.patch.object(diagnostics, "warning") as mock_warning:
            cm.load_cache()
        messages = " ".join(str(call.args[0]) for call in mock_warning.call_args_list)
        self.assertIn("load_cache failed", messages)
        self.assertIn("OSError", messages)

    # --- #3 save_type_aliases_batch -> 0 --------------------------------

    def test_save_type_aliases_batch_failure_returns_zero(self):
        cm = self._create_cache_manager(self._broken_backend("save_type_aliases_batch"))
        result = cm.save_type_aliases_batch([_alias()])
        self.assertEqual(result, 0)
        self.assertIsInstance(result, int)

    def test_save_type_aliases_batch_success_returns_count(self):
        backend = Mock()
        backend.close = Mock()
        backend.save_type_aliases_batch = Mock(return_value=2)
        cm = self._create_cache_manager(backend)
        self.assertEqual(cm.save_type_aliases_batch([_alias(), _alias("B", "float")]), 2)

    def test_save_type_aliases_batch_failure_logs_lost_count(self):
        from clang_index_mcp._core import diagnostics

        cm = self._create_cache_manager(
            self._broken_backend("save_type_aliases_batch", OSError("disk full"))
        )
        with unittest.mock.patch.object(diagnostics, "warning") as mock_warning:
            cm.save_type_aliases_batch([_alias(), _alias("B")])
        messages = " ".join(str(call.args[0]) for call in mock_warning.call_args_list)
        self.assertIn("save_type_aliases_batch failed", messages)
        self.assertIn("2 aliases not persisted", messages)

    # --- #4 get_aliases_for_canonical -> [] -----------------------------

    def test_get_aliases_for_canonical_failure_returns_empty_list(self):
        cm = self._create_cache_manager(self._broken_backend("get_aliases_for_canonical"))
        result = cm.get_aliases_for_canonical("int")
        self.assertEqual(result, [])
        self.assertIsInstance(result, list)

    def test_get_aliases_for_canonical_success_returns_names(self):
        backend = Mock()
        backend.close = Mock()
        backend.get_aliases_for_canonical = Mock(return_value=["A", "B"])
        cm = self._create_cache_manager(backend)
        self.assertEqual(cm.get_aliases_for_canonical("int"), ["A", "B"])

    # --- #5 get_canonical_for_alias -> None + degraded ------------------

    def test_get_canonical_for_alias_failure_returns_none_and_marks_degraded(self):
        cm = self._create_cache_manager(self._broken_backend("get_canonical_for_alias"))
        result = cm.get_canonical_for_alias("Missing")
        self.assertIsNone(result)
        self.assertTrue(cm.is_degraded("get_canonical_for_alias"))
        self.assertIsNotNone(cm.last_error_for("get_canonical_for_alias"))
        self.assertTrue(cm.get_error_summary()["degraded"]["read"])

    def test_get_canonical_for_alias_success_not_found_is_not_degraded(self):
        backend = Mock()
        backend.close = Mock()
        backend.get_canonical_for_alias = Mock(return_value=None)
        cm = self._create_cache_manager(backend)
        self.assertIsNone(cm.get_canonical_for_alias("Missing"))
        self.assertFalse(cm.is_degraded("get_canonical_for_alias"))

    def test_get_canonical_for_alias_success_after_failure_clears_degraded(self):
        backend = self._broken_backend("get_canonical_for_alias")
        cm = self._create_cache_manager(backend)
        cm.get_canonical_for_alias("A")
        self.assertTrue(cm.is_degraded("get_canonical_for_alias"))

        backend.get_canonical_for_alias = Mock(return_value="int")
        self.assertEqual(cm.get_canonical_for_alias("A"), "int")
        self.assertFalse(cm.is_degraded("get_canonical_for_alias"))

    # --- #6 get_type_alias_info -> None + degraded ----------------------

    def test_get_type_alias_info_failure_returns_none_and_marks_degraded(self):
        cm = self._create_cache_manager(self._broken_backend("get_type_alias_info"))
        result = cm.get_type_alias_info("Foo")
        self.assertIsNone(result)
        self.assertTrue(cm.is_degraded("get_type_alias_info"))
        self.assertIsNotNone(cm.last_error_for("get_type_alias_info"))

    def test_get_type_alias_info_success_returns_dict(self):
        backend = Mock()
        backend.close = Mock()
        backend.get_type_alias_info = Mock(return_value={"canonical_type": "int"})
        cm = self._create_cache_manager(backend)
        self.assertEqual(cm.get_type_alias_info("Foo"), {"canonical_type": "int"})

    def test_get_type_alias_info_success_after_failure_clears_degraded(self):
        backend = self._broken_backend("get_type_alias_info")
        cm = self._create_cache_manager(backend)
        cm.get_type_alias_info("Foo")
        self.assertTrue(cm.is_degraded("get_type_alias_info"))

        backend.get_type_alias_info = Mock(return_value={"canonical_type": "int"})
        cm.get_type_alias_info("Foo")
        self.assertFalse(cm.is_degraded("get_type_alias_info"))

    # --- #7 get_type_alias_details -> [] --------------------------------

    def test_get_type_alias_details_failure_returns_empty_list(self):
        cm = self._create_cache_manager(self._broken_backend("get_type_alias_details"))
        result = cm.get_type_alias_details(["A"])
        self.assertEqual(result, [])
        self.assertIsInstance(result, list)

    def test_get_type_alias_details_success_returns_records(self):
        backend = Mock()
        backend.close = Mock()
        backend.get_type_alias_details = Mock(return_value=[{"alias_name": "A"}])
        cm = self._create_cache_manager(backend)
        self.assertEqual(cm.get_type_alias_details(["A"]), [{"alias_name": "A"}])

    # --- #8 get_all_alias_mappings -> {} --------------------------------

    def test_get_all_alias_mappings_failure_returns_empty_dict(self):
        cm = self._create_cache_manager(self._broken_backend("get_all_alias_mappings"))
        result = cm.get_all_alias_mappings()
        self.assertEqual(result, {})
        self.assertIsInstance(result, dict)

    def test_get_all_alias_mappings_success_returns_mappings(self):
        backend = Mock()
        backend.close = Mock()
        backend.get_all_alias_mappings = Mock(return_value={"A": "int"})
        cm = self._create_cache_manager(backend)
        self.assertEqual(cm.get_all_alias_mappings(), {"A": "int"})

    # --- no exception escapes any wrapper -------------------------------

    def test_no_wrapper_raises_on_backend_failure(self):
        error = RuntimeError("exploded")
        backend = Mock()
        backend.close = Mock()
        for name in (
            "save_cache",
            "load_cache",
            "save_type_aliases_batch",
            "get_aliases_for_canonical",
            "get_canonical_for_alias",
            "get_type_alias_info",
            "get_type_alias_details",
            "get_all_alias_mappings",
        ):
            setattr(backend, name, Mock(side_effect=error))
        cm = self._create_cache_manager(backend)

        cm.save_cache(class_index={}, function_index={}, file_hashes={}, indexed_file_count=0)
        self.assertIsNone(cm.load_cache())
        self.assertEqual(cm.save_type_aliases_batch([_alias()]), 0)
        self.assertEqual(cm.get_aliases_for_canonical("int"), [])
        self.assertIsNone(cm.get_canonical_for_alias("A"))
        self.assertIsNone(cm.get_type_alias_info("A"))
        self.assertEqual(cm.get_type_alias_details(["A"]), [])
        self.assertEqual(cm.get_all_alias_mappings(), {})

    # --- all failures counted in the error summary -----------------------

    def test_failures_counted_in_error_summary(self):
        backend = Mock()
        backend.close = Mock()
        for name in (
            "save_cache",
            "load_cache",
            "save_type_aliases_batch",
            "get_aliases_for_canonical",
            "get_canonical_for_alias",
            "get_type_alias_info",
            "get_type_alias_details",
            "get_all_alias_mappings",
        ):
            setattr(backend, name, Mock(side_effect=OSError("down")))
        cm = self._create_cache_manager(backend)

        cm.save_cache(class_index={}, function_index={}, file_hashes={}, indexed_file_count=0)
        cm.load_cache()
        cm.save_type_aliases_batch([])
        cm.get_aliases_for_canonical("int")
        cm.get_canonical_for_alias("A")
        cm.get_type_alias_info("A")
        cm.get_type_alias_details([])
        cm.get_all_alias_mappings()

        summary = cm.get_error_summary()
        self.assertEqual(summary["total_errors"], 8)
        self.assertIsNotNone(summary["last_error"])


if __name__ == "__main__":
    unittest.main()
