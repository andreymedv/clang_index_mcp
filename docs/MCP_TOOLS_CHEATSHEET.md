# MCP Tools Cheatsheet

Quick reference for C++ code analysis tools. All examples use YAML format for readability.

## Quick Reference by Category

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ SEARCH (find symbols by name/pattern)                                       │
├─────────────────────────────────────────────────────────────────────────────┤
│ search_classes     │ Find classes/structs by name pattern                   │
│ search_functions   │ Find functions/methods by name pattern                 │
│ search_symbols     │ Find any symbol (classes + functions)                  │
│ find_in_file       │ Find symbols defined in specific file                  │
├─────────────────────────────────────────────────────────────────────────────┤
│ DETAILS (get full info about specific symbol)                               │
├─────────────────────────────────────────────────────────────────────────────┤
│ get_class_info     │ Methods, members, base classes of a class              │
│ get_function_signature │ Parameters, return type, template info             │
│ get_type_alias_info │ Underlying type of using/typedef                      │
├─────────────────────────────────────────────────────────────────────────────┤
│ HIERARCHY (inheritance relationships)                                       │
├─────────────────────────────────────────────────────────────────────────────┤
│ get_class_hierarchy │ Full base + derived class tree (all descendants)      │
├─────────────────────────────────────────────────────────────────────────────┤
│ CALL GRAPH (who calls what)                                                 │
├─────────────────────────────────────────────────────────────────────────────┤
│ find_callers       │ Functions that call target function                    │
│ find_callees       │ Functions called by target function                    │
│ get_call_sites     │ Exact lines where calls occur                          │
│ get_call_path      │ Path between two functions in call graph               │
├─────────────────────────────────────────────────────────────────────────────┤
│ PROJECT MANAGEMENT                                                          │
├─────────────────────────────────────────────────────────────────────────────┤
│ set_project_directory │ Set project root, start indexing                    │
│ refresh_project    │ Re-index changed files                                 │
│ get_indexing_status │ Check indexing progress                               │
│ wait_for_indexing  │ Block until indexing complete                          │
│ get_server_status  │ Server health and statistics                           │
│ get_files_containing_symbol │ Files where symbol is defined/used            │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Pattern Matching Modes (for all search tools)

| Pattern | Mode | Matches | Does NOT match |
|---------|------|---------|----------------|
| `Handler` | Unqualified | `Handler`, `app::Handler`, `app::ui::Handler` | - |
| `ui::Handler` | Suffix | `app::ui::Handler`, `legacy::ui::Handler` | `myui::Handler` |
| `::Handler` | Exact global | `Handler` (global only) | `app::Handler` |
| `.*Handler.*` | Regex | `MyHandlerImpl`, `app::Handler` | - |
| `""` (empty) | Match all | Everything | - |

---

## Search Tools

### search_classes

Find classes and structs by name pattern.

**Input:**
```yaml
pattern: "Builder"              # Required: name pattern (see modes above)
project_only: true              # Optional: exclude system headers (default: true)
file_name: "document.h"         # Optional: filter by file
namespace: "app::core"          # Optional: exact namespace filter
```

**Output:** List of matching classes
```yaml
- name: TextBuilder                        # Simple class name
  qualified_name: app::doc::TextBuilder    # Full name with namespaces
  namespace: app::doc                      # Namespace portion
  kind: class                              # "class" or "struct"
  file: /path/to/document.h                # Definition file
  line: 42                                 # Definition line
  start_line: 42                           # First line of class
  end_line: 85                             # Last line of class
  base_classes:                            # Parent classes
    - app::doc::Builder
  is_template: false                       # Is template class?
  template_kind: null                      # "class_template" if template
  template_parameters: null                # Template params as JSON
  is_template_specialization: false        # Is explicit specialization?
  brief: "Builds text documents"           # First line of doc comment
  doc_comment: "Builds text documents..."  # Full doc comment
```

### search_functions

Find functions and methods by name pattern.

**Input:**
```yaml
pattern: "parse.*"              # Required: name pattern
project_only: true              # Optional
file_name: "parser.cpp"         # Optional
namespace: "parser"             # Optional
```

**Output:** List of matching functions
```yaml
- name: parseDocument                      # Function name
  qualified_name: parser::parseDocument    # Full name
  namespace: parser
  kind: function                           # "function" or "method"
  signature: "Document (const string &)"   # Parameters and return type
  file: /path/to/parser.cpp
  line: 100
  start_line: 100
  end_line: 150
  parent_class: ""                         # Non-empty for methods
  access: public                           # public/private/protected
  is_template: false
  template_kind: null
  template_parameters: null
  is_template_specialization: false
  brief: null
  doc_comment: null
```

### search_symbols

Find any symbol type (classes + functions combined).

**Input:**
```yaml
pattern: "Widget.*"             # Required
project_only: true              # Optional
```

**Output:** Same as search_classes + search_functions combined.

### find_in_file

Find all symbols defined in a specific file.

**Input:**
```yaml
file_path: "src/core/engine.cpp"  # Required: file path (absolute or relative)
pattern: ""                        # Optional: filter by name pattern
```

**Output:** Same structure as search_symbols.

---

## Detail Tools

### get_class_info

Get complete information about a single class.

**Input:**
```yaml
class_name: "app::ui::Widget"   # Simple or qualified name
```

**Output:**
```yaml
name: Widget
qualified_name: app::ui::Widget
namespace: app::ui
kind: class
file: /path/to/widget.h
line: 25
start_line: 25
end_line: 120
base_classes:
  - app::ui::Component
methods:                                   # All methods of this class
  - name: render
    signature: "void ()"
    access: public
    line: 45
    is_template: false
    is_template_specialization: false
    start_line: 45
    end_line: 60
    brief: "Renders widget to screen"
  - name: handleEvent
    signature: "bool (const Event &)"
    access: protected
    line: 70
members: []                                # Data members (if extracted)
is_template: false
template_kind: null
template_parameters: null
brief: "Base widget class"
doc_comment: "Base widget class for all UI components..."
```

### get_function_signature

Get complete function/method information.

**Input:**
```yaml
function_name: "parser::parseJSON"  # Simple or qualified name
```

**Output:**
```yaml
name: parseJSON
qualified_name: parser::parseJSON
namespace: parser
signature: "Document (const string &, ParseOptions)"
return_type: Document                      # Extracted from signature
parameters:                                # Parsed parameters
  - name: input
    type: const string &
  - name: options
    type: ParseOptions
file: /path/to/parser.cpp
line: 200
start_line: 200
end_line: 250
is_template: false
template_parameters: null
brief: "Parse JSON string into Document"
```

### get_type_alias_info

Get information about type aliases (using/typedef).

**Input:**
```yaml
alias_name: "StringList"        # Alias name
```

**Output:**
```yaml
name: StringList
qualified_name: app::StringList
underlying_type: "std::vector<std::string>"   # What it aliases to
file: /path/to/types.h
line: 15
is_template_alias: false                       # Template alias?
template_parameters: null                      # For template aliases
```

---

## Hierarchy Tools

### get_class_hierarchy

Get full inheritance tree (both directions).

**Input:**
```yaml
class_name: "app::ui::Button"   # Simple or qualified name
```

**Output:**
```yaml
name: app::ui::Button
class_info:                                # Full class details (same as get_class_info)
  name: Button
  qualified_name: app::ui::Button
  # ... all fields ...
base_classes:                              # Direct parents
  - app::ui::Widget
derived_classes:                           # Direct children
  - app::ui::IconButton
  - app::ui::TextButton
base_hierarchy:                            # Full tree upward
  name: app::ui::Button
  base_classes:
    - name: app::ui::Widget
      base_classes:
        - name: app::ui::Component
          base_classes: []
derived_hierarchy:                         # Full tree downward
  name: app::ui::Button
  derived_classes:
    - name: app::ui::IconButton
      derived_classes: []
    - name: app::ui::TextButton
      derived_classes:
        - name: app::ui::RichTextButton
          derived_classes: []
```

---

## Call Graph Tools

### find_callers

Find all functions that call the target function.

**Input:**
```yaml
function_name: "saveDocument"   # Simple or qualified name
max_depth: 1                    # Optional: 1 = direct callers only (default)
```

**Output:**
```yaml
- name: handleSaveAction
  qualified_name: app::ui::Editor::handleSaveAction
  file: /path/to/editor.cpp
  line: 340
  call_line: 355                           # Line where call occurs
```

### find_callees

Find all functions called by the target function.

**Input:**
```yaml
function_name: "processRequest" # Simple or qualified name
max_depth: 1                    # Optional: 1 = direct callees only
```

**Output:**
```yaml
- name: validateInput
  qualified_name: app::validateInput
  file: /path/to/validation.cpp
  line: 50
  call_line: 120                           # Line in processRequest where call occurs
```

### get_call_sites

Get exact call locations with line numbers.

**Input:**
```yaml
function_name: "logError"       # Function being called
```

**Output:**
```yaml
- caller: app::network::Connection::handleError
  caller_file: /path/to/connection.cpp
  call_line: 234
  callee: logError
- caller: app::db::Query::execute
  caller_file: /path/to/query.cpp
  call_line: 89
  callee: logError
```

### get_call_path

Find path between two functions in call graph.

**Input:**
```yaml
from_function: "main"
to_function: "sendEmail"
max_depth: 10                   # Optional: maximum search depth
```

**Output:**
```yaml
path_found: true
path:
  - main
  - processCommands
  - handleNotification
  - NotificationService::send
  - sendEmail
path_length: 5
```

---

## Project Management Tools

### set_project_directory

Initialize project and start indexing.

**Input:**
```yaml
path: "/home/user/myproject"    # Required: project root
config_file: "cpp-analyzer-config.json"  # Optional: custom config
```

**Output:**
```yaml
status: indexing_started
project_root: /home/user/myproject
total_files: 1250
config_used: /home/user/myproject/cpp-analyzer-config.json
compile_commands: /home/user/myproject/build/compile_commands.json
```

### get_indexing_status

Check current indexing progress.

**Input:** None

**Output:**
```yaml
status: indexing                           # "idle", "indexing", "completed"
files_processed: 450
files_total: 1250
percent_complete: 36
current_file: /path/to/current.cpp
errors: 3                                  # Files with parse errors
```

### wait_for_indexing

Block until indexing completes (useful in scripts).

**Input:**
```yaml
timeout_seconds: 300            # Optional: max wait time
```

**Output:**
```yaml
status: completed
files_indexed: 1250
files_with_errors: 3
duration_seconds: 45.2
```

### refresh_project

Re-index changed files (incremental).

**Input:**
```yaml
force_full: false               # Optional: force full re-index
```

**Output:**
```yaml
status: refresh_completed
files_checked: 1250
files_changed: 12
files_reindexed: 15                        # Changed + dependents
duration_seconds: 2.3
```

### get_server_status

Get server health and statistics.

**Input:** None

**Output:**
```yaml
status: ready
project_root: /home/user/myproject
indexed_files: 1250
classes_indexed: 3420
functions_indexed: 15600
index_size_mb: 45.2
cache_location: /home/user/myproject/.mcp_cache
uptime_seconds: 3600
```

### get_files_containing_symbol

Find files where symbol is defined or used.

**Input:**
```yaml
symbol_name: "DatabaseConnection"
```

**Output:**
```yaml
definition_files:
  - /path/to/database.h
  - /path/to/database.cpp
usage_files:
  - /path/to/repository.cpp
  - /path/to/migrations.cpp
  - /path/to/tests/db_test.cpp
```

---

## Common Use Cases

| I want to... | Use this |
|--------------|----------|
| Find a class by name | `search_classes(pattern="ClassName")` |
| Find all classes in a file | `search_classes(pattern="", file_name="myfile.h")` |
| See class methods and inheritance | `get_class_info(class_name="ClassName")` |
| Find who calls a function | `find_callers(function_name="func")` |
| See full inheritance tree | `get_class_hierarchy(class_name="Base")` |
| Find function signature | `get_function_signature(function_name="func")` |
| Search in specific namespace | `search_classes(pattern=".*", namespace="app::core")` |
| Find path between functions | `get_call_path(from="main", to="target")` |
