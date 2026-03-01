# MCP Testing Skill - FAQ & Troubleshooting

## Frequently Asked Questions

### General

**Q: What is the `/test-mcp` skill?**

A: A comprehensive testing framework for the C++ MCP Server. It allows you to run automated tests, manage test projects, and create custom test scenarios using YAML.

**Q: Do I need to install anything?**

A: The skill is already installed in `.claude/skills/test-mcp/`. You only need:
- `git` (for cloning projects)
- `cmake` (for CMake projects)
- `pytest` (optional, for running pytest suite)

**Q: Which projects can I test?**

A: You can test:
- tier1 (builtin small project, ~18 files)
- tier2 (builtin large project, ~5700 files)
- Any custom project cloned with `setup-project`

**Q: How long do tests take?**

A:
- `basic-indexing` on tier1: ~5-10 seconds
- `incremental-refresh` on tier1: ~10-20 seconds
- `all-protocols` on tier1: ~15-30 seconds
- `issue-13` on tier2: ~5-15 minutes (large project)

---

### Commands

**Q: How do I list available projects?**

A:
```bash
/test-mcp list-projects
```

**Q: How do I run a quick test?**

A:
```bash
/test-mcp test=basic-indexing tier=1
```

**Q: Can I test my own C++ project?**

A: Yes! Clone it first:
```bash
/test-mcp setup-project url=https://github.com/user/repo name=myproject
/test-mcp test=basic-indexing project=myproject
```

**Q: How do I create a custom test?**

A: Create a YAML file in `.test-scenarios/` and run:
```bash
/test-mcp test=custom scenario=my-test.yaml tier=1
```

See [YAML_SCENARIO_SPEC.md](../../.claude/skills/test-mcp/YAML_SCENARIO_SPEC.md) for format.

---

### Custom Scenarios

**Q: Where do I put custom YAML scenarios?**

A: In `.test-scenarios/` directory. Files there are tracked in git.

**Q: Can I use custom scenarios with any project?**

A: Yes! Specify the project:
```bash
/test-mcp test=custom scenario=my-test.yaml project=myproject
```

**Q: What MCP tools can I use in YAML scenarios?**

A: All MCP tools are supported:
- `set_project_directory`
- `get_indexing_status`
- `wait_for_indexing` (special helper)
- `search_classes`
- `search_functions`
- `search_symbols`
- `get_class_info`
- `get_incoming_calls`
- etc.

**Q: How do I validate expectations in YAML?**

A: Use expectation types:
```yaml
expect:
  - type: count           # Validate count
    operator: ">="
    value: 1
  - type: content_includes  # Check content
    value: "MyClass"
  - type: no_error        # No errors
```

---

### Projects

**Q: What's the difference between tier1 and tier2?**

A:
- **tier1**: Small project (~18 files), fast (~5-10s), good for quick tests
- **tier2**: Large project (~5700 files), slow (~5-15min), for real-world testing

**Q: How do I add a new test project?**

A:
```bash
/test-mcp setup-project url=https://github.com/user/repo name=myproject
```

**Q: Can I test projects without compile_commands.json?**

A: The MCP server can work without it, but won't have accurate compilation flags. For CMake projects, `setup-project` generates it automatically.

**Q: How do I remove a project?**

A:
```bash
# Remove from registry only
/test-mcp remove-project project=myproject

# Remove and delete files
/test-mcp remove-project project=myproject delete=yes
```

**Q: Can I remove tier1 or tier2?**

A: No, builtin projects cannot be removed.

---

## Troubleshooting

### Server Startup Issues

**Problem: "Server failed to start within 30s"**

**Solutions:**
1. Check if another server is running on port 8000:
   ```bash
   lsof -i :8000
   pkill -f cpp_mcp_server
   ```

2. Try a different protocol:
   ```bash
   /test-mcp test=basic-indexing tier=1 protocol=sse
   ```

3. Check server logs in `.test-results/` directory

---

**Problem: "Server not started"**

**Cause:** ServerManager couldn't start the MCP server process

**Solutions:**
1. Verify MCP server is installed:
   ```bash
   python -m mcp_server.cpp_mcp_server --help
   ```

2. Check for Python errors in terminal output

3. Ensure virtual environment is activated (if using one)

---

### Test Failures

**Problem: "Indexing did not complete within Xs"**

**Causes:**
- Project is very large
- Server crashed during indexing
- Timeout too short

**Solutions:**
1. Increase timeout in YAML scenario:
   ```yaml
   - tool: wait_for_indexing
     timeout: 120  # Increase to 120 seconds
   ```

2. Check if server is still running:
   ```bash
   ps aux | grep cpp_mcp_server
   ```

3. Use tier1 for faster testing

4. Check `.test-results/` logs for errors

---

**Problem: "Project validation failed"**

**Common Issues:**

1. **Directory does not exist:**
   - Project was deleted
   - Path in registry is incorrect
   - Solution: Run `setup-project` again or fix path

2. **compile_commands.json not found:**
   - CMake wasn't run
   - Build directory changed
   - Solution: Re-run cmake or update path in registry

3. **No C++ source files found:**
   - Wrong directory
   - Files have different extensions
   - Solution: Verify project path

---

**Problem: "Unknown test scenario: X"**

**Cause:** Typo in scenario name or scenario doesn't exist

**Solution:**
```bash
# Check available scenarios
/test-mcp help

# For custom scenarios, verify filename
ls .test-scenarios/
```

---

**Problem: "Custom scenarios require scenario= parameter"**

**Cause:** Used `test=custom` without `scenario=` parameter

**Solution:**
```bash
/test-mcp test=custom scenario=my-test.yaml tier=1
```

---

### Project Setup Issues

**Problem: "Git clone failed"**

**Causes:**
- Invalid URL
- No internet connection
- Authentication required
- Repository doesn't exist

**Solutions:**
1. Verify URL is correct
2. Test git clone manually:
   ```bash
   git clone <url>
   ```
3. For private repos, use SSH URL or configure git credentials

---

**Problem: "CMake configuration failed"**

**Causes:**
- CMake not installed
- Missing dependencies
- Invalid CMakeLists.txt

**Solutions:**
1. Install cmake:
   ```bash
   # Ubuntu/Debian
   sudo apt-get install cmake

   # macOS
   brew install cmake
   ```

2. Check CMake version:
   ```bash
   cmake --version
   ```

3. Try manual configuration:
   ```bash
   cd .test-projects/myproject
   cmake -B build -DCMAKE_EXPORT_COMPILE_COMMANDS=ON
   ```

---

**Problem: "compile_commands.json not generated by CMake"**

**Causes:**
- Old CMake version
- Project doesn't use CMake
- Configuration error

**Solutions:**
1. Update CMake (requires 3.5+)
2. For non-CMake projects, create compile_commands.json manually
3. Check CMake output for errors

---

### YAML Scenario Issues

**Problem: "YAML parsing error"**

**Causes:**
- Invalid YAML syntax
- Incorrect indentation
- Special characters not quoted

**Solutions:**
1. Validate YAML syntax:
   ```bash
   python -c "import yaml; yaml.safe_load(open('.test-scenarios/my-test.yaml'))"
   ```

2. Check indentation (use spaces, not tabs)

3. Quote special values:
   ```yaml
   pattern: ".*"  # Correct
   pattern: .*    # May fail
   ```

---

**Problem: "Scenario missing 'steps' field"**

**Cause:** YAML file doesn't have required `steps` field

**Solution:**
```yaml
name: my-test
description: My test
project: tier1
protocol: http
steps:              # Required!
  - tool: set_project_directory
    args:
      project_path: "$PROJECT_PATH"
```

---

**Problem: "Expectation failed"**

**Causes:**
- Actual results don't match expected
- Wrong expectation type
- Incorrect operator or value

**Solutions:**
1. Check test results in `.test-results/` directory
2. Adjust expectations to match actual behavior
3. Verify expectation syntax:
   ```yaml
   expect:
     - type: count
       operator: ">="  # Not ">" if count can be equal
       value: 1
   ```

---

**Problem: "Unknown expectation type: X"**

**Cause:** Typo or unsupported expectation type

**Supported types:**
- `count`
- `content_includes`
- `content_matches`
- `has_field`
- `no_error`

**Solution:** Fix typo or use supported type

---

### pytest Issues

**Problem: "pytest not found"**

**Cause:** pytest is not installed

**Solution:**
```bash
pip install pytest
```

---

**Problem: "Pytest suite timed out"**

**Cause:** Tests taking longer than 5 minutes

**Solutions:**
1. Run pytest manually to see progress:
   ```bash
   pytest -v
   ```

2. Run specific tests:
   ```bash
   pytest tests/test_analyzer.py -v
   ```

---

### Performance Issues

**Problem: "Tests are slow"**

**Solutions:**
1. Use tier1 instead of tier2:
   ```bash
   /test-mcp test=basic-indexing tier=1  # Fast
   ```

2. Use custom scenarios with specific tools (faster than full tests)

3. Don't run `issue-13` on tier2 unless necessary (takes 5-15 minutes)

---

**Problem: "Server takes long to start"**

**Causes:**
- Cold start
- Large project indexing in background

**Solutions:**
1. First start is always slower
2. Subsequent tests are faster (cache warm)
3. Use smaller projects for quick iteration

---

### File System Issues

**Problem: ".test-projects/ directory full"**

**Solution:**
```bash
# Remove unused projects
/test-mcp remove-project project=old-project delete=yes

# Or manually clean
rm -rf .test-projects/old-project
```

---

**Problem: ".test-results/ directory too large"**

**Solution:**
```bash
# Remove old test results
rm -rf .test-results/*

# Or keep recent results only
find .test-results/ -mtime +7 -delete  # Delete older than 7 days
```

---

### Common Errors

**Error: "Project 'X' not found"**

**Solution:**
```bash
# List available projects
/test-mcp list-projects

# Use correct project name
/test-mcp test=basic-indexing project=tier1
```

---

**Error: "Cannot remove builtin project 'tier1'"**

**Cause:** Attempted to remove tier1 or tier2

**Solution:** These projects cannot be removed (they're references to existing directories)

---

**Error: "Scenario file not found"**

**Causes:**
- File doesn't exist
- Wrong path
- File in wrong directory

**Solutions:**
1. Check file exists:
   ```bash
   ls .test-scenarios/my-test.yaml
   ```

2. Use relative path from `.test-scenarios/`:
   ```bash
   /test-mcp test=custom scenario=my-test.yaml tier=1
   ```

3. Or use absolute path:
   ```bash
   /test-mcp test=custom scenario=/full/path/to/test.yaml tier=1
   ```

---

## Getting Help

If you're still having issues:

1. **Check logs:**
   ```bash
   cat .test-results/$(ls -t .test-results/ | head -1)/results.json | jq
   ```

2. **Read documentation:**
   - [User Guide](TEST_MCP_USER_GUIDE.md)
   - [Command Reference](TEST_MCP_COMMAND_REFERENCE.md)
   - [YAML Scenario Spec](../../.claude/skills/test-mcp/YAML_SCENARIO_SPEC.md)

3. **Try simple test first:**
   ```bash
   /test-mcp test=basic-indexing tier=1
   ```

4. **Validate setup:**
   ```bash
   /test-mcp validate-project project=tier1
   ```

5. **Report issue:**
   - Include command run
   - Include error message
   - Include logs from `.test-results/`

---

## Best Practices

1. **Start simple:** Use tier1 and basic-indexing for initial testing
2. **Validate first:** Run `validate-project` before tests
3. **Check logs:** Look in `.test-results/` for detailed error information
4. **Clean up:** Remove old projects and test results periodically
5. **Use custom scenarios:** Faster and more focused than full tests

---

## See Also

- [User Guide](TEST_MCP_USER_GUIDE.md) - Comprehensive usage guide
- [Command Reference](TEST_MCP_COMMAND_REFERENCE.md) - Detailed command documentation
- [YAML Scenario Spec](../../.claude/skills/test-mcp/YAML_SCENARIO_SPEC.md) - Custom scenario format
