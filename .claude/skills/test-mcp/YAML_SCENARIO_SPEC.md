# YAML Scenario Specification

## Overview

Custom test scenarios can be defined in YAML format for flexible testing without writing Python code.

## Format

```yaml
name: scenario-name
description: Human-readable description
project: tier1  # or tier2, or custom project name
protocol: http  # sse, http, or stdio
timeout: 60     # Maximum execution time in seconds (optional, default: 60)

steps:
  - tool: set_project_directory
    args:
      project_path: "$PROJECT_PATH"  # Special variable
    description: "Set project directory"

  - tool: wait_for_indexing
    timeout: 30
    description: "Wait for indexing to complete"

  - tool: search_classes
    args:
      pattern: "Example.*"
    expect:
      - type: count
        operator: ">"
        value: 0
      - type: content_includes
        value: "ExampleClass"
    description: "Search for Example classes"

  - tool: search_functions
    args:
      pattern: ""
    expect:
      - type: count
        operator: ">="
        value: 10
    description: "Verify at least 10 functions found"

  - tool: get_class_info
    args:
      class_name: "ExampleClass"
    expect:
      - type: has_field
        field: "methods"
      - type: content_includes
        value: "void someMethod"
    description: "Get class information"
```

## Special Variables

- `$PROJECT_PATH` - Replaced with actual project path from registry
- `$PROJECT_NAME` - Project name
- `$BUILD_DIR` - Project build directory (if applicable)

## Step Structure

Each step has:
- `tool`: MCP tool name (required)
- `args`: Tool arguments as key-value pairs (optional)
- `expect`: List of expectations to validate (optional)
- `description`: Human-readable description (optional)
- `timeout`: Step-specific timeout in seconds (optional)

## Expectation Types

### count
Validate number of results:
```yaml
expect:
  - type: count
    operator: ">"  # >, >=, <, <=, ==, !=
    value: 5
```

### content_includes
Check if response contains specific text:
```yaml
expect:
  - type: content_includes
    value: "expected_string"
```

### content_matches
Check if response matches regex:
```yaml
expect:
  - type: content_matches
    pattern: "class \\w+.*"
```

### has_field
Verify response has specific field (for JSON responses):
```yaml
expect:
  - type: has_field
    field: "methods"
```

### no_error
Verify no error in response:
```yaml
expect:
  - type: no_error
```

## Example Scenarios

### Minimal Scenario
```yaml
name: quick-check
description: Quick smoke test
project: tier1
protocol: http

steps:
  - tool: set_project_directory
    args:
      project_path: "$PROJECT_PATH"
  - tool: wait_for_indexing
  - tool: search_classes
    args:
      pattern: ""
    expect:
      - type: count
        operator: ">"
        value: 0
```

### Advanced Scenario
```yaml
name: class-hierarchy-test
description: Test class hierarchy analysis
project: tier1
protocol: http
timeout: 120

steps:
  - tool: set_project_directory
    args:
      project_path: "$PROJECT_PATH"

  - tool: wait_for_indexing
    timeout: 60

  - tool: search_classes
    args:
      pattern: "Base.*"
    expect:
      - type: count
        operator: ">="
        value: 1
      - type: content_includes
        value: "BaseClass"

  - tool: get_class_info
    args:
      class_name: "BaseClass"
    expect:
      - type: has_field
        field: "methods"
      - type: has_field
        field: "file_path"

  - tool: find_derived_classes
    args:
      base_class: "BaseClass"
    expect:
      - type: count
        operator: ">="
        value: 1
```

## Location

Custom scenarios should be placed in:
- `.test-scenarios/` directory in project root (gitignored)
- Or specified via full path: `/test-mcp test=custom scenario=/path/to/scenario.yaml`

## Usage

```bash
# Run custom scenario
/test-mcp test=custom scenario=.test-scenarios/my-test.yaml

# Or if scenario is in default location
/test-mcp test=my-test
```
