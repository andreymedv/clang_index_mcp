"""
Project Manager - Manages test project registry and validation
"""

import json
import os
import subprocess
import shutil
from pathlib import Path
from datetime import datetime
from typing import Dict, Tuple, List, Optional


class ProjectManager:
    """Manages test project registry and operations"""

    def __init__(self, registry_path: Optional[Path] = None) -> None:
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
                        "path": "/home/andrey/ProjectName",
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

    def list_projects(self) -> Dict:
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

    def get_project(self, name: str) -> Optional[Dict]:
        """
        Get project info by name

        Args:
            name: Project name

        Returns:
            dict: Project info or None if not found
        """
        projects = self.list_projects()
        return projects.get(name)

    def validate_project(self, name: str) -> Tuple[bool, List[str]]:
        """
        Validate a project's configuration

        Args:
            name: Project name

        Returns:
            tuple: (is_valid, list of issues)
        """
        project = self.get_project(name)
        if not project:
            return False, [
                f"Project '{name}' not found in registry",
                "  Hint: Run '/test-mcp list-projects' to see available projects"
            ]

        issues = []

        # Check directory exists
        project_path = Path(project["path"])
        if not project_path.exists():
            issues.append(f"Directory does not exist: {project_path}")
            issues.append(f"  Hint: Either restore the directory or remove project with '/test-mcp remove-project project={name}'")

        # Check compile_commands.json exists
        compile_commands_path = project_path / project["compile_commands"]
        if not compile_commands_path.exists():
            issues.append(f"compile_commands.json not found: {compile_commands_path}")
            if Path(project_path / "CMakeLists.txt").exists():
                issues.append(f"  Hint: Run 'cmake -B build -DCMAKE_EXPORT_COMPILE_COMMANDS=ON' in {project_path}")
            else:
                issues.append(f"  Hint: Check compile_commands path in registry or create it manually")
        else:
            # Validate it's valid JSON
            try:
                with open(compile_commands_path, "r") as f:
                    json.load(f)
            except json.JSONDecodeError:
                issues.append(f"compile_commands.json is not valid JSON")
                issues.append(f"  Hint: Regenerate compile_commands.json with cmake or check for corruption")

        # Check for C++ files
        if project_path.exists():
            cpp_files = list(project_path.rglob("*.cpp")) + list(project_path.rglob("*.cc"))
            if not cpp_files:
                issues.append("No C++ source files found")
                issues.append(f"  Hint: Verify project path is correct or check if files have different extensions (.cxx, .c++)")

        # Update last_validated timestamp if valid
        if not issues:
            self._update_project_timestamp(name, "last_validated")

        return len(issues) == 0, issues

    def _update_project_timestamp(self, name: str, field: str) -> None:
        """Update timestamp field for a project"""
        if not self.registry_path.exists():
            return

        with open(self.registry_path, "r") as f:
            registry = json.load(f)

        if name in registry.get("projects", {}):
            registry["projects"][name][field] = datetime.now().isoformat()

            with open(self.registry_path, "w") as f:
                json.dump(registry, f, indent=2)

    def mark_project_used(self, name: str) -> None:
        """Mark project as recently used"""
        self._update_project_timestamp(name, "last_used")

    def setup_project(
        self,
        url: str,
        name: Optional[str] = None,
        commit: Optional[str] = None,
        tag: Optional[str] = None,
        build_dir: str = "build"
    ) -> Tuple[bool, str, str]:
        """
        Clone and configure a project from GitHub

        Args:
            url: GitHub repository URL
            name: Project name (default: derived from URL)
            commit: Specific commit hash to checkout
            tag: Specific tag to checkout (alternative to commit)
            build_dir: Build directory name (default: "build")

        Returns:
            tuple: (success, message, project_name)
        """
        # Import here to avoid circular imports
        import sys
        from pathlib import Path

        # Add utils to path
        skill_dir = Path(__file__).parent
        sys.path.insert(0, str(skill_dir))
        from utils.cmake_helper import CMakeHelper

        # Derive project name from URL if not provided
        if not name:
            # Extract name from URL (e.g., github.com/user/repo.git -> repo)
            name = url.rstrip("/").split("/")[-1].replace(".git", "")

        # Check if project already exists
        if self.get_project(name):
            return False, (
                f"Project '{name}' already exists in registry\n"
                f"  Hint: Use '/test-mcp remove-project project={name}' to remove it first\n"
                f"        or choose a different name with 'name=different-name'"
            ), name

        # Determine clone destination
        clone_dest = self.registry_path.parent / name

        # Check if git is available
        if not shutil.which("git"):
            return False, (
                "git not found in PATH\n"
                "  Hint: Install git:\n"
                "    Ubuntu/Debian: sudo apt-get install git\n"
                "    macOS: brew install git\n"
                "    Windows: download from https://git-scm.com/"
            ), name

        # Clone repository
        print(f"Cloning {url} to {clone_dest}...")
        try:
            clone_cmd = ["git", "clone", url, str(clone_dest)]
            result = subprocess.run(
                clone_cmd,
                capture_output=True,
                text=True,
                timeout=300  # 5 minute timeout
            )

            if result.returncode != 0:
                error_msg = result.stderr or result.stdout
                return False, (
                    f"Git clone failed:\n{error_msg}\n"
                    f"  Hint: Check if:\n"
                    f"    - URL is correct and accessible\n"
                    f"    - Repository is public or you have access\n"
                    f"    - Network connection is working"
                ), name

        except subprocess.TimeoutExpired:
            return False, (
                "Git clone timed out (>5 minutes)\n"
                "  Hint: Repository may be too large or network is slow\n"
                "        Try cloning manually first"
            ), name
        except Exception as e:
            return False, f"Git clone error: {e}", name

        # Checkout specific commit/tag if specified
        if commit or tag:
            ref = commit or tag
            print(f"Checking out {ref}...")
            try:
                checkout_cmd = ["git", "checkout", ref]
                result = subprocess.run(
                    checkout_cmd,
                    cwd=clone_dest,
                    capture_output=True,
                    text=True,
                    timeout=30
                )

                if result.returncode != 0:
                    error_msg = result.stderr or result.stdout
                    # Cleanup on failure
                    shutil.rmtree(clone_dest)
                    return False, f"Git checkout failed:\n{error_msg}", name

            except Exception as e:
                # Cleanup on failure
                shutil.rmtree(clone_dest)
                return False, f"Git checkout error: {e}", name

        # Get current commit hash
        try:
            result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=clone_dest,
                capture_output=True,
                text=True
            )
            commit_hash = result.stdout.strip()
        except Exception:
            commit_hash = "unknown"

        # Detect CMake and configure if present
        compile_commands_rel_path = None
        file_count = 0

        if CMakeHelper.detect_cmake_project(clone_dest):
            print("CMakeLists.txt detected, configuring with CMake...")
            success, message, compile_commands_path = CMakeHelper.configure_project(
                clone_dest,
                build_dir=build_dir
            )

            if not success:
                # Cleanup on failure
                shutil.rmtree(clone_dest)
                return False, f"CMake configuration failed: {message}", name

            # Get relative path for compile_commands.json
            compile_commands_rel_path = str(
                compile_commands_path.relative_to(clone_dest)
            )

            # Get file count from compile_commands.json
            file_count = CMakeHelper.get_file_count(compile_commands_path)
            print(f"CMake configuration successful, {file_count} compilation units")

        else:
            print("No CMakeLists.txt found, skipping CMake configuration")

        # Calculate disk usage
        disk_usage_mb = self._get_directory_size(clone_dest)

        # Add to registry
        project_info = {
            "type": "cloned",
            "source_url": url,
            "commit": commit_hash,
            "path": str(clone_dest),
            "compile_commands": compile_commands_rel_path,
            "build_dir": build_dir,
            "file_count": file_count,
            "disk_usage_mb": disk_usage_mb,
            "created": datetime.now().isoformat(),
            "last_validated": datetime.now().isoformat(),
            "last_used": None
        }

        # Add tag if specified
        if tag:
            project_info["tag"] = tag

        # Load registry and add project
        if not self.registry_path.exists():
            registry = {"version": "1.0", "projects": {}}
        else:
            with open(self.registry_path, "r") as f:
                registry = json.load(f)

        registry["projects"][name] = project_info

        with open(self.registry_path, "w") as f:
            json.dump(registry, f, indent=2)

        return True, f"Project '{name}' setup complete ({file_count} files, {disk_usage_mb:.1f} MB)", name

    def remove_project(self, name: str, delete_files: bool = False) -> Tuple[bool, str]:
        """
        Remove a project from registry

        Args:
            name: Project name
            delete_files: If True, delete project files (only for cloned projects)

        Returns:
            tuple: (success, message)
        """
        project = self.get_project(name)
        if not project:
            return False, f"Project '{name}' not found in registry"

        # Check if it's a builtin project
        if project.get("type") == "builtin":
            return False, (
                f"Cannot remove builtin project '{name}'\n"
                f"  Hint: Builtin projects (tier1, tier2) cannot be removed from registry"
            )

        # Delete files if requested (only for cloned projects)
        if delete_files and project.get("type") == "cloned":
            project_path = Path(project["path"])
            if project_path.exists():
                print(f"Deleting project files: {project_path}")
                try:
                    shutil.rmtree(project_path)
                except Exception as e:
                    return False, f"Failed to delete files: {e}"

        # Remove from registry
        with open(self.registry_path, "r") as f:
            registry = json.load(f)

        del registry["projects"][name]

        with open(self.registry_path, "w") as f:
            json.dump(registry, f, indent=2)

        return True, f"Project '{name}' removed from registry"

    def _get_directory_size(self, path: Path) -> float:
        """
        Calculate directory size in MB

        Args:
            path: Directory path

        Returns:
            float: Size in megabytes
        """
        total_size = 0
        path = Path(path)

        try:
            for item in path.rglob("*"):
                if item.is_file():
                    total_size += item.stat().st_size
        except Exception:
            return 0.0

        return total_size / (1024 * 1024)  # Convert to MB
