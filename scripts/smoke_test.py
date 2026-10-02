"""HTTP smoke test through the public entrypoint (stdlib only).

Checks /health, /, security headers, the forms API, admin login, dashboard and logout.
With SMOKE_FORM_SLUG/SMOKE_FORM_ID set, also checks that synthetic form is loaded and served.
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
loaded = re.search(r"Formularios cargados</dt>\s*<dd>(\d+)<", body)
check("/ reports forms loaded", loaded is not None)
check("CSP header", "frame-ancestors 'none'" in hdr.get("content-security-policy", ""))
check("nosniff header", hdr.get("x-content-type-options") == "nosniff")
check("no Server header", "server" not in hdr, hdr.get("server", ""))
check("no CORS header", "access-control-allow-origin" not in hdr)

status, hdr, body = call("GET", "/api/v1/forms")
forms = json.loads(body).get("forms", []) if status == 200 else []
check(
    "/api/v1/forms -> 200 JSON",
    status == 200 and hdr.get("content-type", "").startswith("application/json"),
)
check(
    "/ count matches /api/v1/forms",
    loaded is not None and int(loaded.group(1)) == len(forms),
    f"{loaded.group(1) if loaded else '?'} vs {len(forms)}",
)
check(
    "/api/v1/forms sorted by slug", [f["slug"] for f in forms] == sorted(f["slug"] for f in forms)
)
check("/api/v1/forms discloses no paths", "/data/forms" not in body and "_path" not in body)

slug = os.environ.get("SMOKE_FORM_SLUG")
if slug:
    form_id = os.environ.get("SMOKE_FORM_ID", "")
    check("/ reports >= 1 form loaded", loaded is not None and int(loaded.group(1)) >= 1)
    check("synthetic form listed", any(f["slug"] == slug and f["id"] == form_id for f in forms))
    status, _, body = call("GET", "/api/v1/forms/" + slug)
    detail = json.loads(body) if status == 200 else {}
    check(
        "form metadata by slug -> 200",
        status == 200
        and detail.get("title") == "Reserva de sala"
        and detail.get("status") == "draft",
        f"{status} {body[:200]}",
    )
    check("form metadata discloses no paths", "/data/forms" not in body and "_path" not in body)

status, _, body = call("GET", "/api/v1/forms/smoke-missing-form")
check(
    "missing form -> 404 FORM_NOT_FOUND",
    status == 404 and json.loads(body)["error"]["code"] == "FORM_NOT_FOUND",
    f"{status} {body[:200]}",
)
status, _, _ = call("POST", "/api/v1/forms", {"slug": "x"})
check("no form creation endpoint", status in (403, 405), str(status))

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
admin_loaded = re.search(r"Formularios cargados</dt>\s*<dd>(\d+)<", body)
check(
    "admin shows same forms count",
    admin_loaded is not None and loaded is not None and admin_loaded.group(1) == loaded.group(1),
)
status, _, _ = call("POST", "/admin/logout", {"csrf_token": csrf_field(body)})
check("admin logout -> 303", status == 303, str(status))
status, _, _ = call("GET", "/admin")
check("dashboard after logout -> 303", status == 303, str(status))

print(f"\n{len(failures)} fallo(s)")
sys.exit(1 if failures else 0)
