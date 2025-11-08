# Development Workflow

This guide explains how to develop Specwright while simultaneously using it to build another project (dogfooding).

## 🔄 Dual-Repo Development Setup

This workflow is ideal when you want to:
- Build a tool (Specwright) while using it in a real project
- Rapidly iterate on features as you discover needs
- Test changes immediately without reinstalling

### Directory Structure

```
/home/user/
├── specwright/          # Tool development (this repo)
│   ├── src/spec/       # Source code
│   ├── .venv/          # Specwright's virtual environment
│   └── ...
└── your-project/       # Your application using Specwright
    ├── .venv/          # Project's virtual environment
    └── ...
```

---

## 🚀 Initial Setup

### 1. Set Up Specwright (One Time)

```bash
cd /home/user/specwright
python -m venv .venv
source .venv/bin/activate

# Install uv (if not already installed)
pip install uv

# Install Specwright with dev dependencies
uv pip install -e ".[dev]"

# Verify installation
spec --help
```

### 2. Set Up Your Project (One Time)

```bash
cd /home/user/your-project
python -m venv .venv
source .venv/bin/activate

# Install uv (if not already installed)
pip install uv

# Install Specwright in EDITABLE mode from local path
uv pip install -e /home/user/specwright

# Verify it works
spec --help
spec create --tier C --title "Test Setup"
```

**Key Point:** The `-e` flag installs Specwright in "editable" mode. Any changes you make to Specwright's code are **immediately available** in your project without reinstalling.

---

## 💻 Daily Workflow

### Typical Development Session

**Terminal 1: Your Project**
```bash
cd /home/user/your-project
source .venv/bin/activate

# Use Specwright normally
spec create --tier B --title "New Feature" --owner alice --goal "Build new feature"
# Edit specs/new-feature.md
spec compile specs/new-feature.md
spec validate aips/new-feature.yaml
spec run aips/new-feature.yaml

# Discover a missing feature or bug?
# → Switch to Terminal 2
```

**Terminal 2: Specwright Development**
```bash
cd /home/user/specwright
source .venv/bin/activate

# Edit source code
# Example: Add new CLI command in src/spec/cli/spec.py
# Example: Fix parser bug in src/spec/compiler/parser.py

# Changes are IMMEDIATELY available in Terminal 1!
```

**Back to Terminal 1: Test Changes**
```bash
# Your new command/fix is already available
spec <new-command>  # Works instantly!
```

---

## 📝 Making Changes to Specwright

### Workflow Loop

1. **Identify Need** (in your project)
   - Using Specwright, you notice a missing feature
   - Or encounter a bug
   - Or see an improvement opportunity

2. **Switch to Specwright** (Terminal 2)
   ```bash
   cd /home/user/specwright
   git checkout -b feature/your-feature-name  # Optional: feature branch

   # Edit code
   # src/spec/cli/spec.py        - CLI commands
   # src/spec/compiler/parser.py  - Markdown parser
   # src/spec/compiler/compiler.py - YAML compiler
   # src/spec/core/loader.py      - Configuration loading
   ```

3. **Test Immediately** (Terminal 1)
   ```bash
   cd /home/user/your-project
   spec <test-your-changes>
   ```

4. **Iterate** (repeat 2-3 until working)

5. **Commit Changes** (Terminal 2)
   ```bash
   cd /home/user/specwright
   git add .
   git commit -m "Add feature X based on real-world usage"
   git push origin main  # Or feature branch
   ```

---

## 🧪 Testing Your Changes

### Quick Local Testing

```bash
cd /home/user/specwright
source .venv/bin/activate

# Run linter
ruff check src/ tests/

# Run type checker
mypy src/

# Run tests (when they exist)
pytest tests/ -v
```

### Testing in Your Project

```bash
cd /home/user/your-project
source .venv/bin/activate

# Test real-world usage
spec create --tier B --title "Test Feature"
spec validate aips/*.yaml
spec run aips/test.yaml --dry-run
```

---

## 📦 Version Management

### During Active Development

**Don't bump version** for every change. Keep it at the current dev version (e.g., `0.3.0`) while iterating.

```bash
# pyproject.toml stays at: version = "0.3.0"
# src/spec/__init__.py stays at: __version__ = "0.3.0"
```

Your project uses the live code via editable install, so version number doesn't matter during development.

### When Ready for a Release

After several iterations and stable features:

1. **Bump version number:**
   ```bash
   # Edit pyproject.toml (line 7): version = "0.4.0"
   # Edit src/spec/__init__.py (line 3): __version__ = "0.4.0"
   ```

2. **Update CHANGELOG.md:**
   ```markdown
   ## [0.4.0] - 2025-11-07

   ### Added
   - New feature X based on real-world usage
   - Enhanced parser to handle Y

   ### Fixed
   - Bug Z discovered during event-bus development
   ```

3. **Commit, tag, and release:**
   ```bash
   git add pyproject.toml src/spec/__init__.py CHANGELOG.md
   git commit -m "Bump version to 0.4.0"
   git push origin main

   git tag v0.4.0
   git push origin v0.4.0

   gh release create v0.4.0 \
     --title "Specwright v0.4.0" \
     --notes "See CHANGELOG.md for details"
   ```

4. **GitHub Actions automatically publishes to PyPI**

---

## 🎯 Best Practices

### 1. Use Feature Branches for Experiments

```bash
cd /home/user/specwright
git checkout -b experiment/new-feature

# Try experimental changes
# If it works → merge to main
# If it doesn't → delete branch
```

### 2. Track TODOs as You Go

```bash
# When you spot something to improve later
echo "- Add --dry-run flag to spec run" >> TODO.md
echo "- Improve error messages in parser" >> TODO.md
```

### 3. Keep a Dev Log

```bash
# Document your discoveries
echo "## 2025-11-07" >> DEVLOG.md
echo "- Discovered need for custom output paths" >> DEVLOG.md
echo "- Added --output flag to spec create" >> DEVLOG.md
```

### 4. Commit Often, Release Rarely

```bash
# Commit after each logical change
git commit -m "Add --output flag to spec create"
git commit -m "Fix parser bug with nested lists"
git commit -m "Improve error messages"

# But only release when you reach a milestone
git tag v0.4.0  # After 10-20 commits
```

---

## 🔧 Troubleshooting

### Changes Not Showing Up?

**Problem:** Made changes to Specwright but they're not reflected in your project.

**Solution:** Verify editable install:
```bash
cd /home/user/your-project
source .venv/bin/activate
uv pip show specwright | grep Location
# Should show: /home/user/specwright/src
```

If not, reinstall in editable mode:
```bash
uv pip uninstall specwright
uv pip install -e /home/user/specwright
```

### Import Errors

**Problem:** `ModuleNotFoundError: No module named 'spec'`

**Solution:** The package structure changed. Reinstall:
```bash
cd /home/user/your-project
source .venv/bin/activate
uv pip install -e /home/user/specwright --force-reinstall
```

### Want to Test PyPI Version vs Local?

**Switch to PyPI version:**
```bash
cd /home/user/your-project
uv pip uninstall specwright
uv pip install specwright  # From PyPI
```

**Switch back to local dev:**
```bash
uv pip uninstall specwright
uv pip install -e /home/user/specwright
```

---

## 📊 Example Session

```bash
# Morning: Start working on your project
$ cd /home/user/my-app
$ source .venv/bin/activate

$ spec create --tier B --title "User Authentication"
# Wait... I need this to go to a custom directory

# Switch to Specwright terminal
$ cd /home/user/specwright
$ source .venv/bin/activate
$ code src/spec/cli/spec.py  # Add --output flag

# Back to project terminal - already works!
$ spec create --tier B --title "User Auth" --output custom/dir
✓ Created: custom/dir/user-auth.md

# Continue building... discover another need
$ spec validate custom/dir/user-auth.md
# Hmm, validator is too strict about whitespace

# Back to Specwright, fix the parser...
# Test immediately in project...
# Iterate...

# End of day: commit improvements
$ cd /home/user/specwright
$ git add .
$ git commit -m "Add --output flag and relax whitespace validation"
$ git push origin main

# Don't release yet - will accumulate more changes tomorrow
```

---

## 🚦 When to Release

Release to PyPI when you reach **stable checkpoints**:

✅ **Good times to release:**
- Completed a cohesive set of features
- Fixed critical bugs
- Reached a version milestone (0.4.0, 0.5.0, 1.0.0)
- After successful dogfooding for a week

❌ **Don't release after:**
- Every single commit
- Experimental features (use feature branches)
- Untested changes

---

## 🎓 Summary

This workflow enables:
- **Rapid iteration:** Change → Test → Repeat in seconds
- **Real-world testing:** Use Specwright in actual projects
- **Organic feature development:** Build what you actually need
- **Quality improvements:** Catch edge cases during real use

The key is **editable install** (`uv pip install -e`), which makes your local Specwright source code the live version used in your project.

Happy building! 🚀
