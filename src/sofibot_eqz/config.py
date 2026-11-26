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
# Who may do what (access.py): usuarios.json (user -> roles) and permisos.json (role -> Gold tables).
# Entra ID only signs users in; the roles are managed here (docs/09-inicio-sesion-entra.md).
ACCESS_DIR = Path(os.environ.get("SOFIBOT_ACCESS_DIR", HOME / "acceso")).resolve()
# Shipped in the image next to the code: the technical documentation shown to administrators
# and the MCP servers users download (in a checkout, the repository's own folders).
DOCS_DIR = Path(os.environ.get("SOFIBOT_DOCS_DIR", HOME / "docs")).resolve()
MCP_DIR = Path(os.environ.get("SOFIBOT_MCP_DIR", HOME / "mcp-server")).resolve()
# Report code written through the API (drafts.py) until a person publishes it into reports/.
DRAFTS_DIR = Path(os.environ.get("SOFIBOT_DRAFTS_DIR", REPORTS_DIR / ".borradores")).resolve()
BUILD_TIMEOUT = int(os.environ.get("SOFIBOT_BUILD_TIMEOUT", "900"))
