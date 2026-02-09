"""Nox sessions for linting, formatting, and testing."""

import tomllib
from pathlib import Path

import nox

nox.options.default_venv_backend = "uv"
nox.options.reuse_venv = "yes"
nox.options.sessions = ["ruff", "pylint", "tests"]


def _project_deps() -> list[str]:
    """Read project dependencies from pyproject.toml."""
    data = tomllib.loads(Path("pyproject.toml").read_text())
    return data["project"]["dependencies"]


@nox.session
def ruff(session: nox.Session) -> None:
    """Run ruff linter and formatter checks."""
    session.install("ruff")
    session.run("ruff", "check", ".")
    session.run("ruff", "format", "--check", ".")


@nox.session
def pylint(session: nox.Session) -> None:
    """Run pylint on app module."""
    session.install("pylint", *_project_deps())
    session.run("pylint", "app")


@nox.session
def tests(session: nox.Session) -> None:
    """Run the test suite."""
    session.install("pytest", *_project_deps())
    session.run("pytest")
