"""
Substantive-diff detection.

A dispatched agent step can exit 0 having produced no real change to the
target repo. The harness's own refs.sync step (governance/sync_refs.py)
unconditionally appends a reference block into the target repo's CLAUDE.md
on every run, wrapped in BEGIN/END SYNCED marker sentinels -- so a
do-nothing agent pass never sees a literally-empty diff; that block IS
the diff. diff_has_substantive_change() answers the real question: does
this diff contain any changed line outside of a synced marker block?
"""

from __future__ import annotations

import difflib
import re

_BEGIN_SYNCED = re.compile(r"BEGIN SYNCED:")
_END_SYNCED = re.compile(r"END SYNCED:")


def diff_has_substantive_change(diff_text: str) -> bool:
    """
    Return True if `diff_text` (a unified diff) contains a real added/removed
    line outside of any BEGIN/END SYNCED marker pair.

    Recognizes both marker forms refs.sync writes:
      - markdown:      '<!-- BEGIN SYNCED: {project} -->' / '<!-- END SYNCED: {project} -->'
      - hash-comment:   '# BEGIN SYNCED: {project}' / '# END SYNCED: {project}'

    Lines between a BEGIN and its matching END (in either form) are excluded
    from consideration, whether they appear in the diff as context,
    additions, or removals. An unmatched BEGIN (no END before end of input,
    or before the next file's diff header) excludes everything after it --
    a truncated/malformed sync block is still synced content, not agent work.
    """
    if not diff_text or not diff_text.strip():
        return False

    in_synced_block = False
    for line in diff_text.splitlines():
        if line.startswith("diff --git "):
            # New file section starting - marker state never carries across files.
            in_synced_block = False
            continue
        if _BEGIN_SYNCED.search(line):
            in_synced_block = True
            continue
        if _END_SYNCED.search(line):
            in_synced_block = False
            continue
        if in_synced_block:
            continue
        if line.startswith("+++") or line.startswith("---"):
            # File-name header lines, not content changes.
            continue
        if line.startswith("+") or line.startswith("-"):
            if line[1:].strip():
                return True
            # A blank added/removed line carries no real content on its own --
            # e.g. the spacer line refs.sync inserts right before a marker.
            continue
    return False


def incremental_diff_text(old_diff: str, new_diff: str) -> str:
    """
    Return the lines of `new_diff` that are new or changed relative to
    `old_diff`, treating each as a sequence of lines.

    Used to isolate what a single step actually changed when both diffs are
    cumulative snapshots (e.g. "diff from the run's base commit to the
    working tree", captured once before a step dispatches and once after) --
    the parts unchanged between the two snapshots are pre-existing state,
    not this step's work.
    """
    old_lines = old_diff.splitlines(keepends=True)
    new_lines = new_diff.splitlines(keepends=True)
    matcher = difflib.SequenceMatcher(a=old_lines, b=new_lines, autojunk=False)

    added: list[str] = []
    for tag, _i1, _i2, j1, j2 in matcher.get_opcodes():
        if tag in ("insert", "replace"):
            added.extend(new_lines[j1:j2])
    return "".join(added)
