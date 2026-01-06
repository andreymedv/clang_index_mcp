#!/usr/bin/env python3
"""
Direct testing script for /test-mcp skill

This allows testing the skill without going through Claude Code CLI
"""

import sys
from pathlib import Path

# Add skill to path
skill_dir = Path(__file__).parent.parent / ".claude" / "skills" / "test-mcp"
sys.path.insert(0, str(skill_dir))

from test_runner import TestRunner


def main():
    """Run a quick test"""
    print("=" * 60)
    print("MCP Testing Skill - Direct Test")
    print("=" * 60)
    print()

    # Test basic-indexing on tier1
    runner = TestRunner()

    print("Running: basic-indexing on tier1 (HTTP mode)")
    print("-" * 60)
    print()

    result = runner.run_test(test_name="basic-indexing", project="tier1", protocol="http")

    print()
    print("=" * 60)
    print("RESULT:")
    print("=" * 60)
    print(result)


if __name__ == "__main__":
    main()
