# Seguridad (Hito 1)

Alcance: la fundación del Core y la carga de paquetes de formulario desde `FORMS_DIR`. Todavía no hay submissions, resources, rules ni JS Runner, así que sus riesgos no se tratan aquí.

## Modelo de amenazas

| Actor | Capacidad asumida |
|---|---|
| Visitante anónimo | Envía cualquier petición HTTP a Caddy, con cabeceras falsificadas. |
| Atacante cross-site | Hace que el navegador de un admin con sesión envíe peticiones. |
| Atacante de fuerza bruta | Muchos intentos de login desde una o varias IPs. |
| Contenedor app comprometido | Ejecuta código como el usuario de la app. |
| Autor de un paquete de formulario | Coloca archivos arbitrarios en `FORMS_DIR` (symlinks, archivos enormes, FIFOs, TOML/JSON hostil, IDs o slugs duplicados). Los paquetes se tratan como configuración **no confiable**. |

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

### Paquetes de formulario (`FORMS_DIR`)

- Todo acceso pasa por `app/forms/fsutil.py`: cada nombre se resuelve contra un fd de directorio abierto (`openat`) con `O_NOFOLLOW`. Un nombre no puede salir del directorio donde se encontró; no hay rutas construidas con texto del paquete. Requiere Linux/POSIX (plataforma soportada del runtime v1).
- `FORMS_DIR` se abre con `O_DIRECTORY|O_NOFOLLOW`. Solo se recorren sus hijos directos; las entradas con `.` inicial (incluido `.tmp-*`) se ignoran.
- Symlinks rechazados en toda la frontera del paquete: directorio, los cuatro archivos de definición y `resources/`, `assets/`, `ui/`.
- Los archivos de definición deben ser regulares. Se comprueba con `lstat` antes de abrir (un FIFO o dispositivo nunca se abre) y con `fstat` tras abrir (mismo inode; detecta un intercambio entre ambas llamadas). `O_NONBLOCK` evita bloquearse si aun así aparece un FIFO.
- Límite `FORM_DEFINITION_MAX_BYTES` (1 MiB por defecto) por archivo: se comprueba el tamaño declarado antes de leer y la lectura se corta en límite+1 bytes, antes de parsear.
- El ID se valida con `^[A-Za-z0-9_-]{16}$` y debe coincidir con el nombre del directorio: un `id` como `../../etc` es inválido, nunca una ruta.
- Parsers de la stdlib (`tomllib`, `json`). JSON rechaza claves duplicadas y `NaN`/`Infinity`; anidación excesiva (`RecursionError`) se convierte en diagnóstico. Texto de `form.toml` sin caracteres de control (un NUL nunca llega a PostgreSQL).
- Esquema estricto: propiedades desconocidas son error.
- Slugs o IDs duplicados invalidan a **todos** los participantes: un paquete nuevo no puede "secuestrar" el slug de otro siendo cargado antes.
- Un paquete inválido no afecta a los demás ni impide arrancar. Los diagnósticos llevan ruta relativa, archivo, código y mensaje fijo: sin rutas absolutas, contenido ni trazas. Solo van al log; la API no los expone.
- Los IDs se generan con `secrets` (96 bits). No son secretos ni autenticación.
- El creador interno escribe en `.tmp-<random>/<id>/` con `O_CREAT|O_EXCL`, valida con el mismo loader y hace `renameat` atómico; nunca sobrescribe un paquete existente y limpia ante fallo. No tiene endpoint.

### API de formularios

- `GET /api/v1/forms` y `GET /api/v1/forms/{slug}` devuelven solo metadata (`id`, `slug`, `title`, `status`, `schema_version`, y en el detalle `subtitle`/`description` como texto). Nunca rutas del filesystem, contenido de elements/resources/rules ni diagnósticos.
- El slug de la URL solo se usa como clave de un diccionario en memoria; no toca el filesystem.
- No hay endpoint de creación, edición ni recarga.
- Formularios en cualquier estado (incluido `draft`) aparecen en la lista. **No es la política pública final**: el hito de publicación/acceso decidirá qué estados son visibles.

### Secretos

- Solo en `.env` (ignorado por git) o variables de entorno. `.env.example` no contiene valores.
- En producción la app no arranca si `SESSION_SECRET` tiene menos de 32 caracteres, si faltan credenciales de DB o si el admin está a medio configurar.
- `generate_hash` lee la contraseña con `getpass` (sin eco, nunca como argumento).

## Verificación

Cubierto por tests (`tests/`, incluidos `tests/unit/test_form_security.py` y los tests de registry contra PostgreSQL real) y por `scripts/smoke_test.sh` contra el stack real: puertos publicados, uid, rootfs read-only, `FORMS_DIR` escribible, ausencia de `POSTGRES_PASSWORD`, cabeceras, HSTS, login/logout por Caddy y un formulario sintético cargado y servido por la API.

## Limitaciones conocidas

- Rate limiter in-memory: se reinicia con la app y no sirve con varios workers.
- `/` y `/health` hacen un ping a la DB por petición; no tienen rate limit propio (Caddy no limita por tasa).
- `scripts/backup.sh` cubre solo PostgreSQL. `FORMS_DIR` ya contiene las definiciones y debe respaldarse aparte (ver README).
- `GET /api/v1/forms` no tiene rate limit propio; sirve memoria, sin DB ni filesystem.
- La unicidad de slug en el creador interno no es segura ante creaciones concurrentes (no hay endpoint que las permita).
- El rol de app es dueño del esquema, así que puede alterar tablas (necesario para que ejecute las migraciones al arrancar).
- La imagen de Caddy corre como root dentro del contenedor (con capacidades mínimas), igual que en el prototipo.
