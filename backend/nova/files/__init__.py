"""File Agent building blocks: allowed folders, search, documents, Recycle Bin, verified operations."""

from .ops import FileOps
from .scope import FileScope, ScopeError

__all__ = ["FileOps", "FileScope", "ScopeError"]
