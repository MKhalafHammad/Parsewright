"""scripts/init_env.py and scripts/env_set.py: the only code that writes secrets into .env.

Each runs on a copy of the scripts in a temporary repo, so the real .env is never touched.
"""

import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
# A token-shaped fake, built at runtime so the source never looks like a real JWT to gitleaks.
JWT = ".".join(["header" + "x" * 10, "payload" + "y" * 20, "signature" + "z" * 10])


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    (tmp_path / "scripts").mkdir()
    for name in ("init_env.py", "env_set.py"):
        shutil.copy(SCRIPTS / name, tmp_path / "scripts" / name)
    (tmp_path / ".env.example").write_text(
        "LLM_API_KEY=your-meta-api-key-here\n"
        "SPLUNK_PASSWORD=changeme-to-a-long-password\n"
        "POSTGRES_PASSWORD=changeme-to-a-long-password\n"
        "POSTGRES_APP_PASSWORD=changeme-to-another-long-password\n"
        "SPLUNK_SEARCH_TOKEN=your-parsewright-search-token-here\n"
        "WEB_PORT=3000\n"
    )
    return tmp_path


def run(repo: Path, script: str, stdin: str = "") -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(repo / "scripts" / script)],
        input=stdin,
        capture_output=True,
        text=True,
        check=False,
    )


def env(repo: Path) -> dict[str, str]:
    lines = (repo / ".env").read_text().splitlines()
    return dict(ln.partition("=")[::2] for ln in lines if "=" in ln)


def test_init_generates_placeholder_passwords_and_never_prints_them(repo: Path) -> None:
    r = run(repo, "init_env.py")
    values = env(repo)
    for key in ("SPLUNK_PASSWORD", "POSTGRES_PASSWORD", "POSTGRES_APP_PASSWORD"):
        assert values[key].isalnum() and len(values[key]) == 32
        assert values[key] not in r.stdout + r.stderr
    assert len({values["POSTGRES_PASSWORD"], values["POSTGRES_APP_PASSWORD"]}) == 2
    assert values["WEB_PORT"] == "3000"
    assert stat.S_IMODE((repo / ".env").stat().st_mode) == 0o600
    # The key is still a placeholder, so it says so and fails.
    assert r.returncode == 1 and "LLM_API_KEY" in r.stderr


def test_init_keeps_passwords_already_set(repo: Path) -> None:
    (repo / ".env").write_text("LLM_API_KEY=k-123\nSPLUNK_PASSWORD=MyOwnPassword1\n")
    assert run(repo, "init_env.py").returncode == 0
    assert env(repo)["SPLUNK_PASSWORD"] == "MyOwnPassword1"


def test_env_set_stores_tokens_quietly(repo: Path) -> None:
    run(repo, "init_env.py")
    r = run(
        repo, "env_set.py", f"SPLUNK_SEARCH_TOKEN={JWT}\nSPLUNK_DEPLOY_TOKEN={JWT}x\n"
    )
    assert r.returncode == 0
    assert JWT not in r.stdout + r.stderr
    assert env(repo)["SPLUNK_SEARCH_TOKEN"] == JWT
    assert env(repo)["SPLUNK_DEPLOY_TOKEN"] == JWT + "x"  # appended when missing
    assert stat.S_IMODE((repo / ".env").stat().st_mode) == 0o600


@pytest.mark.parametrize(
    "line",
    [
        "LLM_BASE_URL=https://evil.example.com/v1",  # only the three token keys
        "POSTGRES_PASSWORD=" + "a" * 30,
        "SPLUNK_SEARCH_TOKEN=abc def ghi jkl mno pqr",  # spaces
        f"SPLUNK_SEARCH_TOKEN={JWT}\nLLM_API_KEY=x",
        "SPLUNK_SEARCH_TOKEN=" + JWT + "'; rm -rf ~ #",  # shell or quoting characters
        "SPLUNK_SEARCH_TOKEN=short",
    ],
)
def test_env_set_refuses_anything_else(repo: Path, line: str) -> None:
    run(repo, "init_env.py")
    before = (repo / ".env").read_text()
    r = run(repo, "env_set.py", line + "\n")
    assert r.returncode == 1
    assert (repo / ".env").read_text() == before  # nothing written
