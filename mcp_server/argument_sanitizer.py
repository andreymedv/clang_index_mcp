"""
Argument Sanitizer - Rule-based compilation argument sanitization.

This module provides a flexible, rule-based system for sanitizing compiler
arguments to ensure compatibility with libclang's programmatic interface.
"""

import json
from pathlib import Path
from typing import List, Dict, Any, Optional

# Handle both package and script imports
try:
    from . import diagnostics
except ImportError:
    import diagnostics


class ArgumentSanitizer:
    """Rule-based compiler argument sanitizer for libclang compatibility."""

    def __init__(self, rules_file: Optional[Path] = None, custom_rules_file: Optional[Path] = None):
        """
        Initialize the argument sanitizer.

        Args:
            rules_file: Path to default rules JSON file (uses built-in if None)
            custom_rules_file: Path to optional custom rules file to extend defaults
        """
        self.rules = []
        self.rules_version = "unknown"

        # Load default rules
        if rules_file is None:
            # Use built-in default rules file
            rules_file = Path(__file__).parent / "sanitization_rules.json"

        if rules_file and rules_file.exists():
            self._load_rules(rules_file)
        else:
            diagnostics.warning(f"Default sanitization rules file not found: {rules_file}")

        # Load and append custom rules if provided
        if custom_rules_file and custom_rules_file.exists():
            self._load_rules(custom_rules_file, append=True)

    def _load_rules(self, rules_file: Path, append: bool = False):
        """
        Load sanitization rules from JSON file.

        Args:
            rules_file: Path to rules JSON file
            append: If True, append to existing rules; if False, replace
        """
        try:
            with open(rules_file, "r") as f:
                data = json.load(f)

            if not append:
                self.rules = []
                self.rules_version = data.get("version", "unknown")

            rules = data.get("rules", [])
            self.rules.extend(rules)

            diagnostics.debug(
                f"Loaded {len(rules)} sanitization rules from {rules_file}"
                f"{' (appended)' if append else ''}"
            )

        except Exception as e:
            diagnostics.error(f"Failed to load sanitization rules from {rules_file}: {e}")

    def sanitize(self, args: List[str]) -> List[str]:
        """
        Sanitize compiler arguments by applying all loaded rules.

        Args:
            args: List of compiler arguments to sanitize

        Returns:
            Sanitized list of arguments
        """
        sanitized = []
        i = 0

        while i < len(args):
            arg = args[i]
            skip_count = self._apply_rules(args, i)

            if skip_count == 0:
                # No rule matched, keep the argument
                sanitized.append(arg)
                i += 1
            else:
                # Rule matched and removed skip_count arguments
                i += skip_count

        return sanitized

    def _apply_rules(self, args: List[str], index: int) -> int:
        """
        Apply sanitization rules to argument at given index.

        Args:
            args: Complete argument list
            index: Current position in argument list

        Returns:
            Number of arguments to skip (0 = keep argument, >0 = remove that many)
        """
        arg = args[index]

        for rule in self.rules:
            rule_type = rule.get("type")

            if rule_type == "exact_match":
                skip = self._apply_exact_match(arg, rule)
                if skip > 0:
                    return skip

            elif rule_type == "prefix_match":
                skip = self._apply_prefix_match(arg, rule)
                if skip > 0:
                    return skip

            elif rule_type == "flag_with_optional_value":
                skip = self._apply_flag_with_optional_value(args, index, rule)
                if skip > 0:
                    return skip

            elif rule_type == "xclang_sequence":
                skip = self._apply_xclang_sequence(args, index, rule)
                if skip > 0:
                    return skip

            elif rule_type == "xclang_conditional_sequence":
                skip = self._apply_xclang_conditional_sequence(args, index, rule)
                if skip > 0:
                    return skip

            elif rule_type == "xclang_option_with_value":
                skip = self._apply_xclang_option_with_value(args, index, rule)
                if skip > 0:
                    return skip

        return 0  # No rule matched

    def _apply_exact_match(self, arg: str, rule: Dict[str, Any]) -> int:
        """Apply exact_match rule."""
        patterns = rule.get("patterns", [])
        if arg in patterns:
            return 1  # Remove this argument
        return 0

    def _apply_prefix_match(self, arg: str, rule: Dict[str, Any]) -> int:
        """Apply prefix_match rule."""
        patterns = rule.get("patterns", [])
        for pattern in patterns:
            if arg.startswith(pattern):
                return 1  # Remove this argument
        return 0

    def _apply_flag_with_optional_value(
        self, args: List[str], index: int, rule: Dict[str, Any]
    ) -> int:
        """Apply flag_with_optional_value rule."""
        pattern = rule.get("pattern")
        if args[index] != pattern:
            return 0

        # Flag matches, check if next argument is a value (not a flag)
        if index + 1 < len(args) and not args[index + 1].startswith("-"):
            return 2  # Remove flag and value
        else:
            return 1  # Remove just the flag

    def _apply_xclang_sequence(self, args: List[str], index: int, rule: Dict[str, Any]) -> int:
        """Apply xclang_sequence rule."""
        if args[index] != "-Xclang":
            return 0

        sequence = rule.get("sequence", [])
        if len(sequence) < 2:
            return 0

        # Check if the sequence matches
        # sequence format: ["-Xclang", "option", "-Xclang", "<arg>"]
        if index + len(sequence) > len(args):
            return 0

        for i, expected in enumerate(sequence):
            if expected == "<arg>":
                # <arg> matches any non-flag argument
                continue
            elif args[index + i] != expected:
                return 0

        # Sequence matches, remove all matching arguments
        return len(sequence)

    def _apply_xclang_conditional_sequence(
        self, args: List[str], index: int, rule: Dict[str, Any]
    ) -> int:
        """Apply xclang_conditional_sequence rule."""
        if args[index] != "-Xclang":
            return 0

        sequence = rule.get("sequence", [])
        condition = rule.get("condition", {})

        if len(sequence) < 2 or not condition:
            return 0

        # Check if sequence matches
        if index + len(sequence) > len(args):
            return 0

        matched_args = []
        for i, expected in enumerate(sequence):
            current_arg = args[index + i]
            if expected == "<arg>":
                matched_args.append(current_arg)
            elif current_arg != expected:
                return 0

        # Sequence matches, check condition
        arg_index = condition.get("arg_index")
        contains_patterns = condition.get("contains", [])

        if arg_index is not None and arg_index < len(matched_args):
            check_arg = matched_args[arg_index].lower()
            for pattern in contains_patterns:
                if pattern in check_arg:
                    # Condition met, remove sequence
                    return len(sequence)

        return 0

    def _apply_xclang_option_with_value(
        self, args: List[str], index: int, rule: Dict[str, Any]
    ) -> int:
        """Apply xclang_option_with_value rule."""
        if args[index] != "-Xclang":
            return 0

        if index + 1 >= len(args):
            return 0

        patterns = rule.get("patterns", [])
        next_arg = args[index + 1]

        if next_arg in patterns:
            # Matched -Xclang <option>
            # Check if there's a value after (non-flag argument)
            if index + 2 < len(args) and not args[index + 2].startswith("-"):
                return 3  # Remove -Xclang, option, and value
            else:
                return 2  # Remove -Xclang and option

        return 0

    def get_rules_info(self) -> Dict[str, Any]:
        """Get information about loaded rules."""
        return {
            "version": self.rules_version,
            "rule_count": len(self.rules),
            "rules": [
                {
                    "id": rule.get("id", "unknown"),
                    "type": rule.get("type", "unknown"),
                    "description": rule.get("description", ""),
                }
                for rule in self.rules
            ],
        }
