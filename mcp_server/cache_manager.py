"""Cache management for C++ analyzer."""

import json
import hashlib
import time
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional, Any
from collections import defaultdict
from .symbol_info import SymbolInfo


class CacheManager:
    """Manages caching for the C++ analyzer."""
    
    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.cache_dir = self._get_cache_dir()
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        
    def _get_cache_dir(self) -> Path:
        """Get the cache directory for this project"""
        # Use the MCP server directory for cache, not the project being analyzed
        mcp_server_root = Path(__file__).parent.parent  # Go up from mcp_server/cache_manager.py to root
        cache_base = mcp_server_root / ".mcp_cache"
        
        # Use a hash of the project path to create a unique cache directory
        project_hash = hashlib.md5(str(self.project_root).encode()).hexdigest()[:8]
        cache_dir = cache_base / f"{self.project_root.name}_{project_hash}"
        return cache_dir
    
    def get_file_hash(self, file_path: str) -> str:
        """Calculate hash of a file"""
        try:
            with open(file_path, 'rb') as f:
                return hashlib.md5(f.read()).hexdigest()
        except:
            return ""
    
    def save_cache(self, class_index: Dict[str, List[SymbolInfo]],
                   function_index: Dict[str, List[SymbolInfo]],
                   file_hashes: Dict[str, str],
                   indexed_file_count: int,
                   include_dependencies: bool = False,
                   config_file_path: Optional[Path] = None,
                   config_file_mtime: Optional[float] = None,
                   compile_commands_path: Optional[Path] = None,
                   compile_commands_mtime: Optional[float] = None) -> bool:
        """Save indexes to cache file with configuration metadata"""
        try:
            cache_file = self.cache_dir / "cache_info.json"

            # Convert to serializable format
            cache_data = {
                "version": "2.0",  # Cache version
                "include_dependencies": include_dependencies,
                "config_file_path": str(config_file_path) if config_file_path else None,
                "config_file_mtime": config_file_mtime,
                "compile_commands_path": str(compile_commands_path) if compile_commands_path else None,
                "compile_commands_mtime": compile_commands_mtime,
                "class_index": {},
                "function_index": {},
                "file_hashes": file_hashes,
                "indexed_file_count": indexed_file_count,
                "timestamp": time.time()
            }
            
            # Convert class index
            for name, infos in class_index.items():
                cache_data["class_index"][name] = [info.to_dict() for info in infos]
            
            # Convert function index
            for name, infos in function_index.items():
                cache_data["function_index"][name] = [info.to_dict() for info in infos]
            
            # Save to file
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            with open(cache_file, 'w') as f:
                json.dump(cache_data, f, indent=2)
            
            return True
        except Exception as e:
            print(f"Error saving cache: {e}", file=sys.stderr)
            return False
    
    def load_cache(self, include_dependencies: bool = False,
                   config_file_path: Optional[Path] = None,
                   config_file_mtime: Optional[float] = None,
                   compile_commands_path: Optional[Path] = None,
                   compile_commands_mtime: Optional[float] = None) -> Optional[Dict[str, Any]]:
        """Load cache if it exists and is valid, checking for configuration changes"""
        cache_file = self.cache_dir / "cache_info.json"

        if not cache_file.exists():
            return None

        try:
            with open(cache_file, 'r') as f:
                cache_data = json.load(f)

            # Check cache version
            if cache_data.get("version") != "2.0":
                print("Cache version mismatch, rebuilding...", file=sys.stderr)
                return None

            # Check if dependencies setting matches
            cached_include_deps = cache_data.get("include_dependencies", False)
            if cached_include_deps != include_dependencies:
                print(f"Cache dependencies setting mismatch (cached={cached_include_deps}, current={include_dependencies})",
                      file=sys.stderr)
                return None

            # Check if config file has changed
            cached_config_path = cache_data.get("config_file_path")
            cached_config_mtime = cache_data.get("config_file_mtime")

            current_config_path = str(config_file_path) if config_file_path else None

            # Detect config file changes
            if cached_config_path != current_config_path:
                # Config file path changed (created, deleted, or switched)
                print("Configuration file path changed, rebuilding index...", file=sys.stderr)
                return None

            if cached_config_mtime != config_file_mtime:
                # Config file modified
                print("Configuration file modified, rebuilding index...", file=sys.stderr)
                return None

            # Check if compile_commands.json has changed
            cached_cc_path = cache_data.get("compile_commands_path")
            cached_cc_mtime = cache_data.get("compile_commands_mtime")

            current_cc_path = str(compile_commands_path) if compile_commands_path else None

            # Detect compile_commands.json changes
            if cached_cc_path != current_cc_path:
                # compile_commands.json path changed (created, deleted, or moved)
                print("compile_commands.json path changed, rebuilding index...", file=sys.stderr)
                return None

            if cached_cc_mtime != compile_commands_mtime:
                # compile_commands.json modified
                print("compile_commands.json modified, rebuilding index...", file=sys.stderr)
                return None

            return cache_data

        except Exception as e:
            print(f"Error loading cache: {e}", file=sys.stderr)
            return None
    
    def get_file_cache_path(self, file_path: str) -> Path:
        """Get the cache file path for a given source file"""
        files_dir = self.cache_dir / "files"
        cache_filename = hashlib.md5(file_path.encode()).hexdigest() + ".json"
        return files_dir / cache_filename
    
    def save_file_cache(self, file_path: str, symbols: List[SymbolInfo],
                       file_hash: str, compile_args_hash: Optional[str] = None) -> bool:
        """Save parsed symbols for a single file with compilation arguments hash

        Args:
            file_path: Path to the source file
            symbols: List of symbols found in the file
            file_hash: Hash of the file content
            compile_args_hash: Hash of the compilation arguments used to parse this file
        """
        try:
            # Create files subdirectory
            files_dir = self.cache_dir / "files"
            files_dir.mkdir(exist_ok=True)

            # Use hash of file path as cache filename
            cache_file = self.get_file_cache_path(file_path)

            # Prepare cache data
            cache_data = {
                "version": "1.1",  # Bump version to include compile_args_hash
                "file_path": file_path,
                "file_hash": file_hash,
                "compile_args_hash": compile_args_hash,
                "timestamp": time.time(),
                "symbols": [s.to_dict() for s in symbols]
            }

            # Save to file
            with open(cache_file, 'w') as f:
                json.dump(cache_data, f, indent=2)

            return True
        except Exception as e:
            # Silently fail for individual file caches
            return False
    
    def load_file_cache(self, file_path: str, current_hash: str,
                       compile_args_hash: Optional[str] = None) -> Optional[List[SymbolInfo]]:
        """Load cached symbols for a file if hash matches

        Args:
            file_path: Path to the source file
            current_hash: Current hash of the file content
            compile_args_hash: Current hash of the compilation arguments

        Returns:
            List of cached symbols if valid, None otherwise
        """
        try:
            cache_file = self.get_file_cache_path(file_path)

            if not cache_file.exists():
                return None

            with open(cache_file, 'r') as f:
                cache_data = json.load(f)

            # Check cache version - invalidate old caches that don't have compile_args_hash
            cache_version = cache_data.get("version", "1.0")
            if cache_version != "1.1":
                return None

            # Check if file hash matches
            if cache_data.get("file_hash") != current_hash:
                return None

            # Check if compilation arguments hash matches
            cached_args_hash = cache_data.get("compile_args_hash")
            if cached_args_hash != compile_args_hash:
                # Compilation arguments changed - invalidate cache
                return None

            # Reconstruct SymbolInfo objects
            symbols = []
            for s in cache_data.get("symbols", []):
                symbols.append(SymbolInfo(**s))

            return symbols
        except:
            return None
    
    def remove_file_cache(self, file_path: str) -> bool:
        """Remove cached data for a deleted file"""
        try:
            cache_file = self.get_file_cache_path(file_path)
            if cache_file.exists():
                cache_file.unlink()
                return True
            return False
        except:
            return False
    
    def save_progress(self, total_files: int, indexed_files: int, 
                     failed_files: int, cache_hits: int,
                     last_index_time: float, class_count: int, 
                     function_count: int, status: str = "in_progress"):
        """Save indexing progress"""
        try:
            progress_file = self.cache_dir / "indexing_progress.json"
            progress_data = {
                "project_root": str(self.project_root),
                "total_files": total_files,
                "indexed_files": indexed_files,
                "failed_files": failed_files,
                "cache_hits": cache_hits,
                "last_index_time": last_index_time,
                "timestamp": time.time(),
                "class_count": class_count,
                "function_count": function_count,
                "status": status
            }
            
            with open(progress_file, 'w') as f:
                json.dump(progress_data, f, indent=2)
        except:
            pass  # Silently fail for progress tracking
    
    def load_progress(self) -> Optional[Dict[str, Any]]:
        """Load indexing progress if available"""
        try:
            progress_file = self.cache_dir / "indexing_progress.json"
            if not progress_file.exists():
                return None
                
            with open(progress_file, 'r') as f:
                return json.load(f)
        except:
            return None