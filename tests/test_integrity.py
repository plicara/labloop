"""Digesting the files that define a measurement."""

from __future__ import annotations

import pytest

from labloop import NoProtectedFilesError, harness_digest
from labloop.integrity import changed_files, harness_files


def write(root, name: str, text: str = "x"):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def test_no_patterns_means_no_claim(tmp_path):
    assert harness_digest(tmp_path, ()) is None


def test_digest_is_stable_across_calls(tmp_path):
    write(tmp_path, "eval.py", "print(1)")
    assert harness_digest(tmp_path, ["eval.py"]) == harness_digest(tmp_path, ["eval.py"])


def test_edited_content_moves_the_digest(tmp_path):
    write(tmp_path, "eval.py", "threshold = 0.5")
    before = harness_digest(tmp_path, ["eval.py"])
    write(tmp_path, "eval.py", "threshold = 0.0")
    assert harness_digest(tmp_path, ["eval.py"]) != before


def test_rename_moves_the_digest_though_bytes_are_identical(tmp_path):
    write(tmp_path, "a.py", "same")
    write(tmp_path, "b.py", "same")
    assert harness_digest(tmp_path, ["a.py"]) != harness_digest(tmp_path, ["b.py"])


def test_directory_pattern_covers_the_subtree(tmp_path):
    write(tmp_path, "data/holdout/rows.csv", "1,2")
    before = harness_digest(tmp_path, ["data"])

    write(tmp_path, "data/holdout/rows.csv", "1,3")
    assert harness_digest(tmp_path, ["data"]) != before


def test_added_file_in_a_protected_directory_is_detected(tmp_path):
    write(tmp_path, "data/rows.csv", "1,2")
    before = harness_digest(tmp_path, ["data"])

    write(tmp_path, "data/answers.csv", "leaked")
    assert harness_digest(tmp_path, ["data"]) != before, (
        "memorizing answers means adding files, not only editing them"
    )


def test_deleted_file_is_detected(tmp_path):
    write(tmp_path, "data/a.csv")
    write(tmp_path, "data/b.csv")
    before = harness_digest(tmp_path, ["data"])

    (tmp_path / "data/b.csv").unlink()
    assert harness_digest(tmp_path, ["data"]) != before


def test_glob_pattern_matches_several_files(tmp_path):
    write(tmp_path, "evals/one.py", "a")
    write(tmp_path, "evals/two.py", "b")
    before = harness_digest(tmp_path, ["evals/*.py"])

    write(tmp_path, "evals/two.py", "c")
    assert harness_digest(tmp_path, ["evals/*.py"]) != before


def test_a_symlink_replacing_a_protected_file_is_detected(tmp_path):
    write(tmp_path, "eval.py", "real")
    write(tmp_path, "other.py", "real")

    # Same bytes as the original, but reached through a link. Excluding
    # symlinks means the file drops out of the set, which moves the digest.
    (tmp_path / "eval.py").unlink()
    (tmp_path / "eval.py").symlink_to(tmp_path / "other.py")
    with pytest.raises(NoProtectedFilesError):
        harness_digest(tmp_path, ["eval.py"])


def test_patterns_matching_nothing_are_an_error_not_a_silent_pass(tmp_path):
    with pytest.raises(NoProtectedFilesError, match="matched no files"):
        harness_digest(tmp_path, ["evla.py"])


def test_changed_files_names_what_moved(tmp_path):
    write(tmp_path, "a.py", "one")
    write(tmp_path, "b.py", "two")
    before = harness_files(tmp_path, ["*.py"])

    write(tmp_path, "b.py", "changed")
    assert changed_files(before, harness_files(tmp_path, ["*.py"])) == "b.py"


def test_changed_files_reports_additions_and_deletions(tmp_path):
    write(tmp_path, "data/a.csv", "1")
    before = harness_files(tmp_path, ["data"])

    write(tmp_path, "data/.cache", "junk")
    (tmp_path / "data/a.csv").unlink()
    moved = changed_files(before, harness_files(tmp_path, ["data"]))
    assert "data/.cache" in moved and "data/a.csv" in moved


def test_changed_files_is_bounded(tmp_path):
    for i in range(10):
        write(tmp_path, f"f{i}.py", "same")
    before = harness_files(tmp_path, ["*.py"])
    for i in range(10):
        write(tmp_path, f"f{i}.py", "different")

    moved = changed_files(before, harness_files(tmp_path, ["*.py"]))
    assert "and 7 more" in moved, "an error message should not list every file"


def test_changed_files_says_nothing_when_nothing_moved(tmp_path):
    write(tmp_path, "a.py", "one")
    files = harness_files(tmp_path, ["a.py"])
    assert changed_files(files, files) == ""


def test_unprotected_files_do_not_move_the_digest(tmp_path):
    write(tmp_path, "eval.py", "frozen")
    write(tmp_path, "train.py", "before")
    before = harness_digest(tmp_path, ["eval.py"])

    write(tmp_path, "train.py", "after")
    assert harness_digest(tmp_path, ["eval.py"]) == before, (
        "the loop must still be free to change the code under study"
    )
