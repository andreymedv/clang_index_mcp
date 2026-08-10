# Agent Behavior Notes

Read this file for the detailed, expanded version of the behavior notes that are summarized in `AGENTS.md`.

1. **When analyzing C++ code in a project:** Prefer using the cpp-analyzer MCP tools (if server is running) over grep/glob. The analyzer understands C++ semantics (classes, inheritance, call graphs) which grep cannot.

2. **Documentation extraction:** MCP tools (`search_classes`, `search_functions`, `get_class_info`) return `brief` and `doc_comment` fields extracted from C++ documentation comments. Supports Doxygen (`///`, `/** */`), JavaDoc, and Qt-style (`/*!`) comments. Documentation is truncated at 4000 characters with "..." suffix if longer.

3. **Virtual/abstract method indicators:** MCP tools return `is_virtual`, `is_pure_virtual`, `is_const`, `is_static`, and `is_definition` fields for methods. This enables agents to:
   - Identify abstract interfaces (classes with `is_pure_virtual: true` methods have no implementation in that class)
   - Find implementations in derived classes (search for method name, filter by `is_definition: true` and non-pure-virtual)
   - Understand method contracts (const methods promise not to modify state, static methods are class-level)
   - Distinguish declarations from definitions when searching for where code actually runs

4. **Pattern matching behavior:** All search tools (`search_classes`, `search_functions`, `search_symbols`, `find_in_file`) support flexible pattern matching:
   - **Empty string (`""`)** matches ALL symbols — useful when filtering by file (e.g., `search_classes("", file_name="example.h")` returns all classes in that file)
   - **Plain text** (no regex metacharacters) performs exact match, case-insensitive (e.g., `"View"` matches only "View", not "ViewManager")
   - **Regex patterns** (with `.*+?[]{}()|` etc.) use anchored full-match (e.g., `"View.*"` matches "View", "ViewManager" but not "ListView"; `".*View.*"` matches all containing "View")

5. **Incremental analysis is automatic:** When using `sync_project(refresh_mode="incremental")`, the analyzer intelligently detects changes. Only use `refresh_mode="full"` after major config changes or if cache corruption is suspected.

6. **Project Identity is Config-Based:** Project identity and cache directories are determined solely by the absolute path of the configuration file. This allows same-source, multi-config workflows.

7. **No Automatic Discovery:** Legacy discovery of `.cpp-analyzer-config.json` in project root is removed. Always provide an explicit path to a configuration file.

8. **compile_commands.json:** If present, the analyzer will use it for accurate compilation arguments. Restart the analyzer after modifying `compile_commands.json`.

9. **Multi-process mode:** Default mode bypasses the GIL for true parallelism. Workers run in isolated `spawn` processes; use `MCP_DEBUG=1` and per-worker logs when debugging parse issues.

10. **SQLite cache:** Lives in `.mcp_cache/` (multi-config support). Compile commands cache is stored in `.mcp_cache/<project>/compile_commands/`. Safe to delete for fresh indexing. WAL mode enables concurrent access. **Schema version 17.0** includes virtual method indicators (`is_virtual`, `is_pure_virtual`, `is_const`, `is_static`), `type_aliases` table with `template_params` support, documentation fields (`brief`, `doc_comment`), `call_sites` table for line-level call graph tracking, and template-mediated call metadata (`display_name`, `template_project_types`).

11. **Development mode auto-recreation:** During development, the SQLite database is automatically recreated when the schema version changes. When you change `clang_index_mcp/_persistence/schema.sql`, increment the version number and update `CURRENT_SCHEMA_VERSION` in `clang_index_mcp/_persistence/sqlite_cache_backend.py`. On next run, the old database will be deleted and recreated with the new schema.

12. **Parse error recovery:** The analyzer leverages libclang's error recovery to extract symbols from files with non-fatal parsing errors. Files with syntax or semantic errors log warnings but continue processing, extracting partial symbols from the usable AST. Only true fatal errors (no TranslationUnit created) cause file rejection. This means you get partial results instead of nothing for files with minor issues.

13. **Test before committing:** Always run `make test` and `make check` before creating PRs.
