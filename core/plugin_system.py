"""
Plugin System - Auto-discovery of tools via @tool decorator.
Generates JSON schemas automatically using Pydantic.
"""
from __future__ import annotations
import inspect
import json
import asyncio
from dataclasses import dataclass, field
from typing import Callable, Any, get_type_hints, get_origin, get_args, Union
from pathlib import Path
from enum import Enum
import importlib
import importlib.util
import sys
from functools import wraps

from pydantic import BaseModel, create_model, Field


class ToolCategory(Enum):
    """Tool categories for organization."""
    SYSTEM = "system"
    FILESYSTEM = "filesystem"
    WEB = "web"
    MEMORY = "memory"
    CUSTOM = "custom"
    SECURITY = "security"


@dataclass
class ToolSpec:
    """Tool specification with auto-generated schema."""
    name: str
    description: str
    function: Callable
    category: ToolCategory = ToolCategory.CUSTOM
    parameters_schema: dict = field(default_factory=dict)
    required_params: list[str] = field(default_factory=list)
    is_async: bool = False
    is_dangerous: bool = False
    confirmation_message: str | None = None

    def to_gemini_function(self) -> dict:
        """Convert to Gemini function calling format."""
        return {
            "type": "function",
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters_schema,
        }


def _python_type_to_json_schema(param_type: Any, param_name: str = "") -> dict:
    """Convert Python type annotation to JSON schema."""
    origin = get_origin(param_type)
    args = get_args(param_type)

    # Handle Optional[T] -> Union[T, None]
    if origin is Union or (hasattr(type(None), '__class__') and param_type is type(None)):
        if args:
            # Find non-None type
            non_none = [a for a in args if a is not type(None)]
            if non_none:
                return _python_type_to_json_schema(non_none[0], param_name)
        return {"type": "string"}  # fallback

    # Basic types
    type_map = {
        str: {"type": "string"},
        int: {"type": "integer"},
        float: {"type": "number"},
        bool: {"type": "boolean"},
        list: {"type": "array", "items": {}},
        dict: {"type": "object"},
    }

    if param_type in type_map:
        return type_map[param_type]

    # Handle List[T], Dict[K, V], etc.
    if origin in (list, List):
        if args:
            return {"type": "array", "items": _python_type_to_json_schema(args[0], param_name)}
        return {"type": "array", "items": {}}

    if origin in (dict, Dict):
        return {"type": "object"}

    # Handle Literal
    if origin is Literal:
        return {"type": "string", "enum": list(args)}

    # Handle Enum
    if inspect.isclass(param_type) and issubclass(param_type, Enum):
        return {"type": "string", "enum": [e.value for e in param_type]}

    # Handle Pydantic models
    if inspect.isclass(param_type) and issubclass(param_type, BaseModel):
        return param_type.model_json_schema()

    # Default fallback
    return {"type": "string"}


def _generate_schema_from_signature(func: Callable) -> tuple[dict, list[str]]:
    """Generate JSON schema from function signature."""
    sig = inspect.signature(func)
    type_hints = get_type_hints(func)

    properties = {}
    required = []

    for param_name, param in sig.parameters.items():
        if param_name in ("self", "cls"):
            continue

        param_type = type_hints.get(param_name, str)
        param_schema = _python_type_to_json_schema(param_type, param_name)

        # Add description from docstring if available
        if param.default is not inspect.Parameter.empty:
            # Optional parameter
            param_schema["default"] = param.default
        else:
            required.append(param_name)

        properties[param_name] = param_schema

    schema = {
        "type": "object",
        "properties": properties,
    }

    if required:
        schema["required"] = required

    return schema, required


# Global registry
_tool_registry: dict[str, ToolSpec] = {}
_tool_categories: dict[ToolCategory, list[ToolSpec]] = {cat: [] for cat in ToolCategory}


def tool(
    name: str | None = None,
    description: str | None = None,
    category: ToolCategory = ToolCategory.CUSTOM,
    dangerous: bool = False,
    confirmation_message: str | None = None,
):
    """
    Decorator to register a function as a tool.

    Usage:
        @tool(description="Abre o Bloco de Notas.")
        def open_notepad() -> dict:
            ...

        @tool(name="custom_name", category=ToolCategory.FILESYSTEM)
        def my_function(path: str, recursive: bool = False) -> dict:
            ...
    """
    def decorator(func: Callable) -> Callable:
        # Generate schema from signature
        schema, required = _generate_schema_from_signature(func)

        # Determine tool name
        tool_name = name or func.__name__

        # Determine description
        tool_description = description or func.__doc__ or f"Execute {tool_name}"

        # Check if async
        is_async = asyncio.iscoroutinefunction(func)

        # Create spec
        spec = ToolSpec(
            name=tool_name,
            description=tool_description,
            function=func,
            category=category,
            parameters_schema=schema,
            required_params=required,
            is_async=is_async,
            is_dangerous=dangerous,
            confirmation_message=confirmation_message,
        )

        # Register
        _tool_registry[tool_name] = spec
        _tool_categories[category].append(spec)

        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            return func(*args, **kwargs)

        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            return await func(*args, **kwargs)

        # Return appropriate wrapper
        if is_async:
            return async_wrapper
        return sync_wrapper

    return decorator


def get_tool(name: str) -> ToolSpec | None:
    """Get tool spec by name."""
    return _tool_registry.get(name)


def get_all_tools() -> list[ToolSpec]:
    """Get all registered tools."""
    return list(_tool_registry.values())


def get_tools_by_category(category: ToolCategory) -> list[ToolSpec]:
    """Get tools by category."""
    return _tool_categories.get(category, [])


def get_gemini_functions() -> list[dict]:
    """Get all tools in Gemini function calling format."""
    return [spec.to_gemini_function() for spec in _tool_registry.values()]


def clear_registry() -> None:
    """Clear the tool registry (useful for testing)."""
    global _tool_registry, _tool_categories
    _tool_registry.clear()
    _tool_categories = {cat: [] for cat in ToolCategory}


class PluginLoader:
    """Loads tools from plugin modules."""

    def __init__(self, plugin_dirs: list[str] | None = None):
        self.plugin_dirs = plugin_dirs or ["tools"]
        self.loaded_modules: list[str] = []

    def discover_plugins(self) -> list[str]:
        """Discover plugin modules in plugin directories."""
        plugins = []
        for plugin_dir in self.plugin_dirs:
            path = Path(plugin_dir)
            if not path.exists():
                continue

            for py_file in path.glob("*.py"):
                if py_file.name.startswith("_"):
                    continue
                module_name = py_file.stem
                plugins.append(f"{plugin_dir}.{module_name}")

        return plugins

    def load_plugins(self) -> int:
        """Load all discovered plugins. Returns count of loaded modules."""
        count = 0
        for module_name in self.discover_plugins():
            try:
                if module_name not in sys.modules:
                    importlib.import_module(module_name)
                else:
                    importlib.reload(sys.modules[module_name])
                self.loaded_modules.append(module_name)
                count += 1
            except Exception as e:
                print(f"[PluginLoader] Failed to load {module_name}: {e}")

        return count

    def load_plugin(self, module_name: str) -> bool:
        """Load a specific plugin module."""
        try:
            if module_name in sys.modules:
                importlib.reload(sys.modules[module_name])
            else:
                importlib.import_module(module_name)
            if module_name not in self.loaded_modules:
                self.loaded_modules.append(module_name)
            return True
        except Exception as e:
            print(f"[PluginLoader] Failed to load {module_name}: {e}")
            return False


# Global plugin loader
_plugin_loader: PluginLoader | None = None


def get_plugin_loader(plugin_dirs: list[str] | None = None) -> PluginLoader:
    """Get global plugin loader instance."""
    global _plugin_loader
    if _plugin_loader is None:
        _plugin_loader = PluginLoader(plugin_dirs)
    return _plugin_loader


# Convenience: load all tools on import
def auto_discover_tools(plugin_dirs: list[str] | None = None) -> int:
    """Auto-discover and load all tools. Returns count of loaded modules."""
    loader = get_plugin_loader(plugin_dirs)
    return loader.load_plugins()


# Re-export for convenience
__all__ = [
    "tool",
    "ToolSpec",
    "ToolCategory",
    "get_tool",
    "get_all_tools",
    "get_tools_by_category",
    "get_gemini_functions",
    "clear_registry",
    "PluginLoader",
    "get_plugin_loader",
    "auto_discover_tools",
]