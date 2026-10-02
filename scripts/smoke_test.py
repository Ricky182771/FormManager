"""HTTP smoke test through the public entrypoint (stdlib only).

Checks /health, /, security headers, admin login, dashboard and logout.
"""

from __future__ import annotations

import http.cookiejar
import json
import os
import re
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request

BASE = os.environ["BASE_URL"].rstrip("/")
ctx = ssl.create_default_context()
if os.environ.get("CURL_INSECURE") == "1":
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

jar = http.cookiejar.CookieJar()


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        return None


opener = urllib.request.build_opener(
    urllib.request.HTTPCookieProcessor(jar), urllib.request.HTTPSHandler(context=ctx), NoRedirect()
)
failures: list[str] = []


def call(method: str, path: str, data: dict[str, str] | None = None) -> tuple[int, dict, str]:
    body = urllib.parse.urlencode(data).encode() if data is not None else None
    headers = {"Origin": BASE}
    if body is not None:
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    # BASE comes from the operator's environment and is always http(s).
    url = BASE + path
    req = urllib.request.Request(url, data=body, method=method, headers=headers)  # noqa: S310
    try:
        with opener.open(req, timeout=15) as res:
            return res.status, {k.lower(): v for k, v in res.headers.items()}, res.read().decode()
    except urllib.error.HTTPError as err:
        return err.code, {k.lower(): v for k, v in err.headers.items()}, err.read().decode()


def check(label: str, ok: bool, detail: str = "") -> None:
    print(("PASS " if ok else "FAIL ") + label + (f"  [{detail}]" if detail and not ok else ""))
    if not ok:
        failures.append(label)


def csrf_field(html: str) -> str:
    m = re.search(r'name="csrf_token" value="([^"]+)"', html)
    return m.group(1) if m else ""


status, hdr, body = call("GET", "/health")
check("/health -> 200 ok", status == 200 and json.loads(body)["status"] == "ok", body)
check("HSTS header over HTTPS", "max-age" in hdr.get("strict-transport-security", ""))

status, hdr, body = call("GET", "/")
check("/ -> 200", status == 200, str(status))
check("/ reports core running", "En ejecución" in body)
check("/ reports database healthy", "Saludable" in body)
check(
    "/ reports 0 forms loaded", re.search(r"Formularios cargados</dt>\s*<dd>0<", body) is not None
)
check("CSP header", "frame-ancestors 'none'" in hdr.get("content-security-policy", ""))
check("nosniff header", hdr.get("x-content-type-options") == "nosniff")
check("no Server header", "server" not in hdr, hdr.get("server", ""))
check("no CORS header", "access-control-allow-origin" not in hdr)

status, _, body = call("GET", "/admin/login")
check("admin login page -> 200", status == 200, str(status))
status, _, _ = call(
    "POST",
    "/admin/login",
    {
        "username": os.environ["ADMIN_USER"],
        "password": os.environ["ADMIN_PASS"],
        "csrf_token": csrf_field(body),
    },
)
check("admin login -> 303", status == 303, str(status))
status, _, body = call("GET", "/admin")
check("admin dashboard -> 200", status == 200 and "FormManager Admin" in body, str(status))
status, _, _ = call("POST", "/admin/logout", {"csrf_token": csrf_field(body)})
check("admin logout -> 303", status == 303, str(status))
status, _, _ = call("GET", "/admin")
check("dashboard after logout -> 303", status == 303, str(status))

print(f"\n{len(failures)} fallo(s)")
sys.exit(1 if failures else 0)
