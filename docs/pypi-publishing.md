# PyPI Publishing Guide

## First-Time Setup

### 1. Create PyPI Account

1. Go to [https://pypi.org/account/register/](https://pypi.org/account/register/)
2. Create account
3. Verify email

### 2. Create API Token

1. Go to [https://pypi.org/manage/account/token/](https://pypi.org/manage/account/token/)
2. Create a new API token for "Entire account" (first time) or "specwright" (after first upload)
3. Copy the token (starts with `pypi-`)
4. **Save it securely** - you won't see it again!

### 3. Configure Credentials

**Option A: Using GitHub Actions (Recommended)**

1. Go to your GitHub repo: Settings → Secrets and variables → Actions
2. Add new repository secret:
   - Name: `PYPI_API_TOKEN`
   - Value: Your PyPI token

**Option B: Local Publishing**

Create `~/.pypirc`:

```ini
[pypi]
username = __token__
password = pypi-YOUR-TOKEN-HERE
```

## Publishing to PyPI

### Via GitHub (Recommended)

1. **Create a release**:
   ```bash
   git tag v0.3.0
   git push origin v0.3.0
   ```

2. **Create GitHub Release**:
   - Go to GitHub → Releases → "Draft a new release"
   - Choose tag: `v0.3.0`
   - Title: `Specwright v0.3.0`
   - Description: Copy from CHANGELOG.md
   - Click "Publish release"

3. **GitHub Actions will automatically**:
   - Build the package
   - Run tests
   - Publish to PyPI

### Manually (Local)

```bash
# 1. Install build tools
pip install build twine

# 2. Clean and build
make clean
make build

# 3. Check the distribution
twine check dist/*

# 4. Test upload to TestPyPI (optional)
twine upload --repository testpypi dist/*

# 5. Upload to PyPI
make publish
# or: twine upload dist/*
```

## Claiming PyPI Namespaces

We want to claim:
- ✅ `specwright` - Main package
- ✅ `specwright` - Main package (v0.3.0)
- 🎯 `dogfold` - Future: Recursive scaffolding
- 🎯 `gorch` - Future: Google orchestration

### Check Availability

```bash
pip search specwright
pip search dogfold
pip search gorch
```

Or check: [https://pypi.org/project/specwright/](https://pypi.org/project/specwright/)

### Claim Strategy

1. **Publish `specwright` immediately** (v0.3.0)
2. **Create placeholder packages** for `dogfold` and `gorch`:

```python
# dogfold/setup.py
from setuptools import setup

setup(
    name="dogfold",
    version="0.0.1",
    description="Recursive scaffolding for Specwright ecosystem - Coming Soon",
    author="Benjamin Armstrong",
    author_email="bfarmstrong@example.com",
    url="https://github.com/bfarmstrong/dogfold",
    py_modules=[],
    classifiers=[
        "Development Status :: 1 - Planning",
    ],
)
```

Upload placeholders to claim names:
```bash
cd dogfold-placeholder && python -m build && twine upload dist/*
cd gorch-placeholder && python -m build && twine upload dist/*
```

## Post-Publication Checklist

- [ ] Verify package appears on PyPI: [https://pypi.org/project/specwright/](https://pypi.org/project/specwright/)
- [ ] Test installation: `pip install specwright`
- [ ] Test CLI: `spec --help`
- [ ] Update README badges (if any)
- [ ] Announce on social media / blog
- [ ] Update documentation site

## Version Bumping

For next release:

1. Update `VERSION` file
2. Update `pyproject.toml` version
3. Add entry to `CHANGELOG.md`
4. Commit: `git commit -am "Bump version to 0.4.0"`
5. Tag: `git tag v0.4.0`
6. Push: `git push origin main --tags`
7. Create GitHub Release

## Troubleshooting

### "Package already exists"
- You can't overwrite an existing version
- Bump the version number and try again

### "Invalid distribution"
- Run `twine check dist/*` to see what's wrong
- Common issues: missing README, invalid metadata

### "Authentication failed"
- Check your API token is correct
- Make sure token has upload permissions
- Try creating a project-specific token after first upload

### "File already exists"
- Delete old builds: `make clean`
- Rebuild: `make build`

## Resources

- [PyPI Help](https://pypi.org/help/)
- [Python Packaging Guide](https://packaging.python.org/)
- [Twine Documentation](https://twine.readthedocs.io/)
