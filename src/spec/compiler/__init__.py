"""Spec compiler - parses and validates Markdown specs."""

from .compiler import compile_spec
from .parser import SpecParser

__all__ = ["SpecParser", "compile_spec"]
