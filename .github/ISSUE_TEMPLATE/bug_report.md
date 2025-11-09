---
name: Bug Report
about: Report a bug or unexpected behavior
title: "[BUG] "
labels: bug
assignees: ''
---

## Bug Description

<!-- A clear and concise description of what the bug is -->

## Steps to Reproduce

1.
2.
3.
4.

## Expected Behavior

<!-- What you expected to happen -->

## Actual Behavior

<!-- What actually happened -->

## Environment

**Operating System:**
- [ ] Windows (Version: )
- [ ] macOS (Version: )
- [ ] Linux (Distribution & Version: )

**Python Version:**
<!-- Run: python --version -->

**libclang Version:**
<!-- Check lib/ directory or run: python -c "import clang.cindex; print(clang.cindex.version)" -->

**MCP Server Version:**
<!-- Git commit hash or release version -->

**Project Being Analyzed:**
- Language: C/C++
- Size: <!-- Number of files -->
- Build System: <!-- CMake, Make, etc. -->

## Error Messages/Logs

<!-- Include any error messages, stack traces, or relevant log output -->

```
Paste error messages here
```

## Configuration

**cpp-analyzer-config.json:**
```json
{
  "exclude_directories": [...],
  ...
}
```

## Minimal Reproducible Example

<!-- If possible, provide a minimal C++ code example that triggers the issue -->

```cpp
// main.cpp
class Example {
    // ...
};
```

## Screenshots

<!-- If applicable, add screenshots to help explain your problem -->

## Additional Context

<!-- Add any other context about the problem here -->

## Possible Solution

<!-- If you have suggestions on how to fix the bug -->

## Checklist

- [ ] I have searched existing issues to ensure this is not a duplicate
- [ ] I have included all relevant information above
- [ ] I have tested with the latest version
- [ ] I can reproduce this issue consistently
