"""The engine image must hold every file its package metadata points at."""

import tomllib
from pathlib import Path

ENGINE = Path(__file__).resolve().parents[1] / "engine"


def test_dockerfile_copies_the_readme_named_in_pyproject():
    readme = tomllib.loads((ENGINE / "pyproject.toml").read_text())["project"]["readme"]
    copies = [
        line.split()[1:-1]
        for line in (ENGINE / "Dockerfile").read_text().splitlines()
        if line.startswith("COPY ")
    ]
    assert any(readme in sources for sources in copies)
