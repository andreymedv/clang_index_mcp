"""Unit tests for ProjectIdentity class."""

import unittest
from pathlib import Path
import tempfile
import shutil
from mcp_server.project_identity import ProjectIdentity


class TestProjectIdentity(unittest.TestCase):
    """Test cases for ProjectIdentity class."""

    def setUp(self):
        """Set up test fixtures."""
        # Create temporary directory for testing
        self.test_dir = Path(tempfile.mkdtemp())
        self.project1 = self.test_dir / "project1"
        self.project2 = self.test_dir / "project2"
        self.project1.mkdir()
        self.project2.mkdir()

        # Create config files
        self.config1 = self.project1 / "config1.json"
        self.config2 = self.project1 / "config2.json"
        self.config1.write_text("{}")
        self.config2.write_text("{}")

    def tearDown(self):
        """Clean up test fixtures."""
        shutil.rmtree(self.test_dir)

    def test_basic_creation(self):
        """Test basic ProjectIdentity creation."""
        identity = ProjectIdentity(self.project1)

        self.assertEqual(identity.source_directory, self.project1.resolve())
        self.assertIsNone(identity.config_file_path)

    def test_creation_with_config(self):
        """Test ProjectIdentity creation with config file."""
        identity = ProjectIdentity(self.project1, self.config1)

        self.assertEqual(identity.source_directory, self.project1.resolve())
        self.assertEqual(identity.config_file_path, self.config1.resolve())

    def test_path_resolution(self):
        """Test that paths are resolved to absolute."""
        # Use relative path
        import os
        orig_dir = os.getcwd()
        try:
            os.chdir(self.test_dir)
            identity = ProjectIdentity(Path("project1"))

            # Should be resolved to absolute
            self.assertTrue(identity.source_directory.is_absolute())
            self.assertEqual(identity.source_directory, self.project1.resolve())
        finally:
            os.chdir(orig_dir)

    def test_hash_stability(self):
        """Test that hash is stable for same inputs."""
        identity1 = ProjectIdentity(self.project1)
        identity2 = ProjectIdentity(self.project1)

        self.assertEqual(identity1.compute_hash(), identity2.compute_hash())

    def test_hash_uniqueness_different_source(self):
        """Test that different source directories produce different hashes."""
        identity1 = ProjectIdentity(self.project1)
        identity2 = ProjectIdentity(self.project2)

        self.assertNotEqual(identity1.compute_hash(), identity2.compute_hash())

    def test_hash_uniqueness_different_config(self):
        """Test that different config files produce different hashes."""
        identity1 = ProjectIdentity(self.project1, self.config1)
        identity2 = ProjectIdentity(self.project1, self.config2)

        self.assertNotEqual(identity1.compute_hash(), identity2.compute_hash())

    def test_hash_with_and_without_config(self):
        """Test that presence/absence of config affects hash."""
        identity1 = ProjectIdentity(self.project1)
        identity2 = ProjectIdentity(self.project1, self.config1)

        self.assertNotEqual(identity1.compute_hash(), identity2.compute_hash())

    def test_hash_length(self):
        """Test that hash has expected length."""
        identity = ProjectIdentity(self.project1)
        hash_value = identity.compute_hash()

        # Should be 16 hex characters
        self.assertEqual(len(hash_value), 16)
        self.assertTrue(all(c in '0123456789abcdef' for c in hash_value))

    def test_cache_directory_name(self):
        """Test cache directory name generation."""
        identity = ProjectIdentity(self.project1)
        cache_dir_name = identity.get_cache_directory_name()

        # Should be in format: {project_name}_{hash}
        self.assertTrue(cache_dir_name.startswith("project1_"))
        self.assertEqual(len(cache_dir_name), len("project1_") + 16)

    def test_cache_directory_name_with_config(self):
        """Test cache directory name with config file."""
        identity = ProjectIdentity(self.project1, self.config1)
        cache_dir_name = identity.get_cache_directory_name()

        # Should still start with project name
        self.assertTrue(cache_dir_name.startswith("project1_"))

    def test_equality(self):
        """Test equality comparison."""
        identity1 = ProjectIdentity(self.project1, self.config1)
        identity2 = ProjectIdentity(self.project1, self.config1)
        identity3 = ProjectIdentity(self.project1, self.config2)

        self.assertEqual(identity1, identity2)
        self.assertNotEqual(identity1, identity3)

    def test_equality_none_config(self):
        """Test equality with None config."""
        identity1 = ProjectIdentity(self.project1)
        identity2 = ProjectIdentity(self.project1)
        identity3 = ProjectIdentity(self.project1, self.config1)

        self.assertEqual(identity1, identity2)
        self.assertNotEqual(identity1, identity3)

    def test_equality_different_types(self):
        """Test equality with different types."""
        identity = ProjectIdentity(self.project1)

        self.assertNotEqual(identity, "string")
        self.assertNotEqual(identity, 123)
        self.assertNotEqual(identity, None)

    def test_hash_method(self):
        """Test __hash__ method for use in sets/dicts."""
        identity1 = ProjectIdentity(self.project1, self.config1)
        identity2 = ProjectIdentity(self.project1, self.config1)
        identity3 = ProjectIdentity(self.project2)

        # Should be usable in sets
        identity_set = {identity1, identity2, identity3}
        self.assertEqual(len(identity_set), 2)  # identity1 and identity2 are equal

        # Should be usable as dict keys
        identity_dict = {identity1: "value1", identity3: "value2"}
        self.assertEqual(identity_dict[identity2], "value1")  # identity2 == identity1

    def test_repr(self):
        """Test __repr__ method."""
        identity = ProjectIdentity(self.project1, self.config1)
        repr_str = repr(identity)

        self.assertIn("ProjectIdentity", repr_str)
        self.assertIn("source=", repr_str)
        self.assertIn("config=", repr_str)
        self.assertIn("hash=", repr_str)

    def test_str(self):
        """Test __str__ method."""
        identity1 = ProjectIdentity(self.project1)
        str1 = str(identity1)
        self.assertIn(str(self.project1), str1)

        identity2 = ProjectIdentity(self.project1, self.config1)
        str2 = str(identity2)
        self.assertIn(str(self.project1), str2)
        self.assertIn(str(self.config1), str2)

    def test_to_dict(self):
        """Test to_dict serialization."""
        identity = ProjectIdentity(self.project1, self.config1)
        data = identity.to_dict()

        self.assertIn("source_directory", data)
        self.assertIn("config_file_path", data)
        self.assertIn("hash", data)
        self.assertIn("cache_directory", data)

        self.assertEqual(data["source_directory"], str(self.project1.resolve()))
        self.assertEqual(data["config_file_path"], str(self.config1.resolve()))
        self.assertEqual(data["hash"], identity.compute_hash())
        self.assertEqual(data["cache_directory"], identity.get_cache_directory_name())

    def test_to_dict_no_config(self):
        """Test to_dict with no config file."""
        identity = ProjectIdentity(self.project1)
        data = identity.to_dict()

        self.assertIsNone(data["config_file_path"])

    def test_from_dict(self):
        """Test from_dict deserialization."""
        original = ProjectIdentity(self.project1, self.config1)
        data = original.to_dict()

        restored = ProjectIdentity.from_dict(data)

        self.assertEqual(restored, original)
        self.assertEqual(restored.compute_hash(), original.compute_hash())

    def test_from_dict_no_config(self):
        """Test from_dict with no config file."""
        original = ProjectIdentity(self.project1)
        data = original.to_dict()

        restored = ProjectIdentity.from_dict(data)

        self.assertEqual(restored, original)
        self.assertIsNone(restored.config_file_path)

    def test_roundtrip_serialization(self):
        """Test complete serialization roundtrip."""
        original = ProjectIdentity(self.project1, self.config1)

        # Serialize and deserialize
        data = original.to_dict()
        restored = ProjectIdentity.from_dict(data)

        # Should be identical
        self.assertEqual(restored.source_directory, original.source_directory)
        self.assertEqual(restored.config_file_path, original.config_file_path)
        self.assertEqual(restored.compute_hash(), original.compute_hash())
        self.assertEqual(restored.get_cache_directory_name(), original.get_cache_directory_name())


if __name__ == '__main__':
    unittest.main()
