# Analysis of Issue #3: File Descriptor Leak

This document details the investigation and resolution of the "Too many open files" error that occurred during large project indexing on Linux.

## Root Cause Analysis

The investigation confirmed that the file descriptor leak was caused by the resource management strategy within the `_process_file_worker` function in `mcp_server/cpp_analyzer.py`. For each file being indexed, a new `CppAnalyzer` instance was created. This, in turn, created a new `CacheManager` and a new `SqliteCacheBackend`, which opened a new SQLite database connection, consuming a file descriptor.

The cleanup of these resources was reliant on Python's garbage collector and the `__del__` method, which is not guaranteed to run reliably in a multi-process environment. As a result, file descriptors were not being released, leading to an accumulation of open files that eventually exhausted the system limit.

The issue was exacerbated by a state leakage bug where the `CallGraphAnalyzer` was not reset between file analyses, leading to incorrect data being returned.

## Solution

The fix addresses both the file descriptor leak and the state leakage bug:

1.  **Shared `CppAnalyzer` Instance:** The `_process_file_worker` was refactored to use a single, process-local `CppAnalyzer` instance. This ensures that only one database connection is opened per worker process, drastically reducing the number of open file descriptors.

2.  **Guaranteed Cleanup:** An `atexit` handler was registered within each worker process to explicitly call the `close()` method on the shared `CppAnalyzer` instance when the process exits. This guarantees that all resources, including the SQLite connection, are properly released.

3.  **State Reset:** To prevent state leakage, the `CallGraphAnalyzer` is re-initialized for each file that is processed. This ensures that the analysis of one file does not affect the results of another.

This solution is robust because it no longer relies on the garbage collector for resource management and instead uses a guaranteed cleanup mechanism. It also ensures the correctness of the analysis by preventing state leakage between file processing tasks.
