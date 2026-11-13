"""Source code of sofibot-mcp.exe (this is NOT the program: build-exe.ps1 builds it into dist\): both Sofibot MCP servers in one Windows program, no Python needed.

    sofibot-mcp.exe              (double click) connect Claude and Codex automatically (sofibot_instalar.py)
    sofibot-mcp.exe informes     functionality 1, writing reports (sofibot_informes_mcp.py)
    sofibot-mcp.exe consultas    functionality 2, data queries (sofibot_consultas_mcp.py)

Claude and Codex start it with "informes" or "consultas". Same code and settings as the Python
scripts (environment variables of sofibot_entra.py). Built with build-exe.ps1.
"""
import sys


def main() -> int:
    which = sys.argv[1] if len(sys.argv) > 1 else "instalar"
    if which == "informes":
        import sofibot_informes_mcp as server
    elif which == "consultas":
        import sofibot_consultas_mcp as server
    elif which == "instalar":
        import sofibot_instalar

        return sofibot_instalar.main()
    elif which == "comprobar":
        # build-exe.ps1 runs this: a Python whose OpenSSL does not survive packaging fails here.
        import ssl

        import certifi

        ssl.create_default_context(cafile=certifi.where())
        print("sofibot-mcp.exe: OK")
        return 0
    else:
        print("Uso: sofibot-mcp.exe [instalar | informes | consultas]", file=sys.stderr)
        return 2
    server.mcp.run(transport="stdio")
    return 0


if __name__ == "__main__":
    sys.exit(main())
