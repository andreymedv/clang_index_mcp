"""
MCP Testing Skill - Main Entry Point

Usage:
    /test-mcp list-projects
    /test-mcp test=<scenario> [tier=1|2] [protocol=sse]
    /test-mcp setup-project url=<url> [name=<name>] [commit=<tag>]
"""

import sys
import argparse
from pathlib import Path

# Add skill directory to path for imports
SKILL_DIR = Path(__file__).parent
sys.path.insert(0, str(SKILL_DIR))

from project_manager import ProjectManager
from test_runner import TestRunner


def main():
    """Main entry point for the skill"""
    parser = argparse.ArgumentParser(
        description="MCP Server Testing Skill",
        usage="%(prog)s <command> [options]"
    )

    parser.add_argument(
        "command",
        nargs="?",
        default="help",
        help="Command to execute"
    )

    # Parse known args to allow flexible parameter passing
    args, unknown = parser.parse_known_args()

    # Parse remaining args as key=value pairs
    params = {}
    for arg in unknown:
        if "=" in arg:
            key, value = arg.split("=", 1)
            params[key] = value

    # Route to appropriate handler
    if args.command == "list-projects":
        handle_list_projects(params)
    elif args.command == "test":
        handle_test(params)
    elif args.command == "setup-project":
        handle_setup_project(params)
    elif args.command == "validate-project":
        handle_validate_project(params)
    elif args.command == "remove-project":
        handle_remove_project(params)
    elif args.command == "help":
        show_help()
    else:
        print(f"Unknown command: {args.command}")
        print("Run '/test-mcp help' for usage information")
        sys.exit(1)


def handle_list_projects(params):
    """List available test projects"""
    pm = ProjectManager()
    projects = pm.list_projects()

    if not projects:
        print("No test projects configured")
        print("\nUse '/test-mcp setup-project' to add a project")
        return

    print("Available test projects:")
    for name, info in projects.items():
        project_type = info.get("type", "unknown")
        file_count = info.get("file_count", "?")
        compile_commands = "✓" if info.get("compile_commands") else "✗"

        print(f"  {name}: {info['path']}")
        print(f"         ~{file_count} files, compile_commands.json: {compile_commands}")


def handle_test(params):
    """Run a test scenario"""
    test_name = params.get("test")
    if not test_name:
        print("Error: test parameter required")
        print("Usage: /test-mcp test=<scenario> [tier=1|2] [protocol=sse]")
        sys.exit(1)

    tier = params.get("tier", "1")
    protocol = params.get("protocol", "sse")
    project = params.get("project")

    # Determine project from tier if not explicitly specified
    if not project:
        if tier == "1":
            project = "tier1"
        elif tier == "2":
            project = "tier2"
        else:
            print(f"Error: Invalid tier '{tier}'. Use tier=1 or tier=2")
            sys.exit(1)

    runner = TestRunner()
    result = runner.run_test(
        test_name=test_name,
        project=project,
        protocol=protocol
    )

    # Output result (formatted by TestRunner)
    print(result)


def handle_setup_project(params):
    """Setup a new test project"""
    url = params.get("url")
    if not url:
        print("Error: url parameter required")
        print("Usage: /test-mcp setup-project url=<github-url> [name=<name>] [commit=<hash>] [tag=<tag>]")
        sys.exit(1)

    name = params.get("name")
    commit = params.get("commit")
    tag = params.get("tag")
    build_dir = params.get("build-dir", "build")

    print(f"\nSetting up project from {url}...")
    if name:
        print(f"Project name: {name}")
    if commit:
        print(f"Commit: {commit}")
    if tag:
        print(f"Tag: {tag}")
    print()

    pm = ProjectManager()
    success, message, project_name = pm.setup_project(
        url=url,
        name=name,
        commit=commit,
        tag=tag,
        build_dir=build_dir
    )

    if success:
        print(f"\n✓ {message}")
        print(f"\nYou can now run tests on this project:")
        print(f"  /test-mcp test=basic-indexing project={project_name}")
    else:
        print(f"\n✗ Setup failed: {message}")
        sys.exit(1)


def handle_validate_project(params):
    """Validate a test project"""
    project_name = params.get("project")
    if not project_name:
        print("Error: project parameter required")
        sys.exit(1)

    pm = ProjectManager()
    is_valid, issues = pm.validate_project(project_name)

    if is_valid:
        print(f"✓ Project '{project_name}' validation: READY")
    else:
        print(f"✗ Project '{project_name}' validation: FAILED")
        for issue in issues:
            print(f"  - {issue}")


def handle_remove_project(params):
    """Remove a test project"""
    project_name = params.get("project")
    if not project_name:
        print("Error: project parameter required")
        print("Usage: /test-mcp remove-project project=<name> [delete=yes]")
        sys.exit(1)

    delete_files = params.get("delete", "").lower() in ["yes", "true", "1"]

    pm = ProjectManager()
    project = pm.get_project(project_name)

    if not project:
        print(f"✗ Project '{project_name}' not found in registry")
        sys.exit(1)

    # Confirm deletion if delete_files is true
    if delete_files:
        print(f"\n⚠️  WARNING: This will delete all project files!")
        print(f"   Path: {project['path']}")
        print(f"   Size: {project.get('disk_usage_mb', '?')} MB")
        print(f"\nAre you sure? (yes/no): ", end="")
        confirmation = input().strip().lower()
        if confirmation != "yes":
            print("Cancelled")
            return

    success, message = pm.remove_project(project_name, delete_files=delete_files)

    if success:
        print(f"✓ {message}")
        if delete_files:
            print("  Files deleted")
        else:
            print("  Files preserved (use delete=yes to remove)")
    else:
        print(f"✗ {message}")
        sys.exit(1)


def show_help():
    """Show help information"""
    help_text = """
MCP Testing Skill - Help

Commands:
  list-projects              List available test projects
  test=<scenario>            Run a test scenario
  setup-project              Setup a new test project (clone from GitHub)
  validate-project           Validate a test project
  remove-project             Remove a test project from registry
  help                       Show this help

Examples:
  /test-mcp list-projects
  /test-mcp test=basic-indexing tier=1
  /test-mcp test=issue-13 tier=2 protocol=sse
  /test-mcp validate-project project=tier1
  /test-mcp setup-project url=https://github.com/user/repo name=myproject
  /test-mcp remove-project project=myproject delete=yes

Available test scenarios:
  Phase 1:
  - basic-indexing: Quick smoke test on small project
  - issue-13: Reproduce Issue #13 (boost headers)

  Phase 3:
  - incremental-refresh: Test incremental analysis after file changes
  - all-protocols: Verify all transport protocols work

Available protocols:
  - sse: Server-Sent Events (recommended for testing)
  - stdio: Standard I/O (production mode)
  - http: HTTP REST-like (alternative)

For full documentation, see:
  docs/MCP_TESTING_SKILL.md
"""
    print(help_text)


if __name__ == "__main__":
    main()
