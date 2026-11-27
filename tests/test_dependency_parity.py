"""Keep Render and CI dependency declarations and resolved pins in sync."""
from pathlib import Path
import tomllib

from packaging.requirements import Requirement
from packaging.version import Version

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


def _pinned_versions(path):
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("-r"):
            continue
        requirement = Requirement(line)
        assert len(requirement.specifier) == 1
        specifier = next(iter(requirement.specifier))
        assert specifier.operator == "==", f"{path.name} must pin {requirement.name}"
        values[requirement.name.lower().replace("_", "-")] = Version(specifier.version)
    return values


def test_pyproject_and_render_runtime_requirements_do_not_drift():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    declared = {
        Requirement(value).name.lower().replace("_", "-"): str(Requirement(value).specifier)
        for value in project["project"]["dependencies"]
    }
    assert _requirements(ROOT / "requirements.txt") == declared


def test_runtime_lock_pins_every_declared_requirement_within_its_range():
    declared = {
        Requirement(value).name.lower().replace("_", "-"): Requirement(value)
        for value in tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["dependencies"]
    }
    pinned = _pinned_versions(ROOT / "requirements.lock")
    for name, requirement in declared.items():
        assert name in pinned, f"{name} is missing from requirements.lock"
        assert pinned[name] in requirement.specifier, (
            f"{name}=={pinned[name]} is outside declared range {requirement.specifier}"
        )


def test_render_and_ci_install_the_pinned_lockfiles():
    render = (ROOT / "render.yaml").read_text(encoding="utf-8")
    ci = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "pip install -r requirements.lock" in render
    assert "pip install -r requirements-test.lock" in ci
    assert "cache-dependency-path: requirements-test.lock" in ci


def test_ci_test_lock_includes_runtime_lock_and_pins_pytest():
    pinned = _pinned_versions(ROOT / "requirements-test.lock")
    assert "-r requirements.lock" in (ROOT / "requirements-test.lock").read_text(encoding="utf-8")
    assert "pytest" in pinned
