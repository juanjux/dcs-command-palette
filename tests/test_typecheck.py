import subprocess
import sys
import os


def test_mypy_typecheck() -> None:
    """Run mypy on all source files to verify type correctness."""
    project_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    source_files = [
        os.path.join(project_dir, "src", "config", "settings.py"),
        os.path.join(project_dir, "src", "bios", "controls.py"),
        os.path.join(project_dir, "src", "bios", "sender.py"),
        os.path.join(project_dir, "src", "palette", "usage.py"),
        os.path.join(project_dir, "src", "lib", "search.py"),
    ]
    result = subprocess.run(
        [sys.executable, "-m", "mypy", "--config-file", os.path.join(project_dir, "pyproject.toml")]
        + source_files,
        capture_output=True,
        text=True,
        cwd=project_dir,
    )
    assert result.returncode == 0, (
        f"mypy failed with:\n{result.stdout}\n{result.stderr}"
    )
