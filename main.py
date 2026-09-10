#!/usr/bin/env python3
"""Convenience top-level entrypoint for Bulk Data Acquisition Pipeline.

Auto-bootstraps into the project's virtual environment if invoked via system python.
"""

import os
import sys
from pathlib import Path

# Auto-re-execute inside project .venv to guarantee all packages are available
venv_python = Path(__file__).resolve().parent / ".venv" / "bin" / "python"
if venv_python.exists() and sys.executable != str(venv_python):
    os.execv(str(venv_python), [str(venv_python)] + sys.argv)

from crawler.pipeline import main

if __name__ == "__main__":
    main()
