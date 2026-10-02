# FormManager — Hito 0 / Core Foundation

Self-hosted, headless form engine with strict validation, reusable data resources, transactional rules, and customizable frontends.

> **Estado: Hito 0.** Este repositorio contiene solo la **fundación** del Core: infraestructura, seguridad, PostgreSQL, Docker y administración básica. **Todavía no es un motor de formularios.**

Al arrancar, FormManager muestra:

```text
FormManager
Core: en ejecución
Base de datos: saludable
Formularios cargados: 0
```

## Qué existe hoy

- App FastAPI `FormManager` con `GET /health` (ping ligero a PostgreSQL) y una página `/` de estado.
- Administración con un único admin definido por entorno: `/admin/login`, `/admin/logout`, `/admin` (panel mínimo).
- Contraseñas Argon2id, sesiones admin server-side (la DB guarda solo HMAC-SHA256 del token), CSRF, rate limiting del login, cabeceras de seguridad, CSP estricta, límite de tamaño de petición y logs JSON sin secretos.
- Auditoría genérica: `ADMIN_LOGIN`, `ADMIN_LOGIN_FAILED`, `ADMIN_LOGOUT`.
- PostgreSQL 16 con rol de aplicación de mínimo privilegio y migración Alembic `0001_initial_formmanager` (solo `admin_sessions` y `admin_audit_log`).
- `FORMS_DIR` (`/data/forms` en el contenedor): se crea o se comprueba al arrancar y se monta como volumen escribible. **No se escanea ni se interpreta.**
- Docker Compose: Caddy (único punto público, TLS automático) → app → PostgreSQL, con redes internas.
- Namespace `/api/v1/` reservado: hoy solo responde errores JSON (`404 NOT_FOUND`).

## Qué NO existe todavía

| Pieza | Estado |
|---|---|
| Form Loader (`form.toml`) | Not implemented yet (Hito 1) |
| `elements.toml` / validación de elementos | Not implemented yet |
| `resources.toml` / Resource Manager | Not implemented yet |
| `rules.json` / Rules Engine | Not implemented yet |
| Submissions genéricas / reservations | Not implemented yet |
| JS Runner | Not implemented yet |
| Markdown, UI custom, `SITE_DIR`, builder, export | Not implemented yet |
| API pública de formularios (`/api/v1/forms/...`) | Not implemented yet |

## Requisitos

- Docker con Compose v2.
- Para desarrollo: Python 3.12.

## Configuración

Copia `.env.example` a `.env` y completa los valores. `.env` nunca se sube a git.

| Variable | Usada por | Descripción |
|---|---|---|
| `APP_ENV` | app | `production` (por defecto), `development` o `test`. En producción faltan secretos → la app no arranca. |
| `APP_DOMAIN` | Caddy | Dominio público para TLS. `localhost` usa la CA interna de Caddy. |
| `APP_TIMEZONE` | app | Zona horaria para mostrar fechas (por defecto `UTC`). Los timestamps se guardan en UTC. |
| `FORMS_DIR` | app | Fijo a `/data/forms` en el contenedor (volumen `forms_data`). |
| `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` | db, scripts | Rol bootstrap de PostgreSQL. La app **no** recibe `POSTGRES_PASSWORD`. |
| `APP_DB_USER`, `APP_DB_PASSWORD` | db, app | Rol de aplicación (NOSUPERUSER, NOCREATEDB, NOCREATEROLE, NOREPLICATION, NOBYPASSRLS). |
| `DATABASE_URL` | app | Opcional; sustituye la URL construida con `APP_DB_*`. |
| `ADMIN_USERNAME`, `ADMIN_PASSWORD_HASH` | app | Único admin. Deben definirse juntos. |
| `SESSION_SECRET` | app | ≥ 32 caracteres. Clave HMAC de sesiones y firma del CSRF de login. |
| `ADMIN_LOGIN_RATE_LIMIT` | app | Por defecto `5/15minutes`. |
| `SESSION_MAX_AGE_SECONDS` | app | Duración absoluta de la sesión admin (300-86400, por defecto 14400). |
| `LOG_LEVEL` | app | `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`. |

Opcionales con valores por defecto seguros: `DB_STATEMENT_TIMEOUT_MS` (15000), `DB_LOCK_TIMEOUT_MS` (10000), `MAX_REQUEST_BODY_BYTES` (16384).

`SITE_DIR` está previsto en el roadmap pero **no** se configura en el Hito 0: no tendría consumidor.

### Secretos

```bash
openssl rand -hex 32   # POSTGRES_PASSWORD y APP_DB_PASSWORD
openssl rand -hex 48   # SESSION_SECRET
docker compose run --rm --no-deps app python -m app.security.generate_hash   # ADMIN_PASSWORD_HASH
```

El hash va entre comillas simples en `.env` (`ADMIN_PASSWORD_HASH='$argon2id$...'`).

## Docker

```bash
docker compose up -d --build
docker compose ps
```

Arranque del contenedor app: `wait_for_db` → `alembic upgrade head` → preparación de `FORMS_DIR` → Uvicorn con **un solo worker** (el rate limiter es in-memory). No hay seed.

Solo Caddy publica puertos (80, 443, 443/udp). PostgreSQL (5432) y la app (8000) solo son accesibles por redes Docker internas.

## Desarrollo y pruebas

```bash
make venv             # .venv con dependencias fijadas
make test-db-up       # PostgreSQL desechable en 127.0.0.1:55433 (tmpfs)
make test             # suite completa contra PostgreSQL real
make test-unit        # sin base de datos
make test-integration
make test-concurrency
make lint format typecheck security-check
make check            # lint + typecheck + security + tests
```

Los tests se conectan con el **rol de aplicación de mínimo privilegio**, creado por el mismo `docker/postgres/10-app-role.sh` que en producción. Solo usan datos sintéticos (`ALICE EXAMPLE`, `BOB EXAMPLE`, ...).

Smoke test de un stack en marcha (aislamiento de contenedores + HTTP vía Caddy):

```bash
BASE_URL=https://localhost ADMIN_USER=... ADMIN_PASS=... CURL_INSECURE=1 scripts/smoke_test.sh
```

## Backups

`scripts/backup.sh` crea un dump comprimido de **PostgreSQL** en `backups/`. `scripts/restore.sh` lo restaura (pide confirmación).

El backup actual **no** incluye `FORMS_DIR`. En el Hito 0 ese directorio no contiene formularios, pero cuando exista el Form Loader un backup completo de FormManager deberá cubrir **PostgreSQL + FORMS_DIR** (y `SITE_DIR` si llega a existir). El empaquetado de formularios no está implementado.

## Documentación

- [`ARCHITECTURE.md`](ARCHITECTURE.md): componentes del Hito 0 y fronteras.
- [`SECURITY.md`](SECURITY.md): modelo de amenazas y controles.
- [`PROJECT_RULES.md`](PROJECT_RULES.md), [`REBASE.md`](REBASE.md), [`CLAUDE.md`](CLAUDE.md): reglas normativas.

## Licencia

Ver [`LICENSE`](LICENSE).
