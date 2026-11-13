"""The connector installer (mcp-server/sofibot_instalar.py): merging Claude and Codex configuration files."""
import json
from pathlib import Path
import sys
import tomllib

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "mcp-server"))
import sofibot_instalar as installer  # noqa: E402

SETTINGS = {"url": "https://informes.test", "tenant_id": "t-1", "client_id": "c-1", "query_url": "https://q.test"}
EXE = r"C:\Users\ana\AppData\Local\Sofibot\sofibot-mcp.exe"


def test_entries_per_connector():
    servers = installer.entries(SETTINGS, EXE, ["informes", "consultas"], "claude")
    assert servers["sofibot-informes"]["args"] == ["informes"]
    assert servers["sofibot-informes"]["env"]["SOFIBOT_URL"] == "https://informes.test"
    assert servers["sofibot-consultas"]["env"]["SOFIBOT_URL"] == "https://q.test"


def test_claude_json_keeps_everything_else():
    before = json.dumps({"theme": "dark", "mcpServers": {"otro": {"command": "x"}, "sofibot-informes": {"command": "viejo"}}})
    after = json.loads(installer.merge_json(before, installer.entries(SETTINGS, EXE, ["informes"], "claude")))
    assert after["theme"] == "dark" and after["mcpServers"]["otro"] == {"command": "x"}
    assert after["mcpServers"]["sofibot-informes"]["command"] == EXE
    assert json.loads(installer.merge_json("", {}))["mcpServers"] == {}


def test_codex_toml_is_valid_and_replaces_earlier_entries():
    before = ('model = "o4"\n\n[mcp_servers.otro]\ncommand = "x"\n\n'
              "[mcp_servers.sofibot_informes]\ncommand = 'viejo'\n[mcp_servers.sofibot_informes.env]\nA = \"1\"\n")
    servers = installer.entries(SETTINGS, EXE, ["informes", "consultas"], "codex")
    once = installer.merge_toml(before, servers)
    twice = installer.merge_toml(once, servers)
    assert once == twice                                   # running it again changes nothing
    data = tomllib.loads(twice)
    assert data["model"] == "o4" and data["mcp_servers"]["otro"] == {"command": "x"}
    assert data["mcp_servers"]["sofibot_informes"]["command"] == EXE
    assert data["mcp_servers"]["sofibot_consultas"]["env"]["SOFIBOT_AI"] == "codex"
    assert "viejo" not in twice


def test_write_config_keeps_a_copy(tmp_path):
    path = tmp_path / "claude_desktop_config.json"
    path.write_text('{"mcpServers": {}}')
    backup = installer.write_config(path, "json", installer.entries(SETTINGS, EXE, ["consultas"], "claude"))
    assert backup is not None and backup.read_text() == '{"mcpServers": {}}'
    assert "sofibot-consultas" in json.loads(path.read_text())["mcpServers"]
    assert installer.write_config(tmp_path / "nuevo" / "config.toml", "toml", {}) is None
