"""
OpenClaw Sandbox RPG - Backend
================================
Main FastAPI application entry point.
"""
__version__ = "0.1.0"

import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Ensure environment variables from .env are loaded before any other submodules import os.getenv
# Skip loading .env when running under pytest to prevent env pollution in tests
if "pytest" not in sys.modules:
    _env_path = Path(__file__).resolve().parent / ".env"
    if _env_path.exists():
        load_dotenv(dotenv_path=_env_path)
    else:
        _root_env_path = Path(__file__).resolve().parent.parent / ".env"
        if _root_env_path.exists():
            load_dotenv(dotenv_path=_root_env_path)

