"""
Project Manager - Manages test project registry and validation
"""

import json
import os
from pathlib import Path
from datetime import datetime


class ProjectManager:
    """Manages test project registry and operations"""

    def __init__(self, registry_path=None):
        """
        Initialize ProjectManager

        Args:
            registry_path: Path to registry.json (default: .test-projects/registry.json)
        """
        if registry_path is None:
            # Default to .test-projects/registry.json in repo root
            repo_root = Path(__file__).parent.parent.parent.parent
            self.registry_path = repo_root / ".test-projects" / "registry.json"
        else:
            self.registry_path = Path(registry_path)

        self.registry_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize_builtin_projects()

    def _initialize_builtin_projects(self):
        """Initialize registry with builtin projects if not exists"""
        if not self.registry_path.exists():
            # Create default registry with tier1 and tier2
            repo_root = self.registry_path.parent.parent

            default_registry = {
                "version": "1.0",
                "projects": {
                    "tier1": {
                        "type": "builtin",
                        "path": str(repo_root / "examples" / "compile_commands_example"),
                        "compile_commands": "compile_commands.json",
                        "file_count": 18,
                        "created": datetime.now().isoformat(),
                        "last_validated": None,
                        "last_used": None
                    },
                    "tier2": {
                        "type": "builtin",
                        "path": "/home/andrey/myoffice",
                        "compile_commands": "build.debug/compile_commands.json",
                        "file_count": 5700,
                        "created": datetime.now().isoformat(),
                        "last_validated": None,
                        "last_used": None
                    }
                }
            }

            with open(self.registry_path, "w") as f:
                json.dump(default_registry, f, indent=2)

    def list_projects(self):
        """
        List all registered projects

        Returns:
            dict: Project registry
        """
        if not self.registry_path.exists():
            return {}

        with open(self.registry_path, "r") as f:
            registry = json.load(f)

        return registry.get("projects", {})

    def get_project(self, name):
        """
        Get project info by name

        Args:
            name: Project name

        Returns:
            dict: Project info or None if not found
        """
        projects = self.list_projects()
        return projects.get(name)

    def validate_project(self, name):
        """
        Validate a project's configuration

        Args:
            name: Project name

        Returns:
            tuple: (is_valid, list of issues)
        """
        project = self.get_project(name)
        if not project:
            return False, [f"Project '{name}' not found in registry"]

        issues = []

        # Check directory exists
        project_path = Path(project["path"])
        if not project_path.exists():
            issues.append(f"Directory does not exist: {project_path}")

        # Check compile_commands.json exists
        compile_commands_path = project_path / project["compile_commands"]
        if not compile_commands_path.exists():
            issues.append(f"compile_commands.json not found: {compile_commands_path}")
        else:
            # Validate it's valid JSON
            try:
                with open(compile_commands_path, "r") as f:
                    json.load(f)
            except json.JSONDecodeError:
                issues.append(f"compile_commands.json is not valid JSON")

        # Check for C++ files
        if project_path.exists():
            cpp_files = list(project_path.rglob("*.cpp")) + list(project_path.rglob("*.cc"))
            if not cpp_files:
                issues.append("No C++ source files found")

        # Update last_validated timestamp if valid
        if not issues:
            self._update_project_timestamp(name, "last_validated")

        return len(issues) == 0, issues

    def _update_project_timestamp(self, name, field):
        """Update timestamp field for a project"""
        if not self.registry_path.exists():
            return

        with open(self.registry_path, "r") as f:
            registry = json.load(f)

        if name in registry.get("projects", {}):
            registry["projects"][name][field] = datetime.now().isoformat()

            with open(self.registry_path, "w") as f:
                json.dump(registry, f, indent=2)

    def mark_project_used(self, name):
        """Mark project as recently used"""
        self._update_project_timestamp(name, "last_used")
