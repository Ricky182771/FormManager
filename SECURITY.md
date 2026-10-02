# Seguridad (Hito 0)

Alcance: la fundación del Core. Todavía no hay formularios, submissions, resources ni JS Runner, así que sus riesgos no se tratan aquí.

## Modelo de amenazas

| Actor | Capacidad asumida |
|---|---|
| Visitante anónimo | Envía cualquier petición HTTP a Caddy, con cabeceras falsificadas. |
| Atacante cross-site | Hace que el navegador de un admin con sesión envíe peticiones. |
| Atacante de fuerza bruta | Muchos intentos de login desde una o varias IPs. |
| Contenedor app comprometido | Ejecuta código como el usuario de la app. |

Fuera de alcance: compromiso del host, del daemon Docker o del administrador.

## Controles

### Autenticación admin

- Un único admin definido por entorno (`ADMIN_USERNAME` + `ADMIN_PASSWORD_HASH`). Multiusuario: no implementado.
- Argon2id (argon2-cffi, parámetros RFC 9106). Nunca texto plano ni hashes rápidos.
- Usuario incorrecto y contraseña incorrecta cuestan lo mismo: con usuario incorrecto se verifica un hash ficticio.
- Comparación de usuario con `hmac.compare_digest`. Un hash inválido devuelve `False`, sin excepción.
- El login fallido se audita **sin** usuario: suele contener contraseñas tecleadas en el campo equivocado.

### Sesiones

- Token opaco de 256 bits (`secrets.token_urlsafe(32)`) en cookie. PostgreSQL guarda solo `HMAC-SHA256(SESSION_SECRET, token)`.
- Expiración absoluta server-side (`SESSION_MAX_AGE_SECONDS`). Las sesiones caducadas se purgan en cada login.
- Al iniciar sesión se descarta cualquier sesión presentada por el navegador (regeneración). Logout borra la fila (revocación real).
- Cookie `HttpOnly`, `SameSite=Strict`, `Path=/`; en producción `Secure` y prefijo `__Host-` (sin `Domain`).

### CSRF

- Formularios admin: token por sesión guardado en DB, comparado con `hmac.compare_digest`.
- Login (sin sesión aún): token en cookie firmada (`itsdangerous`, salt propia, 1 h, `SameSite=Strict`) y en el formulario. Un token de otro navegador no sirve.
- Además: `Sec-Fetch-Site` debe ser `same-origin`/`none` si existe, y `Origin`, si existe, debe coincidir exactamente con el origen.

### Abuso

- Rate limit de `POST /admin/login` por IP (por defecto 5 intentos / 15 min, cuentan también los exitosos) con `Retry-After`. Mientras está bloqueado, incluso la contraseña correcta se rechaza.
- Es defensa de abuso, no identidad ni integridad. In-memory: requiere **un solo worker ASGI**. Escalar workers exige antes un backend compartido.
- La IP sale de `X-Forwarded-For` reescrito por Caddy. Uvicorn confía en proxy headers porque solo Caddy alcanza la app (red interna, sin puerto publicado). Un `X-Forwarded-For` falsificado desde el cliente no evade el límite: verificado contra el stack real a través de Caddy y cubierto por un test a nivel de app.
- Las IPs viven solo en memoria y se purgan tras 2 h de inactividad.

### HTTP

- CSP: `default-src 'none'`, `script-src 'self'`, `style-src 'self'`, `frame-ancestors 'none'`, `base-uri 'none'`, `object-src 'none'`. Sin `unsafe-inline`, `unsafe-eval` ni `*`. La UI no usa JavaScript.
- `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: same-origin`, `Permissions-Policy` restrictiva, COOP/CORP `same-origin`, sin cabecera `Server`.
- `Cache-Control: no-store` en todo salvo `/static/`. HSTS solo si la petición llega por HTTPS (y Caddy lo añade en el borde).
- Sin CORS: no se envía `Access-Control-Allow-Origin`.
- Límite de body: `Content-Length` declarado y conteo real del stream (16 KiB por defecto; Caddy además corta a 64 KB).
- Jinja2 con autoescape; los errores de validación no reflejan los valores enviados.
- Errores genéricos: sin trazas, SQL, DSN ni rutas internas. OpenAPI/docs deshabilitados.

### Logging

- JSON por línea: `timestamp`, `level`, `logger`, `event` + extras de una **allowlist**.
- Claves que contengan `password`, `secret`, `token`, `csrf`, `cookie`, `authorization`, `api_key`, `access_code`, `database_url`, `dsn`, `hash`, `body` nunca se registran, aunque se añadan a la allowlist por error.
- El log de peticiones registra método, ruta, estado y latencia. Sin IP, query string, cookies ni body. El access log de Uvicorn está desactivado.

### Base de datos

- Rol bootstrap (solo contenedor db y scripts de backup) separado del rol de aplicación.
- Rol de aplicación: `NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS`, `CONNECTION LIMIT 30`, dueño solo de su base. `REVOKE CREATE ON SCHEMA public FROM PUBLIC`.
- La app no recibe `POSTGRES_PASSWORD` (lista explícita de variables en compose, sin `env_file`).
- Auth `scram-sha-256`. 5432 no publicado.
- `statement_timeout` (15 s) y `lock_timeout` (10 s) acotan esperas bloqueadas (tests de concurrencia).
- Consultas solo vía SQLAlchemy parametrizado.

### Contenedores

| Servicio | Controles |
|---|---|
| app | uid/gid 10001, rootfs `read_only`, `/tmp` tmpfs 16 MB `noexec`, `/data/forms` único volumen escribible, `cap_drop: ALL`, `no-new-privileges`, `pids_limit 256`, 512 MB, 1 CPU, healthcheck, sin puertos publicados, sin Docker socket. |
| db | `no-new-privileges`, `pids_limit 256`, 512 MB, solo red `backend` (internal). |
| caddy | `cap_drop: ALL` + `NET_BIND_SERVICE`, `no-new-privileges`, admin API desactivada, logs de acceso descartados. |

Las redes `backend` y `proxy` son `internal: true`: la app no tiene salida a Internet.

### Secretos

- Solo en `.env` (ignorado por git) o variables de entorno. `.env.example` no contiene valores.
- En producción la app no arranca si `SESSION_SECRET` tiene menos de 32 caracteres, si faltan credenciales de DB o si el admin está a medio configurar.
- `generate_hash` lee la contraseña con `getpass` (sin eco, nunca como argumento).

## Verificación

Cubierto por tests (`tests/`) y por `scripts/smoke_test.sh` contra el stack real: puertos publicados, uid, rootfs read-only, `FORMS_DIR` escribible, ausencia de `POSTGRES_PASSWORD`, cabeceras, HSTS y login/logout por Caddy.

## Limitaciones conocidas

- Rate limiter in-memory: se reinicia con la app y no sirve con varios workers.
- `/` y `/health` hacen un ping a la DB por petición; no tienen rate limit propio (Caddy no limita por tasa).
- Backup cubre solo PostgreSQL; `FORMS_DIR` no (sin contenido en el Hito 0).
- El rol de app es dueño del esquema, así que puede alterar tablas (necesario para que ejecute las migraciones al arrancar).
- La imagen de Caddy corre como root dentro del contenedor (con capacidades mínimas), igual que en el prototipo.
