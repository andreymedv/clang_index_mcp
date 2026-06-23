"""Type alias expansion for unified symbol search.

Given a type name, resolves its canonical form and any registered aliases so
that searches can match symbols that refer to the same type through different
names (e.g. a typedef and its underlying std::function type).
"""

from typing import List

from .._core import diagnostics


class TypeAliasExpander:
    """Expands a type name to include aliases and canonical equivalents."""

    def __init__(self, cache_manager):
        """
        Args:
            cache_manager: Object providing get_canonical_for_alias() and
                           get_aliases_for_canonical(). May be None.
        """
        self.cache_manager = cache_manager

    def collect_alias_expansions(self, type_name: str) -> List[str]:
        """Collect all alias and canonical type expansions for a given type name."""
        expanded_names = [type_name]

        if self.cache_manager is None:
            return expanded_names

        try:
            canonical = self.cache_manager.get_canonical_for_alias(type_name)
            if canonical and canonical != type_name:
                expanded_names.append(canonical)

            aliases = self.cache_manager.get_aliases_for_canonical(type_name)
            for alias in aliases or []:
                if alias not in expanded_names:
                    expanded_names.append(alias)

            if canonical:
                aliases_of_canonical = self.cache_manager.get_aliases_for_canonical(canonical)
                for alias in aliases_of_canonical or []:
                    if alias not in expanded_names:
                        expanded_names.append(alias)

        except Exception as e:
            diagnostics.debug(f"Failed to expand type name '{type_name}': {e}")

        return expanded_names

    def expand_type_name(self, type_name: str) -> List[str]:
        """
        Expand a type name to include all equivalent type names (aliases and canonical).

        Phase 1.3: Type Alias Tracking - Infrastructure for automatic search unification

        This method enables future parameter type filtering to automatically find functions
        using both aliases and canonical types. For example, searching for "ErrorCallback"
        will also find functions using "std::function<void(const Error&)>".

        Args:
            type_name: Type name to expand (can be alias or canonical type)

        Returns:
            List of equivalent type names including:
            - The original type name
            - All aliases pointing to it (if it's a canonical type)
            - The canonical type (if it's an alias)

        Example:
            type_name = "ErrorCallback"
            returns ["ErrorCallback", "std::function<void(const Error&)>"]

            type_name = "std::function<void(const Error&)>"
            returns ["std::function<void(const Error&)>", "ErrorCallback"]
        """
        if not self.cache_manager:
            return [type_name]

        return self.collect_alias_expansions(type_name)


def expand_type_name(type_name: str, cache_manager) -> List[str]:
    """Convenience function for one-shot type alias expansion."""
    return TypeAliasExpander(cache_manager).expand_type_name(type_name)
