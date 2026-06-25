# Epic context convention — AGENTS.md pointer + CLAUDE.md stub

Every epic carries a small, human-authored **`AGENTS.md` pointer** plus a
one-line **`CLAUDE.md` stub**. At run, `agent.sync_refs` materializes both into
the target repo and copies the skills `AGENTS.md` names into `.claude/skills/`
for native discovery. This is the cheap, colocated alternative to a governed
skill-selection object: selection is a human decision expressed as a pointer
file, not an auto-matcher.

## Where the pointer is authored

specwright does **not** create epics or their context files — it runs and
validates specs, it does not author them (see t013-02). Every epic is authored on
the **cloud-governor** side and carries two hand-authored files:

```
epics/<series>/<epic>/
  AGENTS.md   # the canonical pointer (hand-authored)
  CLAUDE.md   # one-line stub -> AGENTS.md
```

See the authoring catalog + template in the cloud-governor `skills/README.md`.
specwright only **consumes** these at run via `agent.sync_refs` (below).

## AGENTS.md is a pointer, not a context dump

`AGENTS.md` is short. It has exactly two sections:

```markdown
# <Epic Title> — Agent Context

This is a pointer (not a context dump): it names the skills that apply and links
the relevant docs.

## Skills

Shared-library skills copied into `.claude/skills/` at run for native discovery:

- spec-and-epic-authoring
- data-architecture

## Docs

Relevant docs, referenced by path (read on demand, not copied):

- [DESIGN.md](DESIGN.md)
- [../../../docs/PROTOCOL.md](../../../docs/PROTOCOL.md)
```

Rules:

- **`## Skills`** lists shared-library skill names, one per list item. A name may
  be bare, inline-code (`` `name` ``), or a link `[name](path)` — the parser
  takes the leading token. These names are **resolved from the shared library and
  copied** into `.claude/skills/<name>/`.
- **`## Docs`** links docs by path. Docs are **referenced, never copied**; the
  agent reads them on demand.
- Keep it an index. Do not inline skill or doc bodies.

The `CLAUDE.md` stub is one line so Claude Code (which prefers `CLAUDE.md`) and
Codex/Copilot (which read `AGENTS.md`) land on the same canonical file:

```markdown
See [AGENTS.md](AGENTS.md) for the skills and docs that apply to this epic.
```

## The shared skill library

Skills are resolved by `agent.sync_refs` from the shared library, searched in
priority order (first directory holding a matching skill wins, per skill):

1. `$SPECWRIGHT_SKILL_LIBRARY` — explicit override (`os.pathsep`- or
   comma-separated list of directories).
2. `<governor_root>/skills` — the legacy local-governor store.
3. A `skills/` directory found by walking up from the epic folder — this is how
   the canonical 12 (authored as `SKILL.yaml` in the cloud-governor projection at
   `<root>/skills/<name>/SKILL.yaml`) are discovered.

Resolution is **`SKILL.yaml`-aware**: a directory qualifies as a skill if it
contains either `SKILL.yaml` (canonical) or `SKILL.md` (legacy). The whole skill
directory tree (body + `references/`) is copied.

## What happens at run (`agent.sync_refs`)

Given `epic_dir` in the payload, `agent.sync_refs`:

1. Materializes the epic's `AGENTS.md` and `CLAUDE.md` into
   `<repo>/.claude/AGENTS.md` and `<repo>/.claude/CLAUDE.md`. They land under
   `.claude/` so the **repo's own root `AGENTS.md`/`CLAUDE.md` are never
   overwritten**.
2. Parses the epic `AGENTS.md` `## Skills` section, resolves each name from the
   shared library (`SKILL.yaml`-aware), and copies it into
   `<repo>/.claude/skills/<name>/` for native discovery.
3. Leaves docs untouched — they are referenced by path.

It **degrades gracefully**: a missing `build.yaml`, a missing epic `AGENTS.md`,
or a skill name that does not resolve produces a warning and a partial sync —
never a failed step.

## One-off (epic-local) skills

A skill specific to one epic can be authored directly in an epic-local
`skills/<name>/SKILL.yaml` (or `SKILL.md`). Because the resolver walks up from
the epic folder, an epic-local `skills/` dir is found automatically.
