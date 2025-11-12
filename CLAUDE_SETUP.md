# Claude Code Integration Setup

## Quick Start

When setting up Specwright in a new project, the slash commands will be automatically installed:

```bash
cd /path/to/your/project
spec init
```

This will:
- Create `.specwright.yaml` config
- Create `.specwright/GUIDE.md` documentation
- **Install Claude Code slash commands to `.claude/commands/`**

You'll see:
```
✓ Installed 5 Claude Code slash commands to .claude/commands/
  Use /spec-run, /spec-status, /spec-next, /spec-pause in Claude Code
✓ Created .specwright.yaml
```

## Manual Installation (if needed)

If you already have a `.specwright.yaml` and just want to add the Claude commands:

```bash
# Force reinstall with Claude commands
spec init --force

# Or skip Claude commands if you don't want them
spec init --no-claude
```

## Editable Mode Installation

If you installed Specwright in editable mode (`-e` flag):

```bash
# In your specwright development directory
cd /path/to/specwright

# In your other project
cd /path/to/your/project
pip install -e /path/to/specwright

# Then initialize (this will copy commands from specwright repo)
spec init
```

The `spec init` command will automatically find the `.claude/commands/` directory in the specwright repo and copy the slash commands to your project.

## Available Slash Commands

Once installed, you can use these commands in Claude Code:

### `/spec-status`
Shows current AIP progress, including:
- AIP ID, title, tier, goal
- All steps with completion status
- Gate approval status
- Acceptance criteria checklist

### `/spec-run`
Executes the current AIP step-by-step:
- Loads AIP from `.specwright.yaml`
- Displays each step with prompts and commands
- Asks for permission before executing
- Logs execution to audit trail
- Triggers gate reviews

### `/spec-next`
Resumes execution from the last completed step:
- Finds the next incomplete step
- Continues the workflow
- Useful after `/spec-pause`

### `/spec-pause`
Checkpoints current progress:
- Logs pause event
- Shows execution summary
- Provides resume instructions

## Directory Structure

After `spec init`, your project will have:

```
your-project/
├── .specwright.yaml          # Config file
├── .specwright/
│   └── GUIDE.md             # Spec writing guide
├── .claude/
│   └── commands/            # Claude Code slash commands ⭐
│       ├── README.md
│       ├── spec-run.md
│       ├── spec-status.md
│       ├── spec-next.md
│       └── spec-pause.md
├── specs/                   # Your Markdown specs (created when needed)
├── aips/                    # Compiled YAML AIPs (created when needed)
└── .aip_artifacts/         # Execution logs (created when running)
```

## Troubleshooting

### Commands don't show up in Claude Code

1. Check that `.claude/commands/` exists with the files:
   ```bash
   ls -la .claude/commands/
   ```

2. Restart Claude Code (sometimes needed to pick up new commands)

3. Check file permissions:
   ```bash
   chmod 644 .claude/commands/*.md
   ```

### Manual installation if `spec init` fails

If automatic installation doesn't work, manually copy the commands:

```bash
# From specwright repo
mkdir -p .claude/commands
cp /path/to/specwright/.claude/commands/*.md .claude/commands/
```

Or clone from GitHub:
```bash
git clone --depth 1 https://github.com/benthepsychologist/specwright.git /tmp/specwright
cp -r /tmp/specwright/.claude/commands .claude/
rm -rf /tmp/specwright
```

## Updating Commands

To get the latest version of the slash commands:

```bash
# Re-run init with force
spec init --force
```

This will update both your config and the Claude commands.

## See Also

- [INTEGRATION.md](INTEGRATION.md) - Complete integration workflow guide
- [README.md](README.md) - Specwright overview and CLI commands
- `.specwright/GUIDE.md` - How to write effective specs (created after init)
