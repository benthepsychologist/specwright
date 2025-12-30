"""Parse Markdown specifications into structured data."""

import os
import re
from pathlib import Path
from typing import Any

import yaml


class SpecParser:
    """Parse Markdown spec files into structured AIP data."""

    REQUIRED_FRONTMATTER = {"tier", "title", "owner", "goal"}
    VALID_TIERS = {"A", "B", "C"}
    VALID_GATES = {"G0", "G1", "G2", "G3", "G4"}

    def __init__(self, content: str, source_path: Path | None = None, repo_root: Path | None = None):
        self.content = content
        self.source_path = source_path
        self.repo_root = repo_root or Path.cwd()
        self.lines = content.split('\n')
        self.frontmatter: dict[str, Any] = {}
        self.sections: dict[str, str] = {}
        self.plan_steps: list[dict[str, Any]] = []

    def parse(self) -> dict[str, Any]:
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

        in_code_fence = False

        for line in self.content_body.split('\n'):
            # Track fenced code blocks so we don't treat headings inside examples as sections.
            if line.startswith('```'):
                in_code_fence = not in_code_fence

            if (not in_code_fence) and line.startswith('## '):
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
                "outputs": self._extract_outputs(step_body),
                "gate_review": self._extract_gate_review(step_body),
                "role": self._extract_role(step_body),
                "allowed_paths": self._extract_path_list(step_body, "Allowed Paths"),
                "forbidden_paths": self._extract_path_list(step_body, "Forbidden Paths"),
                "verification_commands": self._extract_verification_commands(step_body),
            }

            steps.append(step)

        if not steps:
            raise ValueError("Plan must contain at least one step (### Step N: ...)")

        self.plan_steps = sorted(steps, key=lambda s: s["index"])

    def _extract_prompts(self, text: str) -> list[str]:
        """Extract prompt sections.

        Stops at any known section marker to avoid including executor fields in prompt.
        """
        prompts = []
        in_prompt = False
        current_prompt = []

        # Section markers that terminate prompt extraction
        section_markers = (
            '**Commands:**', '**Outputs:**', '**Allowed Paths:**',
            '**Forbidden Paths:**', '**Verification Commands:**'
        )

        for line in text.split('\n'):
            if line.startswith('**Prompt:**'):
                in_prompt = True
                continue
            elif any(line.startswith(marker) for marker in section_markers):
                if in_prompt and current_prompt:
                    prompts.append('\n'.join(current_prompt).strip())
                    current_prompt = []
                in_prompt = False
            elif in_prompt and line.strip():
                current_prompt.append(line)

        if current_prompt:
            prompts.append('\n'.join(current_prompt).strip())

        return prompts

    def _extract_commands(self, text: str) -> list[dict[str, str]]:
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

    def _extract_outputs(self, text: str) -> list[str]:
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

    def _extract_role(self, text: str) -> str | None:
        """Extract role from step body (e.g., **Role:** agentic)."""
        match = re.search(r'\*\*Role:\*\*\s*(\w+)', text)
        return match.group(1).strip() if match else None

    def _extract_path_list(self, text: str, section_name: str) -> list[str]:
        """Extract a list of paths from a section like **Allowed Paths:** or **Forbidden Paths:**."""
        paths: list[str] = []

        # Support inline form: **Allowed Paths:** `src/**` (legacy templates)
        inline_prefix = f"**{section_name}:**"
        for line in text.split("\n"):
            stripped = line.strip()
            if stripped.startswith(inline_prefix):
                inline = re.findall(r"`([^`]+)`", stripped)
                if inline:
                    paths.extend([p.strip() for p in inline if p.strip()])
                else:
                    remainder = stripped[len(inline_prefix) :].strip()
                    if remainder:
                        # Allow comma-separated or whitespace-separated single-line values.
                        for part in re.split(r"\s*,\s*", remainder):
                            part = part.strip()
                            if part:
                                paths.append(part)
        pattern = rf'\*\*{section_name}:\*\*(.*?)(?=\n\*\*|\n###|$)'
        match = re.search(pattern, text, re.DOTALL)
        if match:
            section_text = match.group(1)
            # Extract paths from bullet points with backticks or quoted strings
            for line in section_text.split('\n'):
                line = line.strip()
                if line.startswith('-') or line.startswith('*'):
                    # Try backtick format: - `src/**`
                    backtick_match = re.search(r'`([^`]+)`', line)
                    if backtick_match:
                        paths.append(backtick_match.group(1))
                    else:
                        # Try plain format: - src/**
                        plain_match = re.match(r'^[-*]\s+(.+)$', line)
                        if plain_match:
                            paths.append(plain_match.group(1).strip())
        # Deduplicate while preserving order
        seen: set[str] = set()
        result: list[str] = []
        for p in paths:
            if p not in seen:
                seen.add(p)
                result.append(p)
        return result

    def _extract_verification_commands(self, text: str) -> list[str]:
        """Extract verification commands from **Verification Commands:** section."""
        commands: list[str] = []

        # Support inline legacy form: **Verification:** `python -c "..."`
        for line in text.split("\n"):
            stripped = line.strip()
            if stripped.startswith("**Verification:**"):
                inline = re.findall(r"`([^`]+)`", stripped)
                for cmd in inline:
                    cmd = cmd.strip()
                    if cmd:
                        commands.append(cmd)
        pattern = r'\*\*Verification Commands:\*\*(.*?)(?=\n\*\*[A-Z]|\n###|$)'
        match = re.search(pattern, text, re.DOTALL)
        if match:
            section_text = match.group(1)
            # Extract commands from code blocks
            code_block_pattern = re.compile(r'```(?:\w+)?\n(.*?)```', re.DOTALL)
            for block_match in code_block_pattern.finditer(section_text):
                code = block_match.group(1).strip()
                # Split by newlines to get individual commands
                for line in code.split('\n'):
                    line = line.strip()
                    if line and not line.startswith('#'):
                        commands.append(line)
        # Deduplicate while preserving order
        seen: set[str] = set()
        result: list[str] = []
        for c in commands:
            if c not in seen:
                seen.add(c)
                result.append(c)
        return result

    def _extract_gate_review(self, text: str) -> dict[str, Any] | None:
        """Extract gate review block from step body.

        Returns:
            Dict with gate review metadata or None if no gate block found
            Structure:
            {
                "checklist": {
                    "Category Name": ["item1", "item2", ...],
                    ...
                },
                "approval_metadata": {
                    "reviewer": "",
                    "date": "",
                    "rationale": ""
                }
            }
        """
        # Find gate review block
        gate_start = text.find('<!-- GATE_REVIEW_START -->')
        gate_end = text.find('<!-- GATE_REVIEW_END -->')

        if gate_start == -1 or gate_end == -1:
            return None

        gate_content = text[gate_start:gate_end + len('<!-- GATE_REVIEW_END -->')].strip()

        # Parse checklist items
        checklist: dict[str, list[str]] = {}
        current_category = None

        # Extract checklist section
        checklist_match = re.search(
            r'#### Gate Review Checklist\s+(.*?)#### Approval Decision',
            gate_content,
            re.DOTALL
        )

        if checklist_match:
            checklist_text = checklist_match.group(1)

            # Parse categories and items
            category_pattern = re.compile(r'^#{5}\s+(.+)$', re.MULTILINE)
            item_pattern = re.compile(r'^-\s+\[\s?\]\s+(.+)$', re.MULTILINE)

            lines = checklist_text.split('\n')
            for line in lines:
                # Check for category header
                cat_match = category_pattern.match(line)
                if cat_match:
                    current_category = cat_match.group(1).strip()
                    checklist[current_category] = []
                    continue

                # Check for checklist item
                item_match = item_pattern.match(line)
                if item_match and current_category:
                    checklist[current_category].append(item_match.group(1).strip())

        # Parse approval metadata structure
        approval_metadata = {
            "reviewer": "",
            "date": "",
            "rationale": ""
        }

        return {
            "checklist": checklist,
            "approval_metadata": approval_metadata
        }

    def _parse_acceptance_criteria(self) -> list[dict[str, str]]:
        """Parse acceptance criteria checkboxes or bullet points."""
        criteria = []
        # Get objective section and look for Acceptance Criteria H3
        objective_text = self.sections.get("objective", "")

        # Find Acceptance Criteria subsection
        ac_match = re.search(r'### Acceptance Criteria\s*\n(.*?)(?=\n###|$)', objective_text, re.DOTALL | re.IGNORECASE)
        if not ac_match:
            # Try looking for it as standalone H2 section (legacy)
            objective_text = self.sections.get("acceptance criteria", "")
            ac_text = objective_text
        else:
            ac_text = ac_match.group(1)

        # Parse checkbox format: - [ ] or - [x]
        checkbox_pattern = re.compile(r'^- \[([ x])\] (.+)$', re.MULTILINE)
        for match in checkbox_pattern.finditer(ac_text):
            status = "done" if match.group(1) == 'x' else "pending"
            text = match.group(2).strip()
            criteria.append({"text": text, "status": status})

        # If no checkboxes found, parse plain bullet points: -
        if not criteria:
            bullet_pattern = re.compile(r'^- (?!\[)(.+)$', re.MULTILINE)
            for match in bullet_pattern.finditer(ac_text):
                text = match.group(1).strip()
                if text:  # Ignore empty bullets
                    criteria.append({"text": text, "status": "pending"})

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

    def _parse_repo(self) -> dict[str, str]:
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

    def _convert_steps_to_schema_format(self, steps: list[dict]) -> list[dict]:
        """Convert our parsed step format to schema-compliant format."""
        schema_steps = []
        for step in steps:
            # Map our fields to schema fields
            # Use parsed role if available, otherwise default to coding_agent
            role = step.get("role") or "coding_agent"

            # Schema often enforces a minimum length; legacy specs may have very short titles.
            title = (step.get("title") or "").strip()
            prompts = step.get("prompts") or []
            prompt_text = "\n".join(prompts).strip() if isinstance(prompts, list) else ""
            prompt_summary = ""
            if prompt_text:
                m = re.match(r"^(.+?[.!?])(\s+|$)", " ".join(prompt_text.split()))
                prompt_summary = (m.group(1) if m else " ".join(prompt_text.split())).strip()

            description = title
            if len(description) < 10:
                if prompt_summary:
                    description = f"{title}: {prompt_summary}" if title else prompt_summary
                else:
                    description = f"Step {step['index']}: {title}" if title else f"Step {step['index']}"

            schema_step = {
                "step_id": f"step-{step['index']:03d}",
                "role": role,
                "kind": "code",  # Default kind
                "description": description,
            }

            # Add optional fields if present
            if step.get("prompts"):
                schema_step["prompt"] = "\n".join(step["prompts"])

            if step.get("outputs"):
                schema_step["outputs"] = step["outputs"]

            if step.get("commands"):
                # Commands aren't in the schema, so we'll add them as a prompt note
                pass

            # Add gate review if present
            if step.get("gate_review"):
                schema_step["gate_review"] = step["gate_review"]

            # Add gate_ref if present
            if step.get("gate_ref"):
                schema_step["gate_ref"] = step["gate_ref"]

            # Add executor fields if present (for agentic steps)
            if step.get("allowed_paths"):
                schema_step["allowed_paths"] = step["allowed_paths"]

            if step.get("forbidden_paths"):
                schema_step["forbidden_paths"] = step["forbidden_paths"]

            if step.get("verification_commands"):
                schema_step["verification_commands"] = step["verification_commands"]

            schema_steps.append(schema_step)

        return schema_steps

    def _build_aip(self) -> dict[str, Any]:
        """Build final AIP structure matching the schema."""
        from datetime import datetime

        # Parse context (use normalized keys)
        context_text = self.sections.get("context", "")
        background = re.search(r'### Background\s+(.+?)(?=###|$)', context_text, re.DOTALL)
        constraints_match = re.search(r'### Constraints\s+(.+?)(?=###|$)', context_text, re.DOTALL)

        # Parse constraints as list (extract bullet points)
        constraints = []
        if constraints_match:
            constraint_text = constraints_match.group(1).strip()
            # Extract list items (lines starting with -)
            for line in constraint_text.split('\n'):
                line = line.strip()
                if line.startswith('-') or line.startswith('*'):
                    constraints.append(line.lstrip('-* ').strip())

        # Parse acceptance criteria
        acceptance_criteria = [c["text"] for c in self._parse_acceptance_criteria()]
        if not acceptance_criteria:
            goal = (self.frontmatter.get("goal") or "").strip()
            acceptance_criteria = [goal] if goal else ["Meets the spec goal"]

        # Get repo info from frontmatter or defaults
        import subprocess
        try:
            repo_url = subprocess.check_output(
                ['git', 'config', '--get', 'remote.origin.url'],
                stderr=subprocess.DEVNULL,
                text=True
            ).strip()
        except (subprocess.CalledProcessError, FileNotFoundError):
            repo_url = "git@github.com:org/repo.git"

        # Get project slug from frontmatter or derive from repo
        project_slug = self.frontmatter.get("project_slug")
        if not project_slug:
            # Derive from repo URL if available
            if "github.com" in repo_url:
                # Extract repo name from URL like git@github.com:user/repo.git
                project_slug = repo_url.split("/")[-1].replace(".git", "")
            else:
                # Fallback to generic slug
                project_slug = "project"
            project_slug = project_slug.lower()

        # Generate AIP ID from frontmatter or create one
        aip_id = self.frontmatter.get("aip_id")
        if not aip_id:
            from datetime import date
            today = date.today()
            aip_id = f"AIP-{project_slug}-{today.year}-{today.month:02d}-{today.day:02d}-001"

        # Parse orchestrator_contract from frontmatter or use default
        orchestrator = self.frontmatter.get("orchestrator_contract", "standard")

        # Handle various forms of orchestrator_contract
        if orchestrator == "standard" or (isinstance(orchestrator, dict) and orchestrator.get("name") == "standard"):
            # Expand "standard" shorthand or partial object into full contract
            orchestrator_contract = {
                "state_machine": {
                    "states": ["pending", "running", "awaiting_human", "failed", "succeeded", "rolled_back"],
                    "events": ["run_step", "await_gate", "approve", "reject", "retry", "escalate", "complete"]
                },
                "artifacts_dir": f".aip_artifacts/{aip_id}",
                "logging": "jsonl"
            }
            # If orchestrator was a dict, merge in any additional fields
            if isinstance(orchestrator, dict):
                orchestrator_contract.update({k: v for k, v in orchestrator.items() if k != "name"})
        else:
            orchestrator_contract = orchestrator  # Assume it's already a complete object

        # Helper to ensure datetime values are ISO strings
        def to_iso_string(value):
            if isinstance(value, datetime):
                return value.isoformat()
            elif isinstance(value, str):
                return value
            else:
                return datetime.now().astimezone().isoformat()

        created = to_iso_string(self.frontmatter.get("created"))
        updated = to_iso_string(self.frontmatter.get("updated"))

        aip = {
            # Required top-level fields
            "version": self.frontmatter.get("version", "0.1"),
            "aip_id": aip_id,
            "project_slug": project_slug,
            "spec_version": self.frontmatter.get("spec_version", "1.0.0"),
            "created": created,
            "updated": updated,
            "title": self.frontmatter["title"],
            "tier": self.frontmatter["tier"],

            # Meta (required: created_by, created_at)
            "meta": {
                "created_by": self.frontmatter.get("owner"),
                "created_at": created
            },

            # Repo (required: url, default_branch, working_branch)
            "repo": {
                "url": self.frontmatter.get("repo", {}).get("url", repo_url),
                "default_branch": self.frontmatter.get("repo", {}).get("default_branch", "main"),
                "working_branch": self.frontmatter.get("repo", {}).get("working_branch", f"feat/{self.frontmatter['title'].lower().replace(' ', '-')}")
            },

            # Objective (required: goal, acceptance_criteria)
            "objective": {
                "goal": self.frontmatter.get("goal", ""),
                "acceptance_criteria": acceptance_criteria
            },

            # Context (optional)
            "context": {
                "background": background.group(1).strip() if background else "",
                "constraints": constraints
            },

            # Plan (array of steps, not {steps: [...]}  - convert our parsed steps)
            "plan": self._convert_steps_to_schema_format(self.plan_steps),

            # Orchestrator contract (required)
            "orchestrator_contract": orchestrator_contract
        }

        return aip
