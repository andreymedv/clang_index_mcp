# Custom Test Scenarios

This directory contains custom YAML test scenarios for the MCP Testing Skill.

## Usage

```bash
# Run a custom scenario
/test-mcp test=custom scenario=quick-check.yaml tier=1

# Or specify full path
/test-mcp test=custom scenario=/path/to/scenario.yaml tier=1
```

## Format

See `.claude/skills/test-mcp/YAML_SCENARIO_SPEC.md` for the complete YAML scenario format specification.

## Examples

- `quick-check.yaml` - Quick smoke test with basic indexing and search
- `class-hierarchy.yaml` - Test class hierarchy analysis

## Creating Custom Scenarios

1. Create a `.yaml` file in this directory
2. Define test steps using MCP tools
3. Add expectations to validate results
4. Run with `/test-mcp test=custom scenario=your-scenario.yaml`

Example:

```yaml
name: my-test
description: My custom test scenario
project: tier1
protocol: http

steps:
  - tool: set_project_directory
    args:
      project_path: "$PROJECT_PATH"

  - tool: wait_for_indexing
    timeout: 30

  - tool: search_classes
    args:
      pattern: "MyClass"
    expect:
      - type: count
        operator: ">="
        value: 1
```
