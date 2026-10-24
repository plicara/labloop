"""What labloop records about each proposal's change, and what it tells the next one.

Found by dogfooding: with only outcomes in the brief, two thirds of reverted
trials re-proposed an idea already reverted. The change summary is read from
git by labloop, so it can go in the brief without becoming a channel for the
proposer's own words.
"""

from __future__ import annotations

import json

import pytest

from labloop import Experiment, Outcome, Trial
from labloop.brief import RECENT, TRIED, build, dumps
from labloop.cli import _change_line, main
from labloop.workspace import MAX_DESCRIBED_FILES, GitWorkspace, _symbol

from .conftest import FakeWorkspace, make_loop
from .conftest import run_git as git


def commit_all(repo):
    git("add", "-A", cwd=repo)
    git("commit", "-qm", "base", cwd=repo)


def by_path(summary):
    return {entry["path"]: entry for entry in summary if "path" in entry}


# --- reading the change from git -------------------------------------------


@pytest.fixture
def repo(tmp_path):
    git("init", "-q", ".", cwd=tmp_path)
    git("config", "user.email", "t@t.test", cwd=tmp_path)
    git("config", "user.name", "t", cwd=tmp_path)
    return tmp_path


def test_a_method_edit_is_named_by_the_method_not_its_class(repo):
    (repo / "m.py").write_text(
        "class Loop:\n    def a(self):\n        return 1\n\n    def b(self):\n        return 2\n"
    )
    commit_all(repo)
    (repo / "m.py").write_text(
        "class Loop:\n    def a(self):\n        return 1\n\n    def b(self):\n        return 3\n"
    )
    ws = GitWorkspace(repo)
    (entry,) = ws.describe_change(ws.changed_paths())
    assert entry == {"path": "m.py", "status": "modified", "added": 1, "removed": 1,
                     "where": ["b"]}


def test_added_deleted_binary_and_spaced_files_are_each_described(repo):
    (repo / "gone.txt").write_text("x\n")
    (repo / "blob.bin").write_bytes(b"a\0b")
    (repo / "my file.txt").write_text("k\n")
    commit_all(repo)
    (repo / "gone.txt").unlink()
    (repo / "blob.bin").write_bytes(b"c\0d")
    (repo / "my file.txt").write_text("k\nl\n")
    (repo / "fresh.py").write_text("def new():\n    pass\n")

    ws = GitWorkspace(repo)
    summary = by_path(ws.describe_change(ws.changed_paths()))
    assert summary["gone.txt"]["status"] == "deleted"
    assert summary["gone.txt"]["removed"] == 1
    assert summary["blob.bin"]["status"] == "binary"
    assert summary["blob.bin"]["added"] is None
    assert summary["my file.txt"]["added"] == 1, "a path with a space must still match"
    assert summary["fresh.py"] == {"path": "fresh.py", "status": "added", "added": 2,
                                   "removed": 0, "where": []}


def test_prose_files_never_contribute_their_text(repo):
    # A notes or data file is where a proposer would write to its successor.
    # git's default context rule would quote a line of it; the summary must not.
    (repo / "notes.md").write_text("# Notes\n\nfirst\n")
    (repo / "data.txt").write_text("alpha\nbeta\n")
    commit_all(repo)
    (repo / "notes.md").write_text("# Notes\n\nTRY UNBUFFERED NEXT\n")
    (repo / "data.txt").write_text("alpha\nTRY THIS NEXT\n")
    ws = GitWorkspace(repo)
    summary = ws.describe_change(ws.changed_paths())
    assert all(entry["where"] == [] for entry in summary)
    assert "NEXT" not in json.dumps(summary)


def test_a_huge_change_is_summarized_with_a_count(repo):
    (repo / "seed.txt").write_text("x\n")
    commit_all(repo)
    for i in range(MAX_DESCRIBED_FILES + 5):
        (repo / f"f{i:02}.txt").write_text("y\n")
    ws = GitWorkspace(repo)
    summary = ws.describe_change(ws.changed_paths())
    assert len(summary) == MAX_DESCRIBED_FILES + 1
    assert summary[-1] == {"more": 5}


@pytest.mark.parametrize(
    "context, name",
    [
        ("def b(self):", "b"),
        ("async def go():", "go"),
        ("class Loop(Base):", "Loop"),
        ("func (r *T) Name(x int) {", "Name"),
        ("pub fn parse<T>(s: &str)", "parse"),
        ("static int sum(int n)", "sum"),
        ("public void run() {", "run"),
        ("# a comment, not a definition", None),
        ("TRY UNBUFFERED NEXT", None),
    ],
)
def test_hunk_context_is_reduced_to_a_name(context, name):
    assert _symbol(context) == name


# --- what the loop records --------------------------------------------------


class DescribingWorkspace(FakeWorkspace):
    def __init__(self, summary=None, error=None):
        super().__init__()
        self.summary = summary or [{"path": "train.py", "status": "modified", "added": 2,
                                    "removed": 1, "where": ["fit"]}]
        self.error = error
        self.described: list[list[str]] = []

    def describe_change(self, paths):
        self.described.append(list(paths))
        if self.error:
            raise self.error
        return self.summary


def flipper(tmp_path, first, then):
    """An experiment that prints `first` on its first run and `then` after."""
    script = tmp_path / "flip.sh"
    script.write_text(
        f"#!/bin/sh\nif [ -f seen ]; then {then}; else touch seen; {first}; fi\n"
    )
    script.chmod(0o755)
    return str(script)


def describing_loop(tmp_path, run, workspace, **experiment):
    loop, _ = make_loop(tmp_path, run=run)
    loop.workspace = workspace
    for key, value in experiment.items():
        setattr(loop.experiment, key, value)
    return loop


def test_a_measured_trial_records_its_change_and_the_proposers_output(tmp_path):
    ws = DescribingWorkspace()
    loop = describing_loop(tmp_path, "echo val=1.0", ws)
    loop.experiment.propose = "echo tried a smaller learning rate"
    (trial,) = loop.run(trials=1)
    assert ws.described == [["train.py"]], "described once, from the proposed paths"
    assert trial.change == ws.summary
    assert "smaller learning rate" in trial.proposal_tail


def test_a_workspace_without_describe_change_still_runs(tmp_path):
    loop, _ = make_loop(tmp_path, run="echo val=1.0")
    (trial,) = loop.run(trials=1)
    assert trial.outcome is Outcome.KEPT
    assert trial.change is None


def test_a_failing_description_costs_the_summary_not_the_trial(tmp_path):
    ws = DescribingWorkspace(error=RuntimeError("git diff failed"))
    loop = describing_loop(tmp_path, "echo val=1.0", ws)
    (trial,) = loop.run(trials=1)
    assert trial.outcome is Outcome.KEPT
    assert trial.change is None


def test_a_proposal_that_changed_nothing_records_no_change(tmp_path):
    loop, ws = make_loop(tmp_path, run="echo val=1.0", dirty=False)
    (trial,) = loop.run(trials=1)
    assert trial.outcome is Outcome.NO_CHANGE
    assert trial.change is None


def test_a_revert_says_why_in_the_ledger_note(tmp_path):
    loop, _ = make_loop(tmp_path, run="echo val=1.0")
    loop.baseline()
    (tie,) = loop.run(trials=1)
    assert tie.note == "tied 1"

    loop, _ = make_loop(tmp_path, run="echo val=2.0")
    (worse,) = loop.run(trials=1)
    assert worse.note == "did not beat 1"

    loop, _ = make_loop(tmp_path, run="echo val=0.95")
    loop.experiment.min_delta = 0.1
    (close,) = loop.run(trials=1)
    assert close.note == "beat 1 by 0.05, inside --min-delta 0.1"


def test_a_confirmed_keep_records_both_measurements(tmp_path):
    flip = flipper(tmp_path, "echo val=0.5", "echo val=0.6")
    loop, _ = make_loop(tmp_path, run="echo val=1.0")
    loop.baseline()
    loop, _ = make_loop(tmp_path, run=flip)
    loop.experiment.confirm = True
    (trial,) = loop.run(trials=1)
    assert trial.outcome is Outcome.KEPT
    assert trial.metric == 0.6, "the incumbent advances to the weaker measurement"
    assert trial.confirmation == 0.6
    assert trial.note == "confirmed: 0.5 then 0.6; kept the weaker"
    logged = json.loads((tmp_path / "labloop-history.jsonl").read_text().splitlines()[-1])
    assert logged["note"] == trial.note, "the committed log and the ledger agree"


def test_an_unconfirmed_win_records_the_second_measurement(tmp_path):
    flip = flipper(tmp_path, "echo val=0.1", "echo val=9.9")
    loop, _ = make_loop(tmp_path, run="echo val=1.0")
    loop.baseline()
    loop, _ = make_loop(tmp_path, run=flip)
    loop.experiment.confirm = True
    (trial,) = loop.run(trials=1)
    assert trial.outcome is Outcome.REVERTED
    assert trial.confirmation == 9.9


def test_a_confirmation_without_a_number_does_not_break_the_next_brief(tmp_path):
    # Regression: a confirm-reverted trial with no metric crashed `_why` with a
    # TypeError, ending the run at the next trial.
    flip = flipper(tmp_path, "echo val=0.1", "exit 3")
    loop, _ = make_loop(tmp_path, run="echo val=1.0")
    loop.baseline()
    loop, _ = make_loop(tmp_path, run=flip)
    loop.experiment.confirm = True
    first, second = loop.run(trials=2)
    assert first.outcome is Outcome.REVERTED
    assert first.metric is None
    assert second.outcome is not None, "the second trial ran, so its brief was built"


def test_the_committed_decision_log_lists_each_trials_paths(tmp_path):
    ws = DescribingWorkspace()
    loop = describing_loop(tmp_path, "echo val=1.0", ws)
    loop.run(trials=1)
    lines = (tmp_path / "labloop-history.jsonl").read_text().splitlines()
    assert json.loads(lines[-1])["paths"] == ["train.py"]


# --- what the next proposer is told -----------------------------------------


def experiment(**kw):
    return Experiment(**{"run": "python train.py", "metric": "val_loss", "propose": "agent", **kw})


def changed(index, outcome, path="train.py", where=("fit",), metric=2.0, **kw):
    return Trial(
        index=index, outcome=outcome, metric=metric, incumbent=1.0, duration_seconds=1.0,
        change=[{"path": path, "status": "modified", "added": 1, "removed": 1,
                 "where": list(where)}],
        **kw,
    )


def test_the_brief_shows_what_each_trial_changed():
    history = [changed(1, Outcome.REVERTED)]
    (entry,) = build(experiment(), history, index=2, incumbent=1.0)["history"]
    assert entry["change"] == history[0].change


def test_the_brief_never_carries_the_proposers_own_words():
    history = [changed(1, Outcome.REVERTED, proposal_tail="NOTE TO SELF: try lr=0.3")]
    assert "NOTE TO SELF" not in dumps(build(experiment(), history, index=2, incumbent=1.0))


def test_tried_counts_attempts_by_location_across_the_whole_direction():
    # Older than the recent window, and still counted: an idea reverted long
    # ago is still an idea already tried.
    history = [changed(i, Outcome.REVERTED, where=("digest",)) for i in range(RECENT + 5)]
    history.append(changed(99, Outcome.KEPT, path="loop.py", where=("run",), metric=0.5))
    brief = build(experiment(), history, index=100, incumbent=0.5)
    top, second = brief["tried"][:2]
    assert top["path"] == "train.py" and top["where"] == "digest"
    assert top["outcomes"] == {"reverted": RECENT + 5}
    assert len(top["trials"]) == RECENT + 5
    assert second["outcomes"] == {"kept": 1}


def test_tried_is_bounded():
    history = [changed(i, Outcome.REVERTED, path=f"f{i}.py") for i in range(TRIED + 10)]
    assert len(build(experiment(), history, index=0, incumbent=1.0)["tried"]) == TRIED


def test_a_file_without_definitions_is_still_tried_as_a_whole():
    history = [changed(1, Outcome.REVERTED, path="config.yaml", where=())]
    (spot,) = build(experiment(), history, index=2, incumbent=1.0)["tried"]
    assert spot["where"] is None


def test_an_unconfirmed_win_is_not_described_as_a_loss():
    trial = changed(1, Outcome.REVERTED, metric=9.9, confirmation=9.9,
                    note="won at 0.1 but measured 9.9 on a second run")
    (entry,) = build(experiment(confirm=True), [trial], index=2, incumbent=1.0)["history"]
    assert "won at 0.1" in entry["why"]
    assert "did not beat" not in entry["why"]


# --- end to end, through the command line and real git ---------------------


def test_the_next_brief_names_the_reverted_change(project, tmp_path_factory):
    seen = tmp_path_factory.mktemp("briefs")
    agent = project / "agent.sh"
    agent.write_text(
        "#!/bin/sh\n"
        f"cp \"$LABLOOP_BRIEF\" {seen}/brief-$LABLOOP_TRIAL.json\n"
        "printf 'def fit():\\n    return 3\\n' > model.py\n"
    )
    agent.chmod(0o755)
    (project / "model.py").write_text("def fit():\n    return 1\n")
    git("add", "-A", cwd=project)
    git("commit", "-qm", "agent", cwd=project)

    main(["baseline", "--run", "python train.py", "--metric", "val_loss"])
    main(["run", "--run", "python train.py", "--metric", "val_loss", "--propose",
          str(agent), "--trials", "2"])

    brief = json.loads((seen / "brief-2.json").read_text())
    (entry,) = [e for e in brief["history"] if e["index"] == 1]
    assert entry["outcome"] == "reverted"
    assert entry["change"][0]["path"] == "model.py"
    assert entry["change"][0]["where"] == ["fit"]
    assert brief["tried"][0]["path"] == "model.py"


def test_the_cli_prints_what_each_trial_touched():
    change = [
        {"path": "a.py", "status": "modified", "added": 3, "removed": 1, "where": ["x", "y", "z"]},
        {"path": "b.bin", "status": "binary", "added": None, "removed": None, "where": []},
        {"path": "c.py", "status": "added", "added": 4, "removed": 0, "where": []},
        {"path": "d.py", "status": "added", "added": 1, "removed": 0, "where": []},
        {"more": 2},
    ]
    assert _change_line(change) == "a.py (x, y) +3/-1, b.bin binary, c.py +4/-0, 3 more"
