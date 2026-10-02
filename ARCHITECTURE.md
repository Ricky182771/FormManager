# FormManager: arquitectura (Hito 0)

Este documento describe **lo que existe** tras el Hito 0. Los principios y el diseño futuro están en `PROJECT_RULES.md` y `REBASE.md`; aquí no se repiten.

## Despliegue

```text
Internet
   │ 80/443 (único punto publicado)
   ▼
 Caddy ── red edge (con salida a Internet, ACME)
   │ red proxy (internal: true)
   ▼
 FormManager Core (FastAPI, 1 worker, uid 10001, rootfs read-only)
   │ red backend (internal: true)
   ▼
 PostgreSQL 16 (sin puertos publicados)
```

Volúmenes: `postgres_data` (db), `forms_data` → `/data/forms` (app, único mount escribible además de `/tmp` tmpfs), `caddy_data`, `caddy_config`.

## Filesystem vs PostgreSQL

| Almacén | Hito 0 |
|---|---|
| Filesystem (`FORMS_DIR`) | Se crea o se comprueba al arrancar (existe, es directorio, no es symlink, legible y escribible). **Nunca se lista ni se lee.** |
| PostgreSQL | `admin_sessions`, `admin_audit_log`, `alembic_version`. |

No hay tablas de formularios, submissions, reservations, resources ni versiones. Llegarán en su hito con su propia migración.

## Módulos

```text
app/
├── main.py            create_app(): servicios, middleware, routers, manejadores de error
├── config.py          Settings de instancia (pydantic-settings). Nada por formulario.
├── storage.py         prepare_forms_dir(); FORMS_LOADED = 0 (no hay Form Loader)
├── web.py             contenedor Services, dependencia de sesión DB, plantillas Jinja2
├── logging_setup.py   JSON por línea, allowlist de extras + denylist de claves sensibles
├── middleware.py      cabeceras/CSP, límite de body, log de peticiones, sobre de error JSON
├── wait_for_db.py     espera con backoff exponencial y deadline
├── db/                Base con naming convention; engine con timeouts; ping
├── models/            AdminSession, AdminAuditLog
├── routes/            health (/health), public (/), admin (/admin/*)
├── security/          passwords (Argon2id), csrf, sessions, rate_limit, generate_hash
├── services/audit.py  AuditAction + record_audit
├── templates/         UI provisional (sin JavaScript)
└── static/css/        CSS provisional
```

## Arranque

```text
python -m app.wait_for_db     (backoff 0.5s → 5s, deadline 90s)
alembic upgrade head
create_app(): prepare_forms_dir(FORMS_DIR)   (falla el arranque si no es usable)
uvicorn --workers 1 --proxy-headers
```

No hay seed: no existen datos genéricos que inicializar.

## HTTP

| Ruta | Descripción |
|---|---|
| `GET /health` | `{"status":"ok","database":"ok"}` o `503` con `unavailable`. Sin datos sensibles. |
| `GET /` | Página de estado: Core, base de datos, formularios cargados (0). |
| `GET/POST /admin/login` | Login con CSRF de cookie firmada y rate limit. |
| `POST /admin/logout` | Requiere sesión + CSRF + mismo origen. |
| `GET /admin` | Panel mínimo: estado del Core, formularios cargados, expiración de sesión. |
| `/api/v1/*` | Reservado. Sin rutas; responde errores JSON. |
| `/docs`, `/redoc`, `/openapi.json` | Deshabilitados (no hay API que documentar todavía). |

### Errores

Rutas bajo `/api/` (y el middleware de tamaño) devuelven:

```json
{"error": {"code": "NOT_FOUND", "message": "El recurso solicitado no existe."}}
```

Códigos actuales: `BAD_REQUEST`, `UNAUTHENTICATED`, `FORBIDDEN`, `NOT_FOUND`, `METHOD_NOT_ALLOWED`, `PAYLOAD_TOO_LARGE`, `VALIDATION_ERROR` (añade `fields`, nunca los valores enviados), `RATE_LIMITED`, `INTERNAL_ERROR`, `SERVICE_UNAVAILABLE`. Las rutas HTML muestran una página de error genérica. Nunca se devuelven trazas, SQL ni DSN.

Este sobre sigue `CLAUDE.md` §69. El contrato completo de la API de formularios se definirá en su hito.

## Base de datos

- SQLAlchemy 2.x, `DeclarativeBase`, naming convention determinista (`pk_`, `uq_`, `ix_`, `fk_`, `ck_`).
- Engine: `pool_pre_ping`, `pool_recycle=1800`, `connect_timeout=5`, `application_name=formmanager`, `statement_timeout` y `lock_timeout` configurables.
- Sesiones con `expire_on_commit=False`, `autoflush=False`.
- Historia Alembic nueva desde `0001` (con downgrade).

## UI provisional

Plantillas Jinja2 con autoescape, sin JavaScript, CSS propio pequeño. Tema claro/oscuro según `prefers-color-scheme`. Es un borrador sin dirección visual (ENERGY 1 / RHYTHM 1 / MOTION 1) y **no** es una especificación de identidad. El Core no depende de ella.

## Preparado para el Hito 1

- `Settings.forms_dir` validado y montado; `prepare_forms_dir()` es el punto donde el Form Loader recibirá un directorio ya comprobado.
- `FORMS_LOADED` es el único lugar que la UI consulta para el contador; el Form Loader lo sustituirá.
- Namespace `/api/v1/` y sobre de error JSON listos.
- Naming convention y patrón de migraciones listos para las tablas de formularios.

## Diferido

| Garantía del prototipo | Hito |
|---|---|
| Validación estricta de definiciones, path traversal en `FORMS_DIR`, carga idempotente | Hito 1 (Form Loader) |
| Valor exclusivo con un único ganador, reservas, adquisición en orden determinista, rollback completo de escrituras parciales, retries 40001/40P01 | Hito de Submissions/Rules/Reservations (número por definir) |
| Esquemas estrictos de submissions (tipos manipulados, inyección por tipos) | Hito de Submissions |
| Exportación CSV con neutralización de fórmulas | Hito de exportación |
| Código de acceso por formulario, estado público firmado | Hito de acceso por formulario |
| `SITE_DIR` / página de inicio personalizada | Hito de frontends custom |
