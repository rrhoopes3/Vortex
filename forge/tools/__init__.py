from .registry import ToolRegistry
from . import filesystem, shell

def create_registry() -> ToolRegistry:
    """Build a ToolRegistry with all available tools registered."""
    reg = ToolRegistry()
    filesystem.register(reg)
    shell.register(reg)
    # browser.register(reg)  # Phase D — uncomment after playwright install
    return reg
