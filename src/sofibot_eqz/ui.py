"""Shared look of the portal pages: header, navigation by role and the Datasofi style."""
from html import escape

from fastapi import Request
from fastapi.responses import HTMLResponse

from . import auth
from .identity import ROLE_ADMIN, ROLE_REVIEWER, Identity, from_session


def user(request: Request) -> Identity | None:
    """The signed-in Entra ID user, or None when the portal has no per-user sign-in."""
    current = auth.current_user(request)
    return None if current is None else from_session(current)


def page(request: Request, title: str, body: str, *, active: str = "", status: int = 200) -> HTMLResponse:
    who = user(request)
    links = [("explore", "/explore", "Explorar"), ("informes", "/informes", "Informes"),
             ("consultas", "/consultas", "Consultas"), ("conectar", "/conectar", "Conectar tu IA")]
    if who is not None and ROLE_REVIEWER in who.roles:
        links.append(("revision", "/revision", "Revisión"))
    if who is not None and ROLE_ADMIN in who.roles:
        links.append(("admin", "/admin", "Administración"))
    nav = "".join(f'<a href="{href}"{" aria-current=page" if key == active else ""}>{label}</a>'
                  for key, href, label in links)
    account = ""
    if who is not None:
        account = (f'<span class="who">{escape(who.name or who.email)}</span>'
                   '<a href="/auth/logout">Cerrar sesión</a>')
    html = (SHELL.replace("{title}", escape(title)).replace("{nav}", nav).replace("{account}", account)
            .replace("{body}", body))
    return HTMLResponse(html, status)


def notice(text: str) -> str:
    return f'<p class="notice">{escape(text)}</p>'


STYLE = """
:root{--blue:#2C3968;--orange:#D16B1B;--cyan:#279CDB;--teal:#5DAEAB;--line:#dfe5ee;--soft:#566173;--bg:#f4f7fb}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--blue);font:15px/1.55 Roboto,Arial,sans-serif}
header{background:var(--blue);color:#fff;padding:12px 24px;display:flex;flex-wrap:wrap;gap:8px 20px;align-items:center}
header .brand{font-size:19px;font-weight:500;margin-right:12px;color:#fff;text-decoration:none}
header nav{display:flex;flex-wrap:wrap;gap:4px;flex:1}header nav a,header .account a{color:#fff;text-decoration:none;padding:6px 10px;border-radius:8px}
header nav a[aria-current]{background:rgba(255,255,255,.16)}header nav a:hover,header .account a:hover{background:rgba(255,255,255,.1)}
header .account{display:flex;gap:8px;align-items:center;font-size:14px}.who{opacity:.85}
main{max-width:1120px;margin:auto;padding:24px 16px 48px}h1{font-size:24px;margin:4px 0 8px}h2{font-size:18px;margin:28px 0 10px}
h3{font-size:16px;margin:18px 0 6px}p{margin:6px 0 10px}.meta{color:var(--soft);font-size:13px}
.cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:16px}
.card{background:#fff;border:1px solid var(--line);border-top:4px solid var(--orange);border-radius:14px;padding:20px}
.card.big{border-top-width:6px;padding:26px}.card h2,.card h3{margin-top:0}.card.off{border-top-color:var(--line);opacity:.8}
.actions{display:flex;flex-wrap:wrap;gap:8px;margin-top:12px;align-items:center}
a.button,button{font:inherit;font-weight:500;padding:8px 14px;border:1px solid var(--line);border-radius:8px;background:#fff;color:var(--blue);cursor:pointer;text-decoration:none;display:inline-block}
a.button.primary,button.primary{background:var(--blue);border-color:var(--blue);color:#fff}
table{width:100%;border-collapse:collapse;background:#fff;border:1px solid var(--line);font-size:14px}
th,td{text-align:left;padding:7px 10px;border-bottom:1px solid var(--line);vertical-align:top}th{background:#f8fafd}
td.num{text-align:right;font-variant-numeric:tabular-nums}.scroll{overflow-x:auto}
pre{background:#fff;border:1px solid var(--line);border-radius:8px;padding:12px;overflow:auto;font-size:13px;max-height:520px}
code{background:#eef2f8;border-radius:4px;padding:1px 4px;font-size:90%}pre code{background:none;padding:0}
.notice{background:#fff;border-left:4px solid var(--orange);padding:8px 12px}
.ok{color:#2e7d4f;font-weight:500}.bad{color:#b3261e;font-weight:500}.warn{color:var(--orange);font-weight:500}
.tag{display:inline-block;font-size:12px;padding:1px 8px;border-radius:10px;background:#eef2f8;margin-left:6px}
.tag.mine{background:var(--teal);color:#fff}
form.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:12px;background:#fff;border:1px solid var(--line);border-radius:12px;padding:16px}
fieldset{border:1px solid var(--line);border-radius:8px;padding:8px 10px;margin:0}legend{font-size:13px;color:var(--soft)}
label{display:block;font-size:14px}select,input[type=text],input[type=month],input[type=number]{font:inherit;width:100%;padding:6px 8px;border:1px solid var(--line);border-radius:8px;background:#fff}
.doc{background:#fff;border:1px solid var(--line);border-radius:12px;padding:8px 28px 24px}.doc table{font-size:13px}
.doc h1{font-size:24px;margin-top:18px}.doc h2{border-bottom:1px solid var(--line);padding-bottom:4px}
details{background:#fff;border:1px solid var(--line);border-radius:10px;padding:10px 14px;margin:12px 0}
summary{cursor:pointer;font-weight:500}h4{font-size:14px;margin:14px 0 4px}
a:focus-visible,button:focus-visible,input:focus-visible,select:focus-visible{outline:3px solid var(--orange);outline-offset:2px}
"""

SHELL = """<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{title} · Sofibot</title><style>""" + STYLE + """</style></head>
<body><header><a class="brand" href="/explore">Sofibot</a><nav>{nav}</nav><div class="account">{account}</div></header>
<main>{body}</main></body></html>"""
