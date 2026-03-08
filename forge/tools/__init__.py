from .registry import ToolRegistry
from . import filesystem, shell, browser

def create_registry() -> ToolRegistry:
    """Build a ToolRegistry with all available tools registered."""
    reg = ToolRegistry()
    filesystem.register(reg)
    shell.register(reg)
    browser.register(reg)
    return reg
