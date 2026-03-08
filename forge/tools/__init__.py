from .registry import ToolRegistry
from . import (
    filesystem, shell, browser, http, python_repl,
    git_ops, search, clipboard, image, database, archive,
)


def create_registry() -> ToolRegistry:
    """Build a ToolRegistry with all available tools registered."""
    reg = ToolRegistry()
    filesystem.register(reg)
    shell.register(reg)
    browser.register(reg)
    http.register(reg)
    python_repl.register(reg)
    git_ops.register(reg)
    search.register(reg)
    clipboard.register(reg)
    image.register(reg)
    database.register(reg)
    archive.register(reg)
    return reg
