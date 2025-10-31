"""Compile Markdown specs to YAML AIPs."""

import hashlib
from pathlib import Path
from typing import Optional
import yaml

from .parser import SpecParser


def compile_spec(
    spec_path: Path,
    output_path: Optional[Path] = None,
    overwrite: bool = False,
    validate: bool = True
) -> Path:
    """
    Compile a Markdown spec to YAML AIP.
    
    Args:
        spec_path: Path to .md spec file
        output_path: Output path (defaults to spec_path.with_suffix('.compiled.yaml'))
        overwrite: Allow overwriting existing compiled file even if content differs
        validate: Validate Markdown structure during compilation (default: True)
    
    Returns:
        Path to compiled YAML file
    
    Raises:
        ValueError: If compilation fails or round-trip check fails
    """
    if not spec_path.exists():
        raise FileNotFoundError(f"Spec file not found: {spec_path}")
    
    # Read source
    content = spec_path.read_text(encoding='utf-8')
    
    # Parse with validation
    parser = SpecParser(content, source_path=spec_path)
    
    try:
        aip_data = parser.parse()
    except (ValueError, KeyError, AttributeError) as e:
        raise ValueError(f"Markdown validation failed: {e}")
    
    # Determine output path
    if output_path is None:
        output_path = spec_path.with_suffix('.compiled.yaml')
    
    # Serialize with canonical ordering
    yaml_content = _serialize_canonical(aip_data)
    
    # Round-trip guard
    if output_path.exists() and not overwrite:
        existing_content = output_path.read_text(encoding='utf-8')
        if existing_content != yaml_content:
            raise ValueError(
                f"Compiled YAML already exists with different content: {output_path}\n"
                "Use --overwrite to force recompilation, or verify your changes."
            )
    
    # Write output
    output_path.write_text(yaml_content, encoding='utf-8')
    
    return output_path


def _serialize_canonical(data: dict) -> str:
    """
    Serialize data to YAML with canonical ordering.
    
    - Sort all dict keys
    - Normalize whitespace
    - Strip trailing spaces
    - Disable anchors/aliases
    - Use consistent formatting
    """
    # Custom dumper for deterministic output
    class CanonicalDumper(yaml.SafeDumper):
        def ignore_aliases(self, data):
            """Disable anchors/aliases for full determinism."""
            return True
    
    def represent_none(self, _):
        return self.represent_scalar('tag:yaml.org,2002:null', 'null')
    
    CanonicalDumper.add_representer(type(None), represent_none)
    
    # Dump with sorted keys and consistent style
    yaml_str = yaml.dump(
        data,
        Dumper=CanonicalDumper,
        default_flow_style=False,
        sort_keys=True,
        allow_unicode=True,
        width=100
    )
    
    # Normalize whitespace
    lines = yaml_str.split('\n')
    lines = [line.rstrip() for line in lines]  # Strip trailing spaces
    
    return '\n'.join(lines) + '\n'
