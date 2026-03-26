"""Smoke test: verify the app can start and stop without crashing."""
import os
import subprocess
import sys
import time


def test_app_starts_and_stops() -> None:
    """Launch the palette, let it initialize, then signal it to stop."""
    project_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    main_py = os.path.join(project_dir, "main.py")
    shutdown_file = os.path.join(project_dir, ".shutdown")

    # Clean up any leftover shutdown file
    try:
        os.remove(shutdown_file)
    except FileNotFoundError:
        pass

    # Launch the app
    proc = subprocess.Popen(
        [sys.executable, main_py, "--aircraft", "FA-18C_hornet"],
        cwd=project_dir,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    try:
        # Give it time to start up
        time.sleep(3)

        # It should still be running
        assert proc.poll() is None, (
            f"App exited prematurely with code {proc.returncode}\n"
            f"stderr: {proc.stderr.read().decode() if proc.stderr else ''}"
        )

        # Signal shutdown via the .shutdown file (same as the Lua hook)
        with open(shutdown_file, "w") as f:
            f.write("stop")

        # Wait for clean exit
        proc.wait(timeout=10)
        assert proc.returncode == 0, f"App exited with code {proc.returncode}"

    finally:
        if proc.poll() is None:
            proc.terminate()
            proc.wait(timeout=5)
        try:
            os.remove(shutdown_file)
        except FileNotFoundError:
            pass
