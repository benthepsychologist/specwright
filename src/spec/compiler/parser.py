"""Parse Markdown specifications into structured data."""

import re
import os
import hashlib
from pathlib import Path
from typing import Dict, List, Any, Optional
import yaml


class SpecParser:
    """Parse Markdown spec files into structured AIP data."""
    
    REQUIRED_FRONTMATTER = {"tier", "title", "owner", "goal"}
    VALID_TIERS = {"A", "B", "C"}
    VALID_GATES = {"G0", "G1", "G2", "G3", "G4"}
    
    def __init__(self, content: str, source_path: Optional[Path] = None, repo_root: Optional[Path] = None):
        self.content = content
        self.source_path = source_path
        self.repo_root = repo_root or Path.cwd()
        self.lines = content.split('\n')
        self.frontmatter: Dict[str, Any] = {}
        self.sections: Dict[str, str] = {}
        self.plan_steps: List[Dict[str, Any]] = []
        
    def parse(self) -> Dict[str, Any]:
        """Parse the full spec and return structured data."""
        self._parse_frontmatter()
        self._validate_frontmatter()
        self._parse_sections()
        self._parse_plan()
        return self._build_aip()
    
    def _parse_frontmatter(self):
        """Extract YAML frontmatter."""
        if not self.content.startswith('---\n'):
            raise ValueError("Spec must start with YAML frontmatter (---)")
        
        # Find end of frontmatter
        end_idx = self.content.find('\n---\n', 4)
        if end_idx == -1:
            raise ValueError("Frontmatter not properly closed with ---")
        
        frontmatter_text = self.content[4:end_idx]
        self.frontmatter = yaml.safe_load(frontmatter_text) or {}
        
        # Store content after frontmatter
        self.content_body = self.content[end_idx + 5:]
    
    def _validate_frontmatter(self):
        """Validate required frontmatter keys."""
        missing = self.REQUIRED_FRONTMATTER - set(self.frontmatter.keys())
        if missing:
            raise ValueError(f"Missing required frontmatter keys: {missing}")
        
        # Validate tier
        tier = self.frontmatter.get("tier", "").upper()
        if tier not in self.VALID_TIERS:
            raise ValueError(f"Invalid tier '{tier}'. Must be one of {self.VALID_TIERS}")
        self.frontmatter["tier"] = tier
        
        # Validate non-empty strings
        for key in self.REQUIRED_FRONTMATTER:
            if not isinstance(self.frontmatter[key], str) or not self.frontmatter[key].strip():
                raise ValueError(f"Frontmatter key '{key}' must be a non-empty string")
    
    def _parse_sections(self):
        """Parse H2 sections with normalized keys."""
        sections = {}
        current_section = None
        current_content = []
        
        for line in self.content_body.split('\n'):
            if line.startswith('## '):
                if current_section:
                    sections[current_section] = '\n'.join(current_content).strip()
                # Normalize section key: lowercase, strip
                current_section = line[3:].strip().lower()
                current_content = []
            elif current_section:
                current_content.append(line)
        
        if current_section:
            sections[current_section] = '\n'.join(current_content).strip()
        
        self.sections = sections
    
    def _parse_plan(self):
        """Parse Plan section into structured steps."""
        plan_text = self.sections.get("plan", "")
        if not plan_text:
            raise ValueError("Plan section is required")
        
        # Improved step pattern with optional whitespace and stricter gate capture
        step_pattern = re.compile(
            r'^###\s+Step\s+(\d+):\s+(.+?)\s*(?:\[(G[0-4]\s*:\s*.+?)\])?\s*$',
            re.MULTILINE
        )
        steps = []
        
        for match in step_pattern.finditer(plan_text):
            step_num = int(match.group(1))
            step_title = match.group(2).strip()
            gate_ref = match.group(3).strip() if match.group(3) else None
            
            # Extract step body
            start = match.end()
            next_match = step_pattern.search(plan_text, start)
            end = next_match.start() if next_match else len(plan_text)
            step_body = plan_text[start:end].strip()
            
            # Parse step components
            step = {
                "index": step_num,
                "title": step_title,
                "gate_ref": gate_ref,
                "prompts": self._extract_prompts(step_body),
                "commands": self._extract_commands(step_body),
                "outputs": self._extract_outputs(step_body)
            }
            
            steps.append(step)
        
        if not steps:
            raise ValueError("Plan must contain at least one step (### Step N: ...)")
        
        self.plan_steps = sorted(steps, key=lambda s: s["index"])
    
    def _extract_prompts(self, text: str) -> List[str]:
        """Extract prompt sections."""
        prompts = []
        in_prompt = False
        current_prompt = []
        
        for line in text.split('\n'):
            if line.startswith('**Prompt:**'):
                in_prompt = True
                continue
            elif line.startswith('**Commands:**') or line.startswith('**Outputs:**'):
                if in_prompt and current_prompt:
                    prompts.append('\n'.join(current_prompt).strip())
                    current_prompt = []
                in_prompt = False
            elif in_prompt and line.strip():
                current_prompt.append(line)
        
        if current_prompt:
            prompts.append('\n'.join(current_prompt).strip())
        
        return prompts
    
    def _extract_commands(self, text: str) -> List[Dict[str, str]]:
        """Extract command code blocks - handle multiple Commands sections."""
        commands = []
        code_block_pattern = re.compile(r'```(\w+)?\n(.*?)```', re.DOTALL)
        
        # Find all Commands sections
        for cs in re.finditer(r'\*\*Commands:\*\*(.*?)(?=\n\*\*|$)', text, re.DOTALL):
            for match in code_block_pattern.finditer(cs.group(1)):
                lang = match.group(1) or "bash"
                code = match.group(2).strip()
                commands.append({"lang": lang, "code": code})
        
        return commands
    
    def _extract_outputs(self, text: str) -> List[str]:
        """Extract output paths with safe regex and path validation."""
        outputs = []
        in_outputs = False
        
        for line in text.split('\n'):
            if line.startswith('**Outputs:**'):
                in_outputs = True
                continue
            elif line.startswith('**'):
                in_outputs = False
            elif in_outputs:
                # Safe regex: capture inside backticks, allow - or *
                m = re.match(r'^\s*[-*]\s+`([^`]+)`', line)
                if m:
                    path = m.group(1).strip()
                    
                    # Validate path is relative and within repo
                    try:
                        resolved = (self.repo_root / path).resolve()
                        repo_resolved = self.repo_root.resolve()
                        
                        if not str(resolved).startswith(str(repo_resolved) + os.sep):
                            raise ValueError(f"Output path escapes repo root: {path}")
                    except (ValueError, OSError) as e:
                        raise ValueError(f"Invalid output path '{path}': {e}")
                    
                    outputs.append(path)
        
        return outputs
    
    def _parse_acceptance_criteria(self) -> List[Dict[str, str]]:
        """Parse acceptance criteria checkboxes."""
        criteria = []
        # Use normalized section key
        objective_text = self.sections.get("acceptance criteria", "")
        
        checkbox_pattern = re.compile(r'^- \[([ x])\] (.+)$', re.MULTILINE)
        for match in checkbox_pattern.finditer(objective_text):
            status = "done" if match.group(1) == 'x' else "pending"
            text = match.group(2).strip()
            criteria.append({"text": text, "status": status})
        
        return criteria
    
    def _parse_tools_models(self) -> tuple:
        """Parse Models & Tools section."""
        section = self.sections.get("models & tools", "")
        tools = []
        models = []
        
        tools_match = re.search(r'\*\*Tools:\*\*\s*(.+?)(?=\n\n|\*\*|$)', section, re.DOTALL)
        if tools_match:
            tools_text = tools_match.group(1).strip()
            tools = [t.strip() for t in tools_text.split(',') if t.strip()]
        
        models_match = re.search(r'\*\*Models:\*\*\s*(.+?)(?=\n\n|\*\*|$)', section, re.DOTALL)
        if models_match:
            models_text = models_match.group(1).strip()
            if models_text and models_text != "(to be filled by defaults)":
                models = [m.strip() for m in models_text.split(',') if m.strip()]
        
        # Default to empty list if not specified
        return tools, models
    
    def _parse_repo(self) -> Dict[str, str]:
        """Parse Repository section."""
        section = self.sections.get("repository", "")
        repo = {}
        
        branch_match = re.search(r'\*\*Branch:\*\*\s*`(.+?)`', section)
        if branch_match:
            repo["branch"] = branch_match.group(1)
        
        strategy_match = re.search(r'\*\*Merge Strategy:\*\*\s*(\w+)', section)
        if strategy_match:
            repo["merge_strategy"] = strategy_match.group(1)
        
        block_match = re.search(r'\*\*Block Paths:\*\*\s*(.+)', section)
        if block_match:
            paths_text = block_match.group(1).strip()
            # Parse comma-separated paths in backticks
            paths = re.findall(r'`([^`]+)`', paths_text)
            if paths:
                repo["block_paths"] = paths
        
        return repo
    
    def _build_aip(self) -> Dict[str, Any]:
        """Build final AIP structure."""
        # Compute source hash
        source_hash = hashlib.sha256(self.content.encode('utf-8')).hexdigest()
        
        # Parse context (use normalized keys)
        context_text = self.sections.get("context", "")
        background = re.search(r'### Background\s+(.+?)(?=###|$)', context_text, re.DOTALL)
        constraints = re.search(r'### Constraints\s+(.+?)(?=###|$)', context_text, re.DOTALL)
        
        # Parse tools and models
        tools, models = self._parse_tools_models()
        
        # Parse repo
        repo = self._parse_repo()
        
        # Compute relative path if source_path provided
        source_md_rel = None
        if self.source_path:
            try:
                source_md_rel = str(self.source_path.relative_to(self.repo_root))
            except ValueError:
                source_md_rel = str(self.source_path)
        
        aip = {
            "meta": {
                "source_md_path": str(self.source_path) if self.source_path else None,
                "source_md_rel": source_md_rel,
                "source_md_sha256": source_hash,
                "compiler_version": "spec-compiler/0.1.0",
                "compiled_at": None,  # Intentionally null for determinism
                "tier": self.frontmatter["tier"],
                "title": self.frontmatter["title"],
                "owner": self.frontmatter["owner"],
                "goal": self.frontmatter["goal"],
                "labels": self.frontmatter.get("labels", [])
            },
            "objective": self.sections.get("objective", "").strip(),
            "acceptance": {
                "criteria": self._parse_acceptance_criteria()
            },
            "context": {
                "background": background.group(1).strip() if background else "",
                "constraints": constraints.group(1).strip() if constraints else ""
            },
            "plan": {
                "steps": self.plan_steps
            },
            "tools": tools,
            "models": models,
            "repo": repo
        }
        
        return aip
