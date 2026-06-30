"""SQLite-backed storage and lookup for type aliases.

Isolates all SQL operations on the ``type_aliases`` table from the rest of the
persistence layer.
"""

import json
import sqlite3
from typing import Any, Dict, List, Optional

from .._core import diagnostics
from .._symbols.ports.parser import TypeAliasRecord


def save_type_aliases_batch(conn: sqlite3.Connection, aliases: List[TypeAliasRecord]) -> int:
    """Batch insert type aliases using a transaction."""
    if not aliases:
        return 0

    try:
        with conn:
            conn.executemany(
                """
                INSERT OR REPLACE INTO type_aliases (
                    alias_name, qualified_name, target_type, canonical_type,
                    file, line, column, alias_kind, namespace,
                    is_template_alias, template_params, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        alias.alias_name,
                        alias.qualified_name,
                        alias.target_type,
                        alias.canonical_type,
                        alias.file,
                        alias.line,
                        alias.column,
                        alias.alias_kind,
                        alias.namespace,
                        1 if alias.is_template_alias else 0,
                        alias.template_params,
                        alias.created_at,
                    )
                    for alias in aliases
                ],
            )

        diagnostics.debug(f"Saved {len(aliases)} type aliases to database")
        return len(aliases)
    except Exception as e:
        diagnostics.error(f"Failed to batch save {len(aliases)} type aliases: {e}")
        return 0


def get_aliases_for_canonical(conn: sqlite3.Connection, canonical_type: str) -> List[str]:
    """Get all alias names (short and qualified) that resolve to a canonical type."""
    try:
        cursor = conn.execute(
            """
            SELECT alias_name, qualified_name
            FROM type_aliases
            WHERE canonical_type = ?
            """,
            (canonical_type,),
        )

        alias_names = []
        for row in cursor.fetchall():
            alias_names.append(row["alias_name"])
            if row["qualified_name"] != row["alias_name"]:
                alias_names.append(row["qualified_name"])

        return alias_names
    except Exception as e:
        diagnostics.error(f"Failed to get aliases for canonical type '{canonical_type}': {e}")
        return []


def get_canonical_for_alias(conn: sqlite3.Connection, alias_name: str) -> Optional[str]:
    """Get the canonical type for a given alias name (short or qualified)."""
    try:
        cursor = conn.execute(
            """
            SELECT canonical_type
            FROM type_aliases
            WHERE alias_name = ? OR qualified_name = ?
            LIMIT 1
            """,
            (alias_name, alias_name),
        )

        row = cursor.fetchone()
        if row:
            result: str = row["canonical_type"]
            return result

        return None
    except Exception as e:
        diagnostics.error(f"Failed to get canonical type for alias '{alias_name}': {e}")
        return None


def get_type_alias_info(conn: sqlite3.Connection, type_name: str) -> Optional[Dict[str, Any]]:
    """Get high-level info for a known alias from the type_aliases table."""
    try:
        cursor = conn.execute(
            """
            SELECT alias_name, qualified_name, canonical_type, file, line, namespace,
                   is_template_alias, template_params
            FROM type_aliases
            WHERE alias_name = ? OR qualified_name = ?
            LIMIT 1
            """,
            (type_name, type_name),
        )
        row = cursor.fetchone()
        if not row:
            return None

        alias_names = get_aliases_for_canonical(conn, row["canonical_type"])
        aliases = get_type_alias_details(conn, alias_names)

        return {
            "canonical_type": row["canonical_type"],
            "qualified_name": row["qualified_name"],
            "namespace": row["namespace"],
            "file": row["file"],
            "line": row["line"],
            "input_was_alias": True,
            "is_ambiguous": False,
            "aliases": aliases,
        }
    except Exception as e:
        diagnostics.warning(f"Error querying type_aliases for '{type_name}': {e}")
        return None


def get_type_alias_details(
    conn: sqlite3.Connection, alias_names: List[str]
) -> List[Dict[str, Any]]:
    """Get detailed records from the type_aliases table for a list of alias names."""
    unique_aliases: Dict[str, Dict[str, Any]] = {}
    try:
        for alias_name in alias_names:
            cursor = conn.execute(
                """
                SELECT alias_name, qualified_name, canonical_type, file, line, namespace,
                       is_template_alias, template_params
                FROM type_aliases
                WHERE alias_name = ? OR qualified_name = ?
                """,
                (alias_name, alias_name),
            )
            row = cursor.fetchone()
            if row:
                qualified_alias = row["qualified_name"]
                if qualified_alias not in unique_aliases:
                    alias_dict = {
                        "name": row["alias_name"],
                        "qualified_name": qualified_alias,
                        "file": row["file"],
                        "line": row["line"],
                    }
                    if row["is_template_alias"]:
                        alias_dict["is_template_alias"] = True
                        if row["template_params"]:
                            alias_dict["template_params"] = json.loads(row["template_params"])
                    unique_aliases[qualified_alias] = alias_dict
    except Exception as e:
        diagnostics.debug(f"Failed to get alias details: {e}")
    return list(unique_aliases.values())


def get_all_alias_mappings(conn: sqlite3.Connection) -> Dict[str, str]:
    """Get all alias → canonical mappings, including qualified names."""
    try:
        cursor = conn.execute("""
            SELECT alias_name, qualified_name, canonical_type
            FROM type_aliases
            """)

        mappings = {}
        for row in cursor.fetchall():
            mappings[row["alias_name"]] = row["canonical_type"]
            if row["qualified_name"] != row["alias_name"]:
                mappings[row["qualified_name"]] = row["canonical_type"]

        return mappings
    except Exception as e:
        diagnostics.error(f"Failed to get all alias mappings: {e}")
        return {}
