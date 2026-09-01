"""Keep the runtime requirements honest.

Splitting dev tooling out of requirements.txt introduces one dangerous failure
mode: something under src/ imports a package that only the dev file installs.
Every local run still passes, because the dev environment has both files, and
the deployment fails on an ImportError nothing caught. These tests compare what
src/ actually imports against what the deployed file installs.
"""

from __future__ import annotations

import ast
import re
import sys
from importlib.metadata import packages_distributions
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "pitch_analyzer"
RUNTIME_REQS = ROOT / "requirements.txt"
DEV_REQS = ROOT / "requirements-dev.txt"

#: Test-only, and specifically checked for: reportlab used to sit in the
#: runtime set even though only the suite and samples/ import it.
DEV_ONLY = {"pytest", "reportlab"}


def normalize(name: str) -> str:
    """PEP 503 normalization, so python_dotenv and python-dotenv compare equal."""
    return re.sub(r"[-_.]+", "-", name).lower()


def parse_requirements(path: Path) -> set[str]:
    """Distribution names declared directly in one requirements file."""
    names = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if not line or line.startswith("-"):  # blank, comment, or -r include
            continue
        name = re.split(r"[<>=!~\[;]", line, maxsplit=1)[0].strip()
        if name:
            names.add(normalize(name))
    return names


def imported_modules() -> dict[str, set[Path]]:
    """Top-level module name -> the files importing it, across all of src/.

    Walks the whole tree rather than module-level statements only: the
    anthropic client is imported inside functions, and a missing lazy import is
    still a production failure — just a later one.
    """
    found: dict[str, set[Path]] = {}
    for path in SRC.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                roots = [alias.name.split(".")[0] for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                # level > 0 is a relative import: first-party by definition.
                roots = [node.module.split(".")[0]] if node.level == 0 and node.module else []
            else:
                continue
            for root in roots:
                found.setdefault(root, set()).add(path.relative_to(ROOT))
    return found


def third_party_imports() -> dict[str, set[Path]]:
    return {
        module: files
        for module, files in imported_modules().items()
        if module not in sys.stdlib_module_names and module != "pitch_analyzer"
    }


def test_every_import_in_src_is_a_runtime_dependency() -> None:
    runtime = parse_requirements(RUNTIME_REQS)
    module_to_dists = packages_distributions()

    missing: list[str] = []
    for module, files in sorted(third_party_imports().items()):
        distributions = module_to_dists.get(module)
        assert distributions, (
            f"cannot resolve which distribution provides {module!r} "
            f"(imported by {', '.join(str(f) for f in sorted(files))}); "
            "is the test environment fully installed?"
        )
        if not any(normalize(dist) in runtime for dist in distributions):
            where = ", ".join(str(f) for f in sorted(files))
            missing.append(f"{module} (from {'/'.join(distributions)}) in {where}")

    assert not missing, (
        "imported by src/ but not installed by requirements.txt, so the "
        "deployment would fail on import:\n  " + "\n  ".join(missing)
    )


def test_dev_only_packages_stay_out_of_the_runtime_file() -> None:
    runtime = parse_requirements(RUNTIME_REQS)
    leaked = sorted(DEV_ONLY & runtime)
    assert not leaked, (
        f"{leaked} are test-only and would ship in the deployed image; "
        "declare them in requirements-dev.txt instead."
    )


def test_dev_requirements_install_the_runtime_set_too() -> None:
    """`pip install -r requirements-dev.txt` has to be enough on its own."""
    text = DEV_REQS.read_text(encoding="utf-8")
    assert "-r requirements.txt" in text
    assert DEV_ONLY <= parse_requirements(DEV_REQS)


def test_reportlab_is_still_needed_by_the_tests() -> None:
    """It is a dev dependency, not dead weight — if that stops being true it
    should be dropped entirely rather than left in the dev file."""
    users = [
        path.relative_to(ROOT)
        for path in [*(ROOT / "tests").rglob("*.py"), *(ROOT / "samples").rglob("*.py")]
        if "reportlab" in path.read_text(encoding="utf-8")
    ]
    assert users, "nothing imports reportlab any more; remove it from requirements-dev.txt"
