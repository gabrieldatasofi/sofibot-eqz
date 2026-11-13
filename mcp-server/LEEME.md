# Conectores MCP de Sofibot

Dos conectores para usar Sofibot desde Claude (Claude Code, Claude Desktop) o Codex:

| Fichero | Funcionalidad | Qué recibe tu IA |
|---|---|---|
| `sofibot_informes_mcp.py` | Crear informes (rol `Sofibot.Autor`) | Solo la estructura de tus tablas. Nunca datos |
| `sofibot_consultas_mcp.py` | Consultar datos (rol `Sofibot.Consultas`) | Los datos que consultas, con tus permisos |
| `sofibot_entra.py` | Inicio de sesión con tu cuenta de Microsoft, común a los dos | — |

## Sin Python: `sofibot-mcp.exe`

Lo más sencillo: en la página **Conectar tu IA** de Sofibot, **Descargar el conector**,
extraer el zip y hacer doble clic en **sofibot-mcp.exe**. Configura solo Claude Desktop,
Claude Code y Codex (`sofibot_instalar.py`), sin Python. Claude y Codex lo arrancan después
como `sofibot-mcp.exe informes` y `sofibot-mcp.exe consultas`. Datasofi lo genera con
`build-exe.ps1`. Estos ficheros son la alternativa en Python.

## Instalación con Python (una vez)

1. Python 3.12. Descomprimir esta carpeta en `C:\sofibot-mcp`.
2. En esa carpeta:

   ```
   python -m venv .venv
   .venv\Scripts\pip install -r requirements.txt
   ```

3. Copiar en tu IA la configuración de la página **Conectar tu IA** de Sofibot (ya trae la
   dirección de Sofibot y los ids de Microsoft) y reiniciarla.

La primera vez que tu IA use Sofibot se abrirá el navegador para iniciar sesión con tu cuenta
de la empresa. La sesión se guarda en `%USERPROFILE%\.sofibot\` y no vuelve a pedirse hasta
que caduque.

## Importante

- Los datos que devuelve el conector de consultas son de la empresa y llegan al proveedor de
  la IA que usas: úsalo solo con la cuenta de IA que la empresa haya autorizado.
- Sofibot registra quién consulta qué (nunca los valores devueltos).
