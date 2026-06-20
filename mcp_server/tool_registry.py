from typing import Any, Callable, Dict, Optional


class ToolRegistry:
    """
    A simple registry for MCP tools to break circular dependencies.
    """

    _tools: Dict[str, Callable] = {}

    @classmethod
    def register(cls, name: str, handler: Callable) -> None:
        """Registers a tool handler."""
        cls._tools[name] = handler

    @classmethod
    def get_handler(cls, name: str) -> Optional[Callable]:
        """Retrieves a tool handler by name."""
        return cls._tools.get(name)

    @classmethod
    def call_tool(cls, name: str, *args: Any, **kwargs: Any) -> Any:
        """Invokes a tool handler by name."""
        handler = cls.get_handler(name)
        if not handler:
            raise ValueError(f"Tool '{name}' not found in registry.")
        return handler(*args, **kwargs)
