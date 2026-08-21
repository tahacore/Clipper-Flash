
from typer.testing import CliRunner

from clipper_flash.cli import (
    _SKILL_MARK_BEGIN,
    _SKILL_MARK_END,
    _bundled_skill_dir,
    _codex_agents_block,
    app,
)

runner = CliRunner()


def test_bundled_skill_resolves_in_dev_checkout() -> None:
    d = _bundled_skill_dir()
    assert d is not None
    assert (d / "SKILL.md").exists()


def test_install_skill_to_custom_dirs(tmp_path) -> None:
    claude = tmp_path / "claude-skills"
    codex_home = tmp_path / "codex"
    result = runner.invoke(
        app,
        [
            "install-skill",
            "--claude-dir", str(claude),
            "--codex-home", str(codex_home),
        ],
    )
    assert result.exit_code == 0, result.output
    skill_file = claude / "SKILL.md"
    assert skill_file.exists()
    # cross-agent standard location (sibling of the codex home we passed)
    agents_skill = tmp_path / ".agents" / "skills" / "clipper-flash" / "SKILL.md"
    assert agents_skill.exists(), result.output
    agents = codex_home / "AGENTS.md"
    assert agents.exists()
    content = agents.read_text(encoding="utf-8")
    assert _SKILL_MARK_BEGIN in content and _SKILL_MARK_END in content
    assert str(skill_file) in content


def test_install_skill_is_idempotent(tmp_path) -> None:
    claude = tmp_path / "claude-skills"
    codex_home = tmp_path / "codex"
    args = ["install-skill", "--claude-dir", str(claude), "--codex-home", str(codex_home)]
    first = runner.invoke(app, args)
    assert first.exit_code == 0
    agents = codex_home / "AGENTS.md"
    before = agents.read_text(encoding="utf-8")
    second = runner.invoke(app, args)
    assert second.exit_code == 0
    after = agents.read_text(encoding="utf-8")
    assert after.count(_SKILL_MARK_BEGIN) == 1
    assert after.count("## Clipper-Flash") == 1
    # content identical apart from whitespace churn
    assert before.replace("\n", "") == after.replace("\n", "")


def test_codex_block_preserves_existing_content(tmp_path) -> None:
    codex_home = tmp_path / "codex"
    codex_home.mkdir()
    agents = codex_home / "AGENTS.md"
    agents.write_text("# My rules\n\nBe nice.\n", encoding="utf-8")
    result = runner.invoke(
        app, ["install-skill", "--claude-dir", str(tmp_path / "c"), "--codex-home", str(codex_home)]
    )
    assert result.exit_code == 0
    content = agents.read_text(encoding="utf-8")
    assert "# My rules" in content and "Be nice." in content
    assert content.index("# My rules") < content.index(_SKILL_MARK_BEGIN)


def test_skip_codex_flag(tmp_path) -> None:
    result = runner.invoke(
        app,
        ["install-skill", "--claude-dir", str(tmp_path / "c"), "--skip-codex"],
    )
    assert result.exit_code == 0
    assert "SKIP" in result.output


def test_codex_block_format() -> None:
    block = _codex_agents_block("/some/path/SKILL.md")
    assert block.startswith(_SKILL_MARK_BEGIN)
    assert "/some/path/SKILL.md" in block
    assert block.rstrip().endswith(_SKILL_MARK_END)
