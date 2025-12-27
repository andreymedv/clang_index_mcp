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
    print("⚠️  setup-project not implemented yet (Phase 2)")
    print("Currently using builtin projects: tier1, tier2")


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


def show_help():
    """Show help information"""
    help_text = """
MCP Testing Skill - Help

Commands:
  list-projects              List available test projects
  test=<scenario>            Run a test scenario
  setup-project              Setup a new test project (Phase 2)
  validate-project           Validate a test project
  help                       Show this help

Examples:
  /test-mcp list-projects
  /test-mcp test=basic-indexing tier=1
  /test-mcp test=issue-13 tier=2 protocol=sse
  /test-mcp validate-project project=tier1

Available test scenarios (Phase 1):
  - basic-indexing: Quick smoke test on small project
  - issue-13: Reproduce Issue #13 (boost headers)

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
