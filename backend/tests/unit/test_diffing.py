from app.services.codegen.diffing import (
    apply_patch,
    count_patch_lines,
    make_new_file_diff,
    make_unified_diff,
)


def test_unified_diff_roundtrip():
    old = "a\nb\nc\n"
    new = "a\nb\nX\nc\n"
    patch = make_unified_diff("f.py", old, new)
    assert apply_patch(old, patch) == new


def test_new_file_diff_applies_as_pure_addition():
    content = "line1\nline2\n"
    patch = make_new_file_diff("new.py", content)
    result = apply_patch("", patch)
    assert result.strip() == content.strip()


def test_count_patch_lines_counts_added_and_removed():
    old = "a\nb\n"
    new = "a\nc\n"
    patch = make_unified_diff("f.py", old, new)
    # one removed ("b") + one added ("c")
    assert count_patch_lines(patch) == 2


def test_count_patch_lines_ignores_headers():
    patch = "--- a/f.py\n+++ b/f.py\n@@ -1 +1 @@\n-old\n+new\n"
    assert count_patch_lines(patch) == 2
