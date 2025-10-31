# Pre-Commit Checklist for Specwright v0.3.0

## Files Updated ✅

- [x] `README.md` - Rebranded to Specwright, added ecosystem
- [x] `CONTRIBUTING.md` - Complete contributor guide
- [x] `CHANGELOG.md` - v0.3.0 release notes
- [x] `LICENSE` - MIT (already correct)
- [x] `VERSION` - Updated to 0.3.0
- [x] `pyproject.toml` - Renamed to `specwright`, updated metadata
- [x] `.gitignore` - Comprehensive ignore rules
- [x] `Makefile` - Full build/test/publish targets
- [x] `MANIFEST.in` - Include all necessary files
- [x] `.github/workflows/test.yml` - CI testing
- [x] `.github/workflows/publish.yml` - PyPI publishing
- [x] `PYPI.md` - Publishing guide
- [x] `config/templates/specs/tier-a-template.md` - Jinja2 template
- [x] `config/templates/specs/tier-b-template.md` - Jinja2 template
- [x] `config/templates/specs/tier-c-template.md` - Jinja2 template
- [x] `src/spec/compiler/` - Parser and compiler modules
- [x] `src/spec/core/loader.py` - YAML loading utilities
- [x] `src/spec/cli/spec.py` - Updated with compile command

## Files Cleaned ✅

- [x] `.pytest_cache/` - Removed
- [x] `.aip_artifacts/` - Removed
- [x] `.venv/` - Removed
- [x] `.env` - Removed

## Still TODO Before Commit

### Code Quality
- [ ] Run linter: `make lint` or `ruff check src/ tests/`
- [ ] Run type check: `make typecheck` or `mypy src/`
- [ ] Fix any errors from above

### Testing
- [ ] Create basic tests (optional for v0.3.0):
  - `tests/test_parser.py` - Frontmatter parsing
  - `tests/test_compiler.py` - MD→YAML compilation
  - `tests/test_cli.py` - CLI command tests
- [ ] Run tests: `make test` (if created)

### Git Setup
- [ ] Ensure git is initialized: `git status`
- [ ] Check remote: `git remote -v`
- [ ] Update remote if needed:
  ```bash
  git remote set-url origin https://github.com/bfarmstrong/specwright.git
  ```

### Final Verification
- [ ] Install locally: `make dev`
- [ ] Test CLI:
  ```bash
  spec new --tier C --title "Test" --owner ben --goal "Test install"
  spec compile specs/test.md
  spec validate specs/test.compiled.yaml
  ```
- [ ] Verify all commands work

## Commit Commands

```bash
# Stage all changes
git add .

# Commit with descriptive message
git commit -m "v0.3.0: Rebrand to Specwright, add Markdown compilation

- Complete rebrand to Specwright for clarity and ecosystem positioning
- Added Markdown-first authoring with Jinja2 templates
- Implemented deterministic MD→YAML compiler with validation
- Added 5-gate governance model (G0-G4) for all tiers
- Created tier-specific templates (A/B/C)
- Updated all documentation and contribution guides
- Added GitHub Actions for CI/CD
- Prepared for PyPI publishing

Part of the Specwright/Dogfold/Gorch/LifeOS ecosystem."

# Tag the release
git tag -a v0.3.0 -m "Specwright v0.3.0 - The architect of agentic workflows"

# Push to remote
git push origin main --tags
```

## Post-Commit

### Create GitHub Release
1. Go to https://github.com/bfarmstrong/specwright/releases/new
2. Choose tag: `v0.3.0`
3. Title: `Specwright v0.3.0 - The Architect of Agentic Workflows`
4. Description: Copy from `CHANGELOG.md` v0.3.0 section
5. Click "Publish release"

### Publish to PyPI
Follow steps in `PYPI.md`:
1. Get PyPI API token
2. Add to GitHub secrets
3. GitHub Actions will auto-publish on release

### Claim Additional Namespaces
- [ ] Reserve `dogfold` on PyPI
- [ ] Reserve `gorch` on PyPI
- [ ] Reserve `lifeos` on PyPI (optional)

## Notes

- Source directory is still `src/spec/` (rename to `src/specwright/` in v0.4.0)
- CLI command is still `spec` (no breaking changes)
- Package name on PyPI will be `specwright`
- Import path will change in v0.4.0: `from specwright.compiler import ...`
