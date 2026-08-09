"""Unit tests for sandbox artifact discovery (``services.sandbox.artifacts``).

Regression for the "FILE · 4 B" placeholder-card bug: a failed sandbox write
leaves a tiny extension-less stub (e.g. 4-byte ``blat``) that used to surface
as a download card and let the model claim it "generated" a file. The
collector must skip empty files and tiny extension-less placeholders while
keeping real deliverables (any size with an extension).
"""

from __future__ import annotations

from pathlib import Path

from deeptutor.services.sandbox import artifacts


class _FakePathService:
    """PathService stand-in: everything under *root* is public."""

    def __init__(self, root: Path) -> None:
        self._root = root

    def get_public_outputs_root(self) -> Path:
        return self._root

    def is_public_output_path(self, file_path: Path) -> bool:
        try:
            file_path.resolve().relative_to(self._root.resolve())
            return True
        except ValueError:
            return False


def _make_run(tmp_path: Path) -> tuple[Path, _FakePathService]:
    root = tmp_path
    run = root / "run1"
    run.mkdir(parents=True)
    (run / "empty.txt").write_bytes(b"")
    (run / "stub").write_bytes(b"blat")          # the reported 4-byte stub
    (run / "tiny.txt").write_bytes(b"ok!")        # tiny but has an extension
    (run / "chart.svg").write_bytes(b"<svg></svg>" * 20)
    (run / ".hidden").write_bytes(b"x")           # dotfile → filtered anyway
    sub = run / "nested"
    sub.mkdir()
    (sub / "data.csv").write_bytes(b"a,b,c\n1,2,3\n")
    return run, _FakePathService(root)


def test_collect_skips_degenerate_files(tmp_path: Path) -> None:
    run, service = _make_run(tmp_path)
    out = artifacts.collect_public_artifacts(run, path_service=service)

    filenames = {a.filename for a in out}
    assert "chart.svg" in filenames      # real deliverable
    assert "tiny.txt" in filenames       # tiny but extensioned → kept
    assert "data.csv" in filenames       # nested file
    assert "stub" not in filenames       # 4-byte extension-less placeholder
    assert "empty.txt" not in filenames  # empty file
    assert ".hidden" not in filenames    # dotfile rule


def test_collect_reports_sizes_and_urls(tmp_path: Path) -> None:
    run, service = _make_run(tmp_path)
    out = artifacts.collect_public_artifacts(run, path_service=service)

    chart = next(a for a in out if a.filename == "chart.svg")
    assert chart.size_bytes == len(b"<svg></svg>" * 20)
    assert chart.url == "/api/outputs/run1/chart.svg"
    assert chart.mime_type == "image/svg+xml"


def test_collect_empty_or_missing_workdir(tmp_path: Path) -> None:
    service = _FakePathService(tmp_path)
    assert artifacts.collect_public_artifacts(tmp_path / "missing", path_service=service) == []
    empty = tmp_path / "empty_dir"
    empty.mkdir()
    assert artifacts.collect_public_artifacts(empty, path_service=service) == []


def test_collect_honors_max_files(tmp_path: Path) -> None:
    root = tmp_path
    run = root / "run1"
    run.mkdir()
    for i in range(5):
        (run / f"f{i}.txt").write_text(f"content {i}")
    service = _FakePathService(root)
    out = artifacts.collect_public_artifacts(run, path_service=service, max_files=2)
    assert len(out) == 2


def test_render_artifacts_warns_about_invisible_stubs() -> None:
    # build artifacts directly — no filesystem dependence
    art = [
        artifacts.SandboxArtifact(
            filename="a.svg", path="/x/a.svg", relative_path="a.svg",
            url="/api/outputs/a.svg", size_bytes=120, mime_type="image/svg+xml",
        )
    ]
    text = artifacts.render_artifacts_for_tool(art)
    assert "a.svg (120 B)" in text
    assert "NOT surfaced" in text  # the degenerate-stub warning
    assert artifacts.render_artifacts_for_tool([]) == ""
