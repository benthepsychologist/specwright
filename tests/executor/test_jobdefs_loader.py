"""Tests for JobDef loader config-path and bundled fallback behavior."""

from __future__ import annotations

from pathlib import Path

import yaml

from spec.executor.jobdefs import list_job_defs, load_job_def


def _write_config(path: Path, jobdefs_path: Path) -> None:
    cfg = {
        "version": "0.7",
        "jobdefs": {
            "path": str(jobdefs_path),
            "fallback": "bundled",
        },
    }
    path.write_text(yaml.safe_dump(cfg, sort_keys=False), encoding="utf-8")


def test_load_job_def_prefers_configured_path(tmp_path, monkeypatch) -> None:
    custom_jobdefs = tmp_path / "jobdefs"
    custom_jobdefs.mkdir(parents=True)
    (custom_jobdefs / "aip-1.yaml").write_text(
        yaml.safe_dump(
            {
                "job_id": "aip-1",
                "version": "9.9",
                "kind": "jobdef",
                "artifact_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                "name": "aip-1",
                "steps": [
                    {
                        "step_id": "custom.step",
                        "backend": "cmd",
                        "payload": {"command": "echo custom"},
                    }
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    _write_config(tmp_path / ".specwright.yaml", custom_jobdefs)
    monkeypatch.chdir(tmp_path)

    job_def = load_job_def("aip-1")
    assert job_def.version == "9.9"
    assert job_def.steps[0].step_id == "custom.step"


def test_load_job_def_falls_back_to_bundled(tmp_path, monkeypatch) -> None:
    configured_jobdefs = tmp_path / "configured-jobdefs"
    configured_jobdefs.mkdir(parents=True)
    _write_config(tmp_path / ".specwright.yaml", configured_jobdefs)
    monkeypatch.chdir(tmp_path)

    job_def = load_job_def("interactive-1")
    assert job_def.job_id == "interactive-1"
    assert job_def.kind == "jobdef"
    assert job_def.name == "interactive-1"
    assert job_def.artifact_id


def test_list_job_defs_includes_bundled_when_configured_dir_empty(tmp_path, monkeypatch) -> None:
    configured_jobdefs = tmp_path / "configured-jobdefs"
    configured_jobdefs.mkdir(parents=True)
    _write_config(tmp_path / ".specwright.yaml", configured_jobdefs)
    monkeypatch.chdir(tmp_path)

    available = list_job_defs()
    assert "aip-1" in available
    assert "interactive-1" in available
    assert "harness-probe-1" in available
