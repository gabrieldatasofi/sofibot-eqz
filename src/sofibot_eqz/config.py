"""Folders and the .env file. In Docker SOFIBOT_HOME is /app; locally, the folder you run from."""
import os
from pathlib import Path

from dotenv import load_dotenv

HOME = Path(os.environ.get("SOFIBOT_HOME", Path.cwd())).resolve()
# Variables already set (Docker env_file, the shell) win over the file.
load_dotenv(HOME / ".env", override=False)

REPORTS_DIR = Path(os.environ.get("SOFIBOT_REPORTS_DIR", HOME / "reports")).resolve()
OUTPUT_DIR = Path(os.environ.get("SOFIBOT_OUTPUT_DIR", HOME / "output")).resolve()
SCHEMA_FILE = REPORTS_DIR / "gold_schema.json"
BUILD_TIMEOUT = int(os.environ.get("SOFIBOT_BUILD_TIMEOUT", "900"))
