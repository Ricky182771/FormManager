# FormManager — Hito 1 / Form Package + Form Loader

Self-hosted, headless form engine with strict validation, reusable data resources, transactional rules, and customizable frontends.

> **Estado: Hito 1.** FormManager sabe qué formularios existen en `FORMS_DIR` y si sus paquetes son estructuralmente válidos. **Todavía no sabe ejecutar un formulario**: no hay elementos, recursos, reglas ni submissions.

Al arrancar, FormManager muestra:

```text
FormManager
Core: en ejecución
Base de datos: saludable
Formularios cargados: N
```

## Qué existe hoy

- App FastAPI `FormManager` con `GET /health` (ping ligero a PostgreSQL) y una página `/` de estado.
- Administración con un único admin definido por entorno: `/admin/login`, `/admin/logout`, `/admin` (panel mínimo).
- Contraseñas Argon2id, sesiones admin server-side (la DB guarda solo HMAC-SHA256 del token), CSRF, rate limiting del login, cabeceras de seguridad, CSP estricta, límite de tamaño de petición y logs JSON sin secretos.
- Auditoría genérica: `ADMIN_LOGIN`, `ADMIN_LOGIN_FAILED`, `ADMIN_LOGOUT`.
- PostgreSQL 16 con rol de aplicación de mínimo privilegio y migración Alembic `0001_initial_formmanager` (solo `admin_sessions` y `admin_audit_log`).
- `FORMS_DIR` (`/data/forms` en el contenedor): cada subdirectorio es un **paquete de formulario** (`form.toml`, `elements.toml`, `resources.toml`, `rules.json`). Se escanea al arrancar; `form.toml` se valida con un schema estricto y los otros tres solo sintácticamente. Contrato: [`FORM_SCHEMA.md`](FORM_SCHEMA.md).
- Paquetes inválidos (TOML/JSON roto, symlinks, archivos enormes, ID o slug duplicado...) se rechazan con un diagnóstico en el log sin impedir el arranque ni afectar a los demás.
- Migración `0002_forms_registry`: índice mínimo de los formularios válidos cargados, sincronizado en una transacción al arrancar.
- API de solo lectura: `GET /api/v1/forms` (ordenados por slug) y `GET /api/v1/forms/{slug}` (metadata; `404 FORM_NOT_FOUND`). La lista incluye formularios en cualquier estado, `draft` incluido: **no** es la política de visibilidad final.
- Creación atómica de paquetes **solo interna** (`app.forms.creator.create_form_package`); no hay endpoint ni UI.
- Docker Compose: Caddy (único punto público, TLS automático) → app → PostgreSQL, con redes internas.

## Qué NO existe todavía

| Pieza | Estado |
|---|---|
| `elements.toml` / validación de elementos | Not implemented yet (Hito 2). Hoy solo sintaxis + `schema_version`. |
| `resources.toml` / Resource Manager | Not implemented yet |
| `rules.json` / Rules Engine | Not implemented yet |
| Submissions genéricas / reservations | Not implemented yet |
| JS Runner | Not implemented yet |
| Markdown, UI custom, `SITE_DIR`, builder, export | Not implemented yet |
| Definición, submissions y creación por API (`/definition`, `/submissions`, `POST /forms`) | Not implemented yet |
| Visibilidad por `status`, acceso por formulario | Not implemented yet |
| Recarga de formularios sin reiniciar | Not implemented yet (reiniciar la app) |

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

Opcionales con valores por defecto seguros: `DB_STATEMENT_TIMEOUT_MS` (15000), `DB_LOCK_TIMEOUT_MS` (10000), `MAX_REQUEST_BODY_BYTES` (16384), `FORM_DEFINITION_MAX_BYTES` (1048576, por archivo de definición).

`SITE_DIR` está previsto en el roadmap pero **no** se configura todavía: no tendría consumidor.

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

Arranque del contenedor app: `wait_for_db` → `alembic upgrade head` → preparación de `FORMS_DIR` → carga de paquetes + sync de `forms_registry` → Uvicorn con **un solo worker** (el rate limiter es in-memory). No hay seed. Si la sync con PostgreSQL falla, la app no arranca.

Los formularios se cargan solo al arrancar: tras añadir o modificar un paquete, `docker compose restart app`.

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

Smoke test de un stack en marcha (aislamiento de contenedores + HTTP vía Caddy). Crea un formulario sintético `room-booking`, reinicia la app para cargarlo, lo comprueba por HTTP y después lo elimina y reinicia de nuevo:

```bash
BASE_URL=https://localhost ADMIN_USER=... ADMIN_PASS=... CURL_INSECURE=1 scripts/smoke_test.sh
```

## Backups

`scripts/backup.sh` crea un dump comprimido de **PostgreSQL** en `backups/`. `scripts/restore.sh` lo restaura (pide confirmación).

El backup actual **no** incluye `FORMS_DIR`, que desde el Hito 1 contiene las definiciones de los formularios (la fuente canónica). Un backup completo es **PostgreSQL + FORMS_DIR**. Hasta que exista un script para ello, respalda el volumen a mano, por ejemplo:

```bash
docker run --rm -v formmanager_forms_data:/data/forms:ro -v "$PWD/backups":/out alpine \
    tar -C /data -czf /out/forms-$(date +%Y%m%d-%H%M%S).tar.gz forms
```

`forms_registry` se reconstruye sola desde `FORMS_DIR` al arrancar.

## Documentación

- [`ARCHITECTURE.md`](ARCHITECTURE.md): componentes y fronteras.
- [`FORM_SCHEMA.md`](FORM_SCHEMA.md): paquete de formulario y `form.toml`.
- [`SECURITY.md`](SECURITY.md): modelo de amenazas y controles.
- [`PROJECT_RULES.md`](PROJECT_RULES.md), [`REBASE.md`](REBASE.md), [`CLAUDE.md`](CLAUDE.md): reglas normativas.

## Licencia

Ver [`LICENSE`](LICENSE).
