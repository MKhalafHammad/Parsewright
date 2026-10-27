import subprocess
import sys
from pathlib import Path

import pytest

HOOK = Path(__file__).resolve().parents[1] / "scripts" / "check_commit_msg.py"


def run_hook(tmp_path: Path, message: str) -> subprocess.CompletedProcess:
    msg = tmp_path / "COMMIT_EDITMSG"
    msg.write_text(message, encoding="utf-8")
    return subprocess.run(
        [sys.executable, str(HOOK), str(msg)],
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.parametrize(
    "message",
    [
        "chore: init\n\nCo-Authored-By: Claude <noreply@example.com>\n",
        "feat: add parser\n\nco-authored-by: someone <a@example.com>\n",
        "docs: thanks Anthropic\n",
        "fix: thing\n\nGenerated with some tool\n",
        "docs: update CLAUDE.md\n",
    ],
)
def test_rejects_attribution(tmp_path: Path, message: str) -> None:
    result = run_hook(tmp_path, message)
    assert result.returncode == 1
    assert "Commit rejected" in result.stderr


@pytest.mark.parametrize(
    "message",
    [
        "chore: initial project foundation\n",
        "feat: add validator\n\n# On branch claude/x\n# new file: CLAUDE.md\n",
        "fix: y\n# ------------------------ >8 ------------------------\n+Co-Authored-By: Claude\n",
    ],
)
def test_accepts_clean_message(tmp_path: Path, message: str) -> None:
    assert run_hook(tmp_path, message).returncode == 0
