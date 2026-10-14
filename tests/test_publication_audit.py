from __future__ import annotations

import subprocess
from pathlib import Path

from scripts.audit_publication import RULE_SECRET, audit, main, scan_working_tree


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


def _repository(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "audit@example.invalid")
    _git(root, "config", "user.name", "Audit Test")
    return root


def test_secret_finding_reports_path_and_rule_without_value(tmp_path: Path, capsys) -> None:
    root = _repository(tmp_path)
    secret = "sk-" + "proj-THIS_IS_A_FAKE_TEST_VALUE_123456"
    (root / "settings.py").write_text(f'API_KEY = "{secret}"\n', encoding="utf-8")
    _git(root, "add", "settings.py")

    assert main(["--root", str(root)]) == 1
    output = capsys.readouterr().out
    assert "settings.py\tpossible-secret" in output
    assert secret not in output
    assert "findings=1" in output


def test_environment_examples_and_placeholder_values_are_allowed(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    (root / ".env.example").write_text("API_KEY=your-api-key-here\n", encoding="utf-8")
    (root / "config.py").write_text('TOKEN = "<set-in-environment>"\n', encoding="utf-8")
    _git(root, "add", ".env.example", "config.py")

    assert audit(root) == []


def test_quoted_secret_detection_ignores_variable_references(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    (root / "providers.py").write_text(
        "api_key = self.settings.openai_api_key.get_secret_value()\n",
        encoding="utf-8",
    )
    literal = "long-" + "hardcoded-test-value-123"
    (root / "config.py").write_text(f'API_KEY = "{literal}"\n', encoding="utf-8")
    _git(root, "add", "providers.py", "config.py")

    findings = audit(root)
    assert [(finding.path, finding.rule) for finding in findings] == [
        ("config.py", "possible-secret")
    ]


def test_banned_file_is_reported_without_scanning_its_contents(tmp_path: Path, capsys) -> None:
    root = _repository(tmp_path)
    private_value = "NEVER_PRINT_THIS_PRIVATE_LOG_VALUE"
    (root / "logs").mkdir()
    (root / "logs" / "application.log").write_text(private_value, encoding="utf-8")
    _git(root, "add", "logs/application.log")

    assert main(["--root", str(root)]) == 1
    output = capsys.readouterr().out
    assert "logs/application.log\tbanned-file" in output
    assert private_value not in output


def test_private_research_data_directories_are_banned(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    (root / "data").mkdir()
    (root / "data" / "records.json").write_text('{"private": true}', encoding="utf-8")
    _git(root, "add", "data/records.json")

    assert [(f.path, f.rule) for f in audit(root)] == [("data/records.json", "banned-file")]


def test_export_scan_prunes_nested_worktrees(tmp_path: Path) -> None:
    root = tmp_path / "export"
    nested = root / ".worktrees" / "another-worktree"
    nested.mkdir(parents=True)
    (root / ".git").write_text("gitdir: .git/worktrees/export\n", encoding="utf-8")
    (nested / "private.py").write_text('TOKEN="sk-' + "x" * 32 + '"\n', encoding="utf-8")

    assert audit(root, export=True) == []


def test_export_scan_reports_private_directory_without_descending(tmp_path: Path) -> None:
    root = tmp_path / "export"
    private_dir = root / "data"
    private_dir.mkdir(parents=True)
    (private_dir / "nested.json").write_text('{"private": true}', encoding="utf-8")

    assert [(f.path, f.rule) for f in audit(root, export=True)] == [("data", "banned-file")]


def test_history_finds_old_secret_with_object_id_without_value(tmp_path: Path, capsys) -> None:
    root = _repository(tmp_path)
    old_secret = "ghp_" + "FAKE_HISTORY_VALUE_01234567890123456789"
    (root / "config.py").write_text(f'TOKEN="{old_secret}"\n', encoding="utf-8")
    _git(root, "add", "config.py")
    _git(root, "commit", "-qm", "fixture")
    (root / "config.py").write_text('TOKEN="placeholder"\n', encoding="utf-8")

    findings = audit(root, history=True)
    assert any(
        f.path == "config.py" and f.rule == "possible-secret" and f.object_id for f in findings
    )
    assert all(old_secret not in str(finding) for finding in findings)

    assert main(["--root", str(root), "--history"]) == 1
    output = capsys.readouterr().out
    assert "config.py\tpossible-secret object=" in output
    assert old_secret not in output


def test_environment_template_is_checked_for_secrets(tmp_path):
    (tmp_path / ".env.example").write_bytes(b"sk-" + b"A" * 24)
    findings = scan_working_tree(tmp_path, export=True)
    assert len(findings) == 1
    assert findings[0].rule == RULE_SECRET
