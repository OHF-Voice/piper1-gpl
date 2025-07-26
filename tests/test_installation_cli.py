
import os
import subprocess
import pytest
from pathlib import Path

def test_cli_synthesis():
    """
    Tests that the Piper CLI can be invoked and used for speech synthesis.
    """
    try:
        # Assuming a default voice model is available or can be downloaded
        # For a real test, you might want to ensure a specific voice is present
        # or download one as part of the test setup.
        # FYI: Downloaded voice models are typically located in ~/.cache/piper/
        command = [
            "python3",
            "-m",
            "piper",
            "--model", "en_US-lessac-medium", # Using a common English model
            "--output-raw",
            "-",
            "--data-dir", str(Path.home() / ".cache" / "piper"),
            "--",
            "Hello, this is a CLI test."
        ]
        
        # Run the command and capture its output
        result = subprocess.run(command, capture_output=True, text=False, check=True)

        # Check for successful execution (exit code 0)
        assert result.returncode == 0, f"CLI command failed with error: {result.stderr.decode()}"
        
        # Check if any audio data was produced (raw output should not be empty)
        assert len(result.stdout) > 0, "CLI produced no audio output"

    except subprocess.CalledProcessError as e:
        pytest.fail(f"CLI test failed: {e.stderr.decode()}")
    except FileNotFoundError:
        pytest.fail("Python or piper command not found. Ensure piper is installed and in PATH.")
    except Exception as e:
        pytest.fail(f"An unexpected error occurred during CLI test: {e}")
