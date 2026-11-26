"""Connect Claude and Codex to Sofibot in one go: what `sofibot-mcp.exe` does on a double click.

1. Reads the Sofibot settings (sofibot-conexion.json next to the program, as downloaded from
   the portal's "Conectar tu IA" page, or asks for the portal's address).
2. Shows what it will do; the user can see every detail before accepting.
3. Copies the program to %LOCALAPPDATA%\\Sofibot.
4. Signs the user in with Microsoft and asks Sofibot which connectors they may use.
5. Finds Claude Desktop, Claude Code and Codex and adds the connectors to their configuration
   files, keeping a copy of each file first.

Writes nothing but those configuration files and the program's folder; never sees data.
"""
from datetime import datetime
import json
import os
from pathlib import Path
import re
import shutil
import sys

CONFIG_NAME = "sofibot-conexion.json"
MARK_START, MARK_END = "# >>> Sofibot (sofibot-mcp.exe) >>>", "# <<< Sofibot <<<"
NAMES = {"informes": "sofibot-informes", "consultas": "sofibot-consultas"}
LINKS = {"Claude Desktop": "https://claude.ai/download",
         "Claude Code": "https://docs.anthropic.com/en/docs/claude-code/setup",
         "Codex": "https://github.com/openai/codex"}


# --- Pure functions (tested) --------------------------------------------------------------

def entries(settings: dict, exe: str, modes: list[str], ai: str) -> dict[str, dict]:
    """MCP server definitions for the given connectors, in the format of Claude's JSON files."""
    found = {}
    for mode in modes:
        url = settings["url"] if mode == "informes" else settings.get("query_url") or settings["url"]
        found[NAMES[mode]] = {"command": exe, "args": [mode], "env": {
            "SOFIBOT_URL": url, "SOFIBOT_ENTRA_TENANT_ID": settings["tenant_id"],
            "SOFIBOT_ENTRA_CLIENT_ID": settings["client_id"], "SOFIBOT_AI": ai}}
    return found


def merge_json(text: str, servers: dict) -> str:
    """Claude Desktop (claude_desktop_config.json) or Claude Code (~/.claude.json): mcpServers updated."""
    data = json.loads(text) if text.strip() else {}
    if not isinstance(data, dict):
        raise ValueError("the file is not a JSON object")
    current = data.get("mcpServers")
    data["mcpServers"] = {**(current if isinstance(current, dict) else {}), **servers}
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def merge_toml(text: str, servers: dict) -> str:
    """Codex (config.toml): replaces Sofibot's block and any earlier [mcp_servers.sofibot_*] tables."""
    lines, kept, skipping, inside = text.splitlines(), [], False, False
    ours = re.compile(r"^\s*\[mcp_servers\.(sofibot_informes|sofibot_consultas)(\.env)?\]\s*$")
    for line in lines:
        if line.strip() == MARK_START:
            inside = True
            continue
        if line.strip() == MARK_END:
            inside = False
            continue
        if inside:
            continue
        if re.match(r"^\s*\[", line):
            skipping = bool(ours.match(line))
        if not skipping:
            kept.append(line)
    while kept and not kept[-1].strip():
        kept.pop()
    block = [MARK_START]
    for name, server in servers.items():
        table = name.replace("-", "_")
        args = ", ".join(f"'{a}'" for a in server["args"])
        block += [f"[mcp_servers.{table}]", f"command = '{server['command']}'", f"args = [{args}]",
                  "startup_timeout_sec = 30", "tool_timeout_sec = 120", f"[mcp_servers.{table}.env]"]
        block += [f'{key} = "{value}"' for key, value in server["env"].items()]
    block.append(MARK_END)
    return "\n".join(kept + ([""] if kept else []) + block) + "\n"


# --- Where each AI keeps its configuration ------------------------------------------------

def targets() -> list[tuple[str, Path, str]]:
    """(AI, configuration file, format) for the AIs installed on this computer."""
    home = Path.home()
    appdata = Path(os.environ.get("APPDATA", home / "AppData" / "Roaming"))
    local = Path(os.environ.get("LOCALAPPDATA", home / "AppData" / "Local"))
    found = []
    desktop = [appdata / "Claude", *sorted(local.glob("Packages/Claude_*/LocalCache/Roaming/Claude"))]
    for folder in desktop:
        if folder.is_dir():
            found.append(("Claude Desktop", folder / "claude_desktop_config.json", "json"))
    if (home / ".claude.json").is_file() or shutil.which("claude"):
        found.append(("Claude Code", home / ".claude.json", "json"))
    codex_home = Path(os.environ.get("CODEX_HOME", home / ".codex"))
    if codex_home.is_dir() or shutil.which("codex"):
        found.append(("Codex", codex_home / "config.toml", "toml"))
    return found


def write_config(path: Path, kind: str, servers: dict) -> Path | None:
    """Merge the servers into the file; a copy of the previous file is kept next to it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    text = path.read_text(encoding="utf-8") if path.is_file() else ""
    backup = None
    if text:
        backup = path.with_name(f"{path.name}.antes-de-sofibot-{datetime.now():%Y%m%d-%H%M%S}")
        backup.write_text(text, encoding="utf-8")
    path.write_text(merge_json(text, servers) if kind == "json" else merge_toml(text, servers), encoding="utf-8")
    return backup


# --- The installer ------------------------------------------------------------------------

def say(text: str = "") -> None:
    print(text, flush=True)


def ask(question: str, default: str = "") -> str:
    answer = input(f"{question}{f' [{default}]' if default else ''}: ").strip()
    return answer or default


def program_dir() -> Path:
    return Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).parent


def load_settings() -> dict:
    for folder in (program_dir(), Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Sofibot"):
        if (folder / CONFIG_NAME).is_file():
            return json.loads((folder / CONFIG_NAME).read_text(encoding="utf-8"))
    import httpx

    url = ask("Dirección de Sofibot (la del navegador, por ejemplo https://informes.empresa.local)").rstrip("/")
    response = httpx.get(f"{url}/conexion.json", timeout=20, verify=os.environ.get("SOFIBOT_CA_BUNDLE") or True)
    response.raise_for_status()
    return response.json()


def plan(settings: dict, found) -> str:
    folder = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Sofibot"
    steps = [f"Copiar este programa a {folder}",
             "Abrir el navegador para que inicies sesión con tu cuenta de Microsoft",
             "Preguntar a Sofibot qué conectores puedes usar según tus roles"]
    steps += [f"Añadir los conectores a {ai}: {path} (guardando antes una copia)" for ai, path, _ in found]
    return "\n".join(f"  {i}. {step}" for i, step in enumerate(steps, 1))


def run() -> int:
    say("=" * 70)
    say("  Sofibot · conectar tu IA (Claude o Codex)")
    say("=" * 70)
    settings = load_settings()
    say(f"\nSofibot: {settings['url']}")
    found = targets()
    if not found:
        say("\nNo encuentro Claude ni Codex en este equipo. Instala uno de ellos y vuelve a abrir este programa:")
        for ai, link in LINKS.items():
            say(f"  - {ai}: {link}")
        return 1
    say(f"IAs encontradas: {', '.join(ai for ai, _, _ in found)}")
    say(f"\nVoy a hacer esto:\n{plan(settings, found)}")
    while True:
        choice = ask("\nPulsa Enter para continuar, D para ver los detalles o C para cancelar").lower()
        if choice == "c":
            say("Cancelado: no se ha cambiado nada.")
            return 1
        if choice == "d":
            preview = entries(settings, str(Path(os.environ.get("LOCALAPPDATA", "")) / "Sofibot" / "sofibot-mcp.exe"),
                              ["informes", "consultas"], "claude")
            say("\nEsto es lo que se añade a cada fichero (solo direcciones e identificadores públicos, sin contraseñas):")
            say(json.dumps({"mcpServers": preview}, indent=2, ensure_ascii=False))
            say("En Codex, lo mismo en formato TOML, entre las líneas '# >>> Sofibot' y '# <<< Sofibot'.")
            continue
        break

    folder = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Sofibot"
    folder.mkdir(parents=True, exist_ok=True)
    exe = folder / "sofibot-mcp.exe"
    if getattr(sys, "frozen", False) and Path(sys.executable).resolve() != exe.resolve():
        shutil.copyfile(sys.executable, exe)
    (folder / CONFIG_NAME).write_text(json.dumps(settings, indent=2), encoding="utf-8")
    say(f"\n1. Programa copiado a {exe}")

    import sofibot_entra

    os.environ.update({"SOFIBOT_ENTRA_TENANT_ID": settings["tenant_id"],
                       "SOFIBOT_ENTRA_CLIENT_ID": settings["client_id"]})
    say("2. Inicia sesión en la ventana del navegador que se abre…")
    modes = []
    for mode, path in (("informes", "/api/code/schema"), ("consultas", "/api/query/catalog")):
        if not settings.get(mode):
            continue
        os.environ["SOFIBOT_URL"] = entries(settings, "", [mode], "")[NAMES[mode]]["env"]["SOFIBOT_URL"]
        result = sofibot_entra.call("GET", path)
        if "error" not in result:
            tables = len(result.get("tables", {}))
            say(f"3. {'Crear informes' if mode == 'informes' else 'Consultas'}: disponible ({tables} tablas)")
            modes.append(mode)
        else:
            say(f"3. {'Crear informes' if mode == 'informes' else 'Consultas'}: no disponible ({result['error']})")
    if not modes:
        say("\nTu usuario no puede usar ningún conector: pide a un administrador de Sofibot el rol Sofibot.Autor o Sofibot.Consultas.")
        return 1

    for ai, path, kind in found:
        servers = entries(settings, str(exe), modes, "codex" if ai == "Codex" else "claude")
        try:
            backup = write_config(path, kind, servers)
            say(f"4. {ai}: conectado ({path}){f'; copia anterior en {backup.name}' if backup else ''}")
        except (OSError, ValueError) as exc:
            say(f"4. {ai}: no se ha podido configurar ({exc}). Usa la configuración manual de la página.")
    say("\nListo. Cierra y vuelve a abrir Claude o Codex para que cargue los conectores.")
    say("Prueba a preguntarle: «¿Qué puedo consultar en Sofibot?»")
    return 0


def main() -> int:
    try:
        code = run()
    except KeyboardInterrupt:
        code = 1
    except Exception as exc:  # shown to the person at the keyboard; no secrets involved
        say(f"\nNo se ha podido terminar: {exc}")
        code = 1
    if getattr(sys, "frozen", False):
        input("\nPulsa Enter para cerrar esta ventana.")
    return code
