"""
Direct unit tests for diff_substantive.diff_has_substantive_change() and
incremental_diff_text() -- see hf-03-01-silent-completion-detection.

These exercise the helper directly on hand-built diff text, not through the
engine. The real-run replays live in test_silent_completion_fixtures.py.
"""

from spec.executor.diff_substantive import (
    diff_has_substantive_change,
    incremental_diff_text,
)

MARKDOWN_SYNC_ONLY_DIFF = """\
diff --git a/CLAUDE.md b/CLAUDE.md
index 064a129..25e86c3 100644
--- a/CLAUDE.md
+++ b/CLAUDE.md
@@ -1327,3 +1327,8 @@
 (No acceptance criteria section found in spec)
 <!-- END SYNCED: SPEC: e040-09-registrar-gated-row-writes -->

+<!-- BEGIN SYNCED: SPEC: e040-06-sqlite-write-gate -->
+## Current Spec: e040-06-sqlite-write-gate
+
+## Acceptance Criteria
+<!-- END SYNCED: SPEC: e040-06-sqlite-write-gate -->
"""

HASH_SYNC_ONLY_DIFF = """\
diff --git a/.aider.conf.yml b/.aider.conf.yml
index abc1234..def5678 100644
--- a/.aider.conf.yml
+++ b/.aider.conf.yml
@@ -10,3 +10,7 @@
 # unrelated existing comment
+# BEGIN SYNCED: my-project
+# ## Current Spec: some-spec
+# (No acceptance criteria section found in spec)
+# END SYNCED: my-project
"""

REAL_CODE_CHANGE_DIFF = """\
diff --git a/src/thing.py b/src/thing.py
index 1111111..2222222 100644
--- a/src/thing.py
+++ b/src/thing.py
@@ -1,3 +1,4 @@
 def foo():
-    return 1
+    return 2
+    # a real code change
"""


class TestDiffHasSubstantiveChange:
    def test_empty_diff_is_not_substantive(self):
        assert diff_has_substantive_change("") is False

    def test_whitespace_only_diff_is_not_substantive(self):
        assert diff_has_substantive_change("   \n\n  \n") is False

    def test_markdown_sync_block_only_is_not_substantive(self):
        assert diff_has_substantive_change(MARKDOWN_SYNC_ONLY_DIFF) is False

    def test_hash_comment_sync_block_only_is_not_substantive(self):
        assert diff_has_substantive_change(HASH_SYNC_ONLY_DIFF) is False

    def test_real_code_change_is_substantive(self):
        assert diff_has_substantive_change(REAL_CODE_CHANGE_DIFF) is True

    def test_real_change_plus_sync_block_is_substantive(self):
        combined = REAL_CODE_CHANGE_DIFF + "\n" + MARKDOWN_SYNC_ONLY_DIFF
        assert diff_has_substantive_change(combined) is True

    def test_sync_block_removal_is_not_substantive(self):
        removal = MARKDOWN_SYNC_ONLY_DIFF.replace("+<!--", "-<!--").replace(
            "+## Current", "-## Current"
        ).replace("+\n", "-\n").replace("+## Acceptance", "-## Acceptance").replace(
            "+<!-- END", "-<!-- END"
        )
        assert diff_has_substantive_change(removal) is False

    def test_marker_state_resets_per_file(self):
        # An unmatched BEGIN in one file's diff must not swallow real changes
        # in the next file's diff section.
        dangling_begin = """\
diff --git a/CLAUDE.md b/CLAUDE.md
index aaa..bbb 100644
--- a/CLAUDE.md
+++ b/CLAUDE.md
@@ -1,1 +1,2 @@
 existing line
+<!-- BEGIN SYNCED: proj -->
diff --git a/src/real.py b/src/real.py
index ccc..ddd 100644
--- a/src/real.py
+++ b/src/real.py
@@ -1,1 +1,2 @@
 def f(): pass
+def g(): return 1
"""
        assert diff_has_substantive_change(dangling_begin) is True


class TestIncrementalDiffText:
    def test_identical_diffs_have_no_delta(self):
        assert incremental_diff_text(REAL_CODE_CHANGE_DIFF, REAL_CODE_CHANGE_DIFF) == ""

    def test_appended_content_is_the_delta(self):
        old = REAL_CODE_CHANGE_DIFF
        new = REAL_CODE_CHANGE_DIFF + MARKDOWN_SYNC_ONLY_DIFF
        delta = incremental_diff_text(old, new)
        assert "BEGIN SYNCED" in delta
        assert "a real code change" not in delta

    def test_delta_of_two_unrelated_diffs_is_substantive(self):
        delta = incremental_diff_text(MARKDOWN_SYNC_ONLY_DIFF, REAL_CODE_CHANGE_DIFF)
        assert diff_has_substantive_change(delta) is True
