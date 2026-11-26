"""Keep Render and CI on the same runtime dependency declaration."""
from pathlib import Path
import tomllib

from packaging.requirements import Requirement

ROOT = Path(__file__).resolve().parents[1]


def _requirements(path):
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("-r"):
            continue
        requirement = Requirement(line)
        values[requirement.name.lower().replace("_", "-")] = str(requirement.specifier)
    return values


def test_pyproject_and_render_runtime_requirements_do_not_drift():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    declared = {
        Requirement(value).name.lower().replace("_", "-"): str(Requirement(value).specifier)
        for value in project["project"]["dependencies"]
    }
    assert _requirements(ROOT / "requirements.txt") == declared


def test_ci_test_requirements_include_runtime_requirements_and_pytest():
    test_requirements = (ROOT / "requirements-test.txt").read_text(encoding="utf-8")
    assert "-r requirements.txt" in test_requirements
    assert any(
        Requirement(line.strip()).name.lower() == "pytest"
        for line in test_requirements.splitlines()
        if line.strip() and not line.startswith("-")
    )
