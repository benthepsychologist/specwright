# Contributing to Specwright

Thanks for your interest in contributing to Specwright! This guide will help you get started.

---

## 🚀 Quick Start

### 1. Clone and Install

```bash
git clone https://github.com/yourusername/spec-core.git
cd spec-core
pip install -e ".[dev]"
```

### 2. Verify Installation

```bash
spec --help
spec new --tier C --title "Test" --owner you --goal "Verify setup"
spec compile specs/test.md
```

### 3. Run Tests

```bash
# All tests
pytest tests/

# Just compiler tests
pytest tests/compiler/ -v

# Golden tests (snapshot-based)
pytest tests/compiler/golden/ -v

# Linter
ruff check src/ tests/

# Type checking
mypy src/
```

---

## 🏗️ Development Workflow

### Setting Up Pre-commit Hooks

**Enforce Markdown/YAML sync:**

```bash
# Install hook
cat > .git/hooks/pre-commit << 'EOF'
#!/bin/bash
set -e

# Check for changed .md files with existing .compiled.yaml
for md in specs/*.md; do
    yaml="${md%.md}.compiled.yaml"
    if [ -f "$yaml" ] && git diff --cached --name-only | grep -q "$md"; then
        echo "Checking: $md"
        spec diff "$md" || {
            echo "ERROR: $md changed but compiled YAML differs"
            echo "Run: spec compile $md"
            exit 1
        }
    fi
done

# Run linter on staged Python files
git diff --cached --name-only --diff-filter=ACM | grep '\.py$' | xargs -r ruff check || exit 1

echo "✓ Pre-commit checks passed"
EOF

chmod +x .git/hooks/pre-commit
```

### Making Changes

**For CLI commands:**
1. Edit `src/spec/cli/spec.py`
2. Follow existing command patterns
3. Add help text and examples
4. Test interactively: `spec <your-command>`

**For compiler changes:**
1. Edit `src/spec/compiler/parser.py` or `compiler.py`
2. **Must update golden tests** if output format changes
3. Run: `pytest tests/compiler/golden/ -v --snapshot-update` (first time)
4. Verify diffs carefully before committing

**For templates:**
1. Edit `config/templates/specs/tier-{a,b,c}-template.md`
2. Use Jinja2 syntax: `{{ variable }}`
3. Test with: `spec new --tier <X> --title "Test" --owner you --goal "Test"`
4. Compile and validate: `spec compile specs/test.md`

---

## 🧪 Testing Requirements

### All Pull Requests Must:

1. **Pass linter**: `ruff check src/ tests/`
2. **Pass type checking**: `mypy src/`
3. **Pass all tests**: `pytest tests/`
4. **Update golden tests** if compiler output changes
5. **Add tests** for new features

### Writing Tests

**Unit tests:**
```python
# tests/test_parser.py
def test_parse_frontmatter():
    content = """---
tier: B
title: Test
owner: alice
goal: Test goal
---
"""
    parser = SpecParser(content)
    parser._parse_frontmatter()
    assert parser.frontmatter["tier"] == "B"
```

**Golden tests** (snapshot-based):
```python
# tests/compiler/golden/test_snapshots.py
def test_tier_b_compilation(snapshot):
    md_path = Path("config/templates/specs/tier-b-template.md")
    # ... render with test vars ...
    compiled = compile_spec(...)
    snapshot.assert_match(compiled.read_text(), "tier-b.yaml")
```

### Updating Golden Tests

When compiler output format changes:

```bash
# Review what changed
pytest tests/compiler/golden/ -v

# If changes are intentional, update snapshots
pytest tests/compiler/golden/ -v --snapshot-update

# Review diffs carefully
git diff tests/compiler/golden/snapshots/

# Commit updated snapshots
git add tests/compiler/golden/snapshots/
git commit -m "Update golden snapshots for compiler changes"
```

---

## 📝 Code Style

### Python

- **Follow PEP 8** (enforced by ruff)
- **Use type hints** for function signatures
- **Docstrings**: Google style for public APIs
- **Line length**: 100 characters max

**Example:**
```python
def compile_spec(
    spec_path: Path,
    output_path: Optional[Path] = None,
    overwrite: bool = False
) -> Path:
    """
    Compile a Markdown spec to YAML AIP.
    
    Args:
        spec_path: Path to .md spec file
        output_path: Output path (defaults to .compiled.yaml)
        overwrite: Allow overwriting existing file
    
    Returns:
        Path to compiled YAML file
    
    Raises:
        ValueError: If compilation fails
    """
    ...
```

### Markdown Templates

- Use **Jinja2 syntax** for variables: `{{ variable }}`
- Keep **section structure canonical**: Objective, Context, Plan, etc.
- **Document all steps** with Gate references: `[G0: Plan Approval]`
- Use **fenced code blocks** with language: ` ```bash `

### YAML

- **2-space indentation**
- **Alphabetically sorted keys** (handled by compiler)
- **No anchors/aliases** (handled by compiler)
- **Use `null` not empty strings** for optional fields

---

## 🎯 Contribution Areas

### High-Impact

1. **Improve compiler robustness**
   - Better error messages
   - Handle edge cases (nested code blocks, special characters)
   - Performance optimization

2. **Add builder adapters**
   - Forge (Python) - `src/spec/builders/forge.py`
   - Next.js - `src/spec/builders/nextjs.py`
   - Generic shell - `src/spec/builders/shell.py`

3. **Automated gate approvals**
   - Slack integration
   - Email notifications
   - GitHub PR comments

4. **Metrics tracking**
   - Budget consumption (tokens, API calls)
   - Coverage tracking
   - Time-to-green metrics

### Documentation

1. **Tutorial videos**
2. **Blog post: "Tier A feature walkthrough"**
3. **Comparison guide: Tier A vs B vs C**
4. **Migration guide: YAML → Markdown workflow**

### Testing

1. **Fuzz testing for parser**
2. **Integration tests with real repos**
3. **Performance benchmarks**

---

## 🐛 Reporting Issues

### Before Opening an Issue

1. Search existing issues
2. Try latest version: `pip install -U -e .`
3. Check docs: README.md, docs/

### Good Issue Template

**For bugs:**
```
**Describe the bug**
A clear description of what went wrong.

**To Reproduce**
Steps to reproduce:
1. Run `spec compile specs/example.md`
2. See error: ...

**Expected behavior**
What should have happened.

**Environment**
- OS: [e.g., Ubuntu 22.04]
- Python version: [e.g., 3.12.0]
- spec-core version: [e.g., 0.3.0]

**Additional context**
Paste error output, relevant file contents.
```

**For features:**
```
**Feature description**
What problem does this solve?

**Proposed solution**
How should it work?

**Alternatives considered**
Other approaches you've thought about.
```

---

## 📋 Pull Request Process

### Before Submitting

1. **Create feature branch**: `git checkout -b feature/amazing-feature`
2. **Make atomic commits**: One logical change per commit
3. **Write good commit messages**:
   ```
   Add support for custom gate approvers
   
   - Parse approver_role from gate config
   - Add CLI flag: --approver
   - Update tier-b template
   
   Fixes #42
   ```
4. **Update documentation** if needed
5. **Add tests** for new functionality
6. **Run full test suite**: `pytest tests/`
7. **Run linter**: `ruff check src/ tests/`

### PR Template

```markdown
## Description
Brief description of changes.

## Type of Change
- [ ] Bug fix (non-breaking change)
- [ ] New feature (non-breaking change)
- [ ] Breaking change (fix or feature that changes existing behavior)
- [ ] Documentation update

## Testing
- [ ] All tests pass
- [ ] Added new tests for changes
- [ ] Updated golden snapshots (if applicable)
- [ ] Manually tested with real spec

## Checklist
- [ ] Code follows style guidelines
- [ ] Self-reviewed code
- [ ] Commented hard-to-understand areas
- [ ] Updated documentation
- [ ] No new warnings from linter/mypy
- [ ] Tested on Python 3.12+
```

### Review Process

1. Maintainer reviews within 48 hours
2. Address feedback with new commits
3. Once approved, squash-merge to main
4. Delete feature branch

---

## 🏷️ Versioning

We use **Semantic Versioning** (SemVer):

- **MAJOR**: Breaking changes (e.g., 1.0.0 → 2.0.0)
- **MINOR**: New features, backward compatible (e.g., 0.3.0 → 0.4.0)
- **PATCH**: Bug fixes (e.g., 0.3.0 → 0.3.1)

---

## 🚢 Release Process

### For Maintainers

Releases are automated via GitHub Actions. When a GitHub release is created, the package is automatically built and published to PyPI.

**Steps to release a new version:**

1. **Update version numbers:**
   ```bash
   # Edit version in two places:
   # - pyproject.toml (line 7)
   # - src/spec/__init__.py (line 3)

   # Example: bumping from 0.3.0 to 0.3.1
   ```

2. **Commit and push to main:**
   ```bash
   git add pyproject.toml src/spec/__init__.py
   git commit -m "Bump version to 0.3.1"
   git push origin main
   ```

3. **Create and push git tag:**
   ```bash
   git tag v0.3.1
   git push origin v0.3.1
   ```

4. **Create GitHub release (triggers automatic PyPI publish):**
   ```bash
   gh release create v0.3.1 \
     --title "Specwright v0.3.1" \
     --notes "## What's New
   - Bug fixes and improvements
   - Updated documentation

   ## Installation
   \`\`\`bash
   pip install specwright
   \`\`\`
   "
   ```

5. **GitHub Actions will automatically:**
   - Build the source distribution (`.tar.gz`) and wheel (`.whl`)
   - Upload to PyPI using the `PYPI_API_TOKEN` secret
   - Package will be live at https://pypi.org/project/specwright/

6. **Verify the release:**
   ```bash
   # Check PyPI
   pip install --upgrade specwright
   spec --version  # Should show new version

   # Check GitHub Actions
   gh run list --limit 1
   ```

### Release Checklist

Before creating a release, ensure:

- [ ] All tests pass on `main` branch
- [ ] CHANGELOG.md is updated with release notes
- [ ] Version bumped in `pyproject.toml` and `src/spec/__init__.py`
- [ ] Documentation is up to date
- [ ] No open critical bugs or security issues

### Troubleshooting Releases

**If GitHub Action fails:**
- Check the workflow run: `gh run view <run-id> --log-failed`
- Verify `PYPI_API_TOKEN` secret is set correctly in repo settings
- Ensure version number doesn't already exist on PyPI

**If you need to re-release:**
- You cannot re-upload the same version to PyPI
- Bump the patch version (e.g., 0.3.1 → 0.3.2) and try again

---

## 📜 License

By contributing, you agree that your contributions will be licensed under the [MIT License](LICENSE).

---

## 💬 Questions?

- **Discussions**: [GitHub Discussions](https://github.com/yourusername/spec-core/discussions)
- **Email**: bfarmstrong@example.com
- **Issues**: [GitHub Issues](https://github.com/yourusername/spec-core/issues)

---

**Thank you for contributing to spec-core!** 🚀
