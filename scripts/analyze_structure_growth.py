#!/usr/bin/env python3
"""
Targeted analysis of data structure growth during indexing.

Runs indexing on a subset of files and measures which structures
accumulate the most memory.
"""

import os
import sys
import gc
from pathlib import Path
from typing import Dict, List, Any

sys.path.insert(0, str(Path(__file__).parent.parent))


def get_size_recursive(obj, seen=None, max_depth=4, current_depth=0) -> int:
    """Get approximate size of an object and its references."""
    if seen is None:
        seen = set()

    if current_depth > max_depth:
        return 0

    obj_id = id(obj)
    if obj_id in seen:
        return 0
    seen.add(obj_id)

    size = sys.getsizeof(obj)

    if isinstance(obj, dict):
        for k, v in obj.items():
            size += get_size_recursive(k, seen, max_depth, current_depth + 1)
            size += get_size_recursive(v, seen, max_depth, current_depth + 1)
    elif isinstance(obj, (list, tuple, set, frozenset)):
        for item in obj:
            size += get_size_recursive(item, seen, max_depth, current_depth + 1)
    elif hasattr(obj, "__dict__"):
        size += get_size_recursive(obj.__dict__, seen, max_depth, current_depth + 1)

    return size


def format_size(size_bytes: int) -> str:
    """Format size in human-readable form."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"


def count_items(obj) -> int:
    """Count items in a collection."""
    if isinstance(obj, dict):
        return len(obj)
    elif isinstance(obj, (list, set, frozenset)):
        return len(obj)
    return 0


def analyze_analyzer_structures(analyzer, label: str = "") -> Dict[str, Any]:
    """Analyze memory usage of analyzer data structures."""
    gc.collect()

    structures = {}

    # Core indexes
    if hasattr(analyzer, "class_index"):
        ci_items = sum(len(v) for v in analyzer.class_index.values())
        structures["class_index"] = {
            "size": get_size_recursive(analyzer.class_index, max_depth=3),
            "keys": len(analyzer.class_index),
            "items": ci_items,
        }

    if hasattr(analyzer, "function_index"):
        fi_items = sum(len(v) for v in analyzer.function_index.values())
        structures["function_index"] = {
            "size": get_size_recursive(analyzer.function_index, max_depth=3),
            "keys": len(analyzer.function_index),
            "items": fi_items,
        }

    if hasattr(analyzer, "file_index"):
        fli_items = sum(len(v) for v in analyzer.file_index.values())
        structures["file_index"] = {
            "size": get_size_recursive(analyzer.file_index, max_depth=3),
            "keys": len(analyzer.file_index),
            "items": fli_items,
        }

    if hasattr(analyzer, "usr_index"):
        structures["usr_index"] = {
            "size": get_size_recursive(analyzer.usr_index, max_depth=3),
            "keys": len(analyzer.usr_index),
            "items": len(analyzer.usr_index),
        }

    if hasattr(analyzer, "file_hashes"):
        structures["file_hashes"] = {
            "size": get_size_recursive(analyzer.file_hashes, max_depth=2),
            "keys": len(analyzer.file_hashes),
            "items": len(analyzer.file_hashes),
        }

    # Call graph analyzer
    if hasattr(analyzer, "call_graph_analyzer"):
        cga = analyzer.call_graph_analyzer
        if hasattr(cga, "call_graph"):
            cg_calls = sum(len(v) for v in cga.call_graph.values())
            structures["call_graph"] = {
                "size": get_size_recursive(cga.call_graph, max_depth=2),
                "keys": len(cga.call_graph),
                "items": cg_calls,
            }
        if hasattr(cga, "reverse_call_graph"):
            rcg_calls = sum(len(v) for v in cga.reverse_call_graph.values())
            structures["reverse_call_graph"] = {
                "size": get_size_recursive(cga.reverse_call_graph, max_depth=2),
                "keys": len(cga.reverse_call_graph),
                "items": rcg_calls,
            }
        if hasattr(cga, "call_sites"):
            structures["call_sites"] = {
                "size": get_size_recursive(cga.call_sites, max_depth=2),
                "keys": 0,
                "items": len(cga.call_sites),
            }

    # Header tracker
    if hasattr(analyzer, "header_tracker"):
        ht = analyzer.header_tracker
        if hasattr(ht, "_processed"):
            structures["header_tracker._processed"] = {
                "size": get_size_recursive(ht._processed, max_depth=2),
                "keys": len(ht._processed),
                "items": len(ht._processed),
            }

    # Compile commands manager
    if hasattr(analyzer, "compile_commands_manager"):
        ccm = analyzer.compile_commands_manager
        if hasattr(ccm, "file_to_command_map") and ccm.file_to_command_map:
            structures["file_to_command_map"] = {
                "size": get_size_recursive(ccm.file_to_command_map, max_depth=2),
                "keys": len(ccm.file_to_command_map),
                "items": len(ccm.file_to_command_map),
            }

    return structures


def print_structures(structures: Dict[str, Any], label: str = ""):
    """Print structure analysis."""
    print(f"\n{'=' * 60}")
    print(f"STRUCTURE ANALYSIS {label}")
    print("=" * 60)

    # Sort by size
    sorted_items = sorted(structures.items(), key=lambda x: -x[1]["size"])

    total_size = 0
    for name, data in sorted_items:
        size = data["size"]
        total_size += size
        keys = data.get("keys", 0)
        items = data.get("items", 0)
        print(f"{name:30} {format_size(size):>12} | {keys:>8} keys | {items:>10} items")

    print("-" * 60)
    print(f"{'TOTAL':30} {format_size(total_size):>12}")
    return total_size


def main():
    if len(sys.argv) < 2:
        print("Usage: python analyze_structure_growth.py /path/to/project [max_files]")
        print("Example: python analyze_structure_growth.py /home/user/project 100")
        sys.exit(1)

    project_path = sys.argv[1]
    max_files = int(sys.argv[2]) if len(sys.argv) > 2 else 50

    if not os.path.isdir(project_path):
        print(f"Error: Project path does not exist: {project_path}")
        sys.exit(1)

    print("=" * 60)
    print("STRUCTURE GROWTH ANALYZER")
    print("=" * 60)
    print(f"Project: {project_path}")
    print(f"Max files: {max_files}")
    print("=" * 60)

    from mcp_server.cpp_analyzer import CppAnalyzer

    # Create analyzer and clear cache to force fresh indexing
    print("\nCreating CppAnalyzer...")
    analyzer = CppAnalyzer(project_path)

    # Initial state
    initial = analyze_analyzer_structures(analyzer, "(initial)")
    print_structures(initial, "(initial)")

    # Get list of files - use _find_cpp_files() to respect compile_commands.json
    print("\nScanning for files...")
    all_files = analyzer._find_cpp_files()
    print(f"Found {len(all_files)} files from compile_commands.json, will process {min(len(all_files), max_files)}")

    # Process files in batches
    batch_size = max(10, max_files // 5)
    snapshots = []

    files_to_process = all_files[:max_files]

    for i in range(0, len(files_to_process), batch_size):
        batch = files_to_process[i : i + batch_size]
        print(f"\nProcessing batch {i // batch_size + 1}: files {i + 1}-{min(i + batch_size, len(files_to_process))}")

        for file_path in batch:
            try:
                analyzer.index_file(file_path, force=True)
            except Exception as e:
                pass  # Ignore errors

        # Take snapshot after each batch
        snapshot = analyze_analyzer_structures(analyzer, f"(after {i + len(batch)} files)")
        snapshots.append((i + len(batch), snapshot))
        print_structures(snapshot, f"(after {i + len(batch)} files)")

    # Growth analysis
    print("\n" + "=" * 60)
    print("GROWTH ANALYSIS")
    print("=" * 60)

    if len(snapshots) >= 2:
        first_count, first = snapshots[0]
        last_count, last = snapshots[-1]

        print(f"\nGrowth from {first_count} to {last_count} files:")
        print("-" * 60)

        for name in first:
            if name in last:
                first_size = first[name]["size"]
                last_size = last[name]["size"]
                growth = last_size - first_size
                first_items = first[name]["items"]
                last_items = last[name]["items"]
                items_growth = last_items - first_items

                if growth > 0:
                    # Calculate per-file growth
                    files_diff = last_count - first_count
                    per_file = growth / files_diff if files_diff > 0 else 0
                    items_per_file = items_growth / files_diff if files_diff > 0 else 0

                    print(f"{name:30}")
                    print(f"  Size: {format_size(first_size)} → {format_size(last_size)} (+{format_size(growth)})")
                    print(f"  Items: {first_items} → {last_items} (+{items_growth})")
                    print(f"  Per file: +{format_size(int(per_file))} size, +{items_per_file:.1f} items")

    # Estimate for full project
    if len(all_files) > max_files and len(snapshots) >= 2:
        print("\n" + "=" * 60)
        print("PROJECTION FOR FULL PROJECT")
        print("=" * 60)

        first_count, first = snapshots[0]
        last_count, last = snapshots[-1]
        files_diff = last_count - first_count

        total_files = len(all_files)
        remaining_files = total_files - last_count

        print(f"\nTotal files in project: {total_files}")
        print(f"Files processed: {last_count}")
        print(f"Remaining: {remaining_files}")
        print("-" * 60)

        for name in last:
            if name in first:
                first_size = first[name]["size"]
                last_size = last[name]["size"]
                growth = last_size - first_size

                if growth > 0 and files_diff > 0:
                    per_file = growth / files_diff
                    projected_growth = per_file * remaining_files
                    projected_total = last_size + projected_growth

                    if projected_total > 10 * 1024 * 1024:  # > 10 MB
                        print(f"{name:30}")
                        print(f"  Current: {format_size(last_size)}")
                        print(f"  Projected: {format_size(int(projected_total))}")
                        print(f"  Rate: +{format_size(int(per_file))}/file")


if __name__ == "__main__":
    main()
