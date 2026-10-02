# FormManager — REBASE.md

> Guía de migración desde **TeamRegistration** hacia el nuevo **FormManager** genérico.
>
> Este documento no describe un simple cambio de nombre. La migración debe conservar las partes robustas del proyecto original y eliminar por completo el acoplamiento al caso escolar concreto.

## 0. Autoridad y propósito

Claude Code debe tratar este archivo como una guía obligatoria de migración.

Si existe `PROJECT_RULES.md`, ese documento define los principios generales del producto y tiene prioridad sobre este archivo. `REBASE.md` define específicamente **qué reutilizar del repositorio TeamRegistration, qué debe desaparecer y cómo debe transformarse**.

El repositorio TeamRegistration es una **referencia de implementación y seguridad**, no una dependencia del nuevo proyecto.

La migración NO debe consistir en copiar el repositorio entero y renombrar clases. Debe portarse comportamiento reusable y rediseñarse todo aquello que dependa de:

- alumnos;
- temas;
- equipos;
- representantes;
- exactamente 44 alumnos;
- exactamente 11 temas/equipos;
- equipos de exactamente 4 integrantes;
- el tema «Transhumanismo y Posthumanismo»;
- nombres reales incluidos en `seed_data.py`;
- mensajes, rutas, plantillas o modelos propios de esa actividad.

El resultado debe ser un producto nuevo: **FormManager**, un motor de formularios self-hosted y headless-first.

---

# 1. Resumen del repositorio original analizado

TeamRegistration utiliza actualmente:

- Python 3.12;
- FastAPI;
- SQLAlchemy 2.x;
- Alembic;
- Pydantic 2;
- PostgreSQL 16;
- psycopg 3;
- Jinja2;
- JavaScript y CSS propios;
- Argon2id;
- Caddy;
- Docker Compose;
- pytest;
- ruff;
- black;
- mypy estricto;
- bandit;
- pip-audit.

La arquitectura desplegada es:

```text
Internet
   │
   ▼
 Caddy
   │  red Docker interna
   ▼
FastAPI
   │  red Docker interna
   ▼
PostgreSQL
```

El contenedor `app` no publica puerto al host. PostgreSQL tampoco. Solo Caddy publica 80/443.

El proyecto original tiene varias decisiones de seguridad y concurrencia que **sí deben conservarse conceptualmente** y una capa de dominio escolar que **no debe migrarse**.

---

# 2. Regla principal de la migración

## 2.1 Portar invariantes, no entidades

Claude debe conservar ideas como:

- transacciones atómicas;
- constraints de PostgreSQL;
- manejo explícito de `IntegrityError`;
- protección ante carreras;
- rollback completo;
- sesiones seguras;
- CSRF;
- rate limiting;
- aislamiento Docker;
- mínimo privilegio;
- logs sin secretos;
- tests reales contra PostgreSQL.

Claude NO debe conservar como arquitectura central:

```text
Student
Topic
Team
TeamMember
MAX_TEAMS
TEAM_SIZE
TOTAL_STUDENTS
register_team()
```

Estos conceptos fueron útiles para el prototipo, pero en FormManager deben convertirse en abstracciones genéricas:

```text
Form
Element
Resource
Rule
Submission
SubmissionValue
Reservation
FormVersion
```

## 2.2 No crear «genéricos falsos»

NO renombrar simplemente:

```text
Student -> ResourceItem
Team -> Submission
Topic -> Option
```

si la lógica continúa asumiendo internamente cuatro integrantes, once opciones o roles de representante.

Cada pieza migrada debe ser realmente independiente del formulario escolar.

---

# 3. Información personal: prohibición de migración

El nuevo repositorio NO debe contener:

- nombres reales de alumnos del proyecto original;
- la lista oficial de 44 alumnos;
- temas escolares reales como seed obligatorio;
- backups del despliegue original;
- respuestas reales;
- logs reales;
- hashes o secretos usados en Azure;
- `.env` reales.

`app/seed_data.py` del proyecto original **NO debe copiarse**.

Si se necesita una demo o fixture equivalente, usar exclusivamente datos ficticios, por ejemplo:

```text
ALICE EXAMPLE
BOB EXAMPLE
CAROL EXAMPLE
DAVE EXAMPLE
```

Los ejemplos deben vivir en `examples/` o fixtures de tests, nunca hardcodeados en el Core.

---

# 4. Qué debe mantenerse casi intacto conceptualmente

Las siguientes piezas del proyecto original son buenas bases. Pueden portarse y renombrarse cuando corresponda, pero deben conservar sus propiedades de seguridad.

## 4.1 `app/db/base.py`

Mantener:

- `DeclarativeBase`;
- convención determinista de nombres de constraints;
- nombres estables para PK/FK/UQ/CK/IX.

Razón: el código de dominio genérico necesitará interpretar conflictos de PostgreSQL sin depender de textos de error localizados.

No acoplar nombres de constraints a TeamRegistration.

## 4.2 `app/db/session.py`

Mantener:

- SQLAlchemy Engine;
- `pool_pre_ping=True`;
- reciclaje razonable de conexiones;
- `connect_timeout`;
- `statement_timeout`;
- `lock_timeout`;
- `application_name` identificable;
- session factory con `expire_on_commit=False`;
- health ping.

Cambiar `application_name="team_registration"` por `formmanager`.

Los timeouts pueden hacerse configurables, pero nunca eliminarse sin justificación.

## 4.3 `app/logging_setup.py`

Mantener el logging estructurado JSON.

Mantener como mínimo:

- timestamp UTC;
- nivel;
- logger;
- evento;
- extras permitidos;
- filtrado de claves sensibles;
- no persistir IPs por defecto;
- desactivar access log de Uvicorn si éste almacenaría IPs innecesariamente.

Ampliar la lista de claves sensibles según aparezcan nuevas funciones:

```text
password
secret
token
csrf
cookie
authorization
api_key
access_code
database_url
```

Nunca loguear bodies completos de submissions por defecto.

## 4.4 `app/middleware.py`

Mantener conceptualmente:

- límite de tamaño de body tanto por `Content-Length` como por conteo del stream;
- security headers;
- `Cache-Control: no-store` para páginas dinámicas sensibles;
- request logging sin query string, cookies, body ni IP;
- HSTS solo cuando la petición se sirve sobre HTTPS.

La CSP original es una buena base, pero el nuevo FormManager tendrá `builtin`, `custom` y `headless` frontend modes. NO relajar globalmente la CSP para acomodar UI personalizada.

Cuando se implemente custom UI, su política debe diseñarse explícitamente. Hasta entonces conservar una CSP estricta.

## 4.5 `app/security/passwords.py`

Portar prácticamente el mismo patrón:

- Argon2id;
- hashing server-side;
- verificación de hash inválido sin crash;
- dummy hash para igualar el coste del caso «usuario inexistente» y «contraseña incorrecta»;
- comparación segura.

NO cambiar a SHA-256, MD5, PBKDF casero ni hashes rápidos.

## 4.6 `app/security/csrf.py`

Mantener:

- token aleatorio criptográficamente seguro;
- `hmac.compare_digest`;
- comprobación `Origin`;
- comprobación `Sec-Fetch-Site` cuando exista.

Todas las mutaciones con autenticación basada en cookies deben conservar protección CSRF.

## 4.7 `app/security/sessions.py`

### Sesiones administrativas

Mantener el patrón:

- token aleatorio opaco en cookie;
- solo HMAC/hash del token almacenado en PostgreSQL;
- expiración server-side;
- regeneración/revocación al iniciar sesión;
- borrado al cerrar sesión;
- cookie `HttpOnly`;
- `Secure` en producción;
- `SameSite=Strict` para admin;
- prefijo `__Host-` cuando se cumplen sus requisitos.

El nuevo v1 puede continuar con un único administrador configurado por variables de entorno. Multiusuario queda fuera de esta migración salvo indicación posterior.

### Estado público

NO copiar literalmente el modelo actual:

```text
csrf
access_granted_at
team_id
```

`team_id` es específico de TeamRegistration.

Conservar únicamente la idea de estado público firmado y CSRF. Rediseñar el estado para que sea genérico y, si hay autorización por formulario, quede correctamente vinculada a un `form_id`/versión y no permita que el acceso a un formulario conceda acceso a todos.

No meter listas ilimitadas de formularios en una cookie. Si el diseño requiere muchos grants, usar estado server-side o cookies acotadas por formulario.

## 4.8 `app/security/rate_limit.py`

Mantener el sliding-window limiter como defensa de abuso, no como mecanismo de identidad ni de integridad.

Conservar:

- buckets independientes;
- ventanas configurables;
- IP solo en memoria;
- limpieza periódica;
- `Retry-After`;
- tests deterministas con reloj inyectable.

Mientras el limiter sea in-memory, ejecutar un solo worker ASGI o sustituirlo explícitamente por un backend compartido antes de aumentar workers.

No usar la IP para decidir «una respuesta por persona».

En FormManager, los buckets deberán incluir suficiente contexto, por ejemplo:

```text
submit:<form_id>
access:<form_id>
admin_login
```

sin alterar la lógica de integridad del formulario.

## 4.9 `app/wait_for_db.py`

Mantener:

- espera activa con deadline;
- backoff exponencial;
- timeout duro;
- no usar sleeps fijos arbitrarios;
- logs estructurados.

## 4.10 Healthcheck

Mantener `/health` ligero y sin información sensible.

Debe verificar al menos:

- proceso de aplicación vivo;
- PostgreSQL accesible.

Más adelante podrán existir `/health/live` y `/health/ready`, pero no es obligatorio durante la migración inicial.

---

# 5. Docker y despliegue: invariantes que NO deben degradarse

El nuevo proyecto debe conservar la postura de seguridad del stack original.

## 5.1 Contenedor de aplicación

Mantener:

- imagen multistage o equivalente;
- Python slim;
- usuario no-root;
- UID/GID dedicado;
- root filesystem `read_only` cuando sea posible;
- `/tmp` como tmpfs limitado;
- `cap_drop: ALL`;
- `no-new-privileges:true`;
- límite razonable de PIDs;
- límite razonable de memoria;
- healthcheck;
- sin Docker socket.

FormManager sí necesitará escribir formularios cuando el administrador los cree. NO desactivar `read_only` para todo el contenedor por esta razón.

En su lugar, montar explícitamente un volumen/directorio writable, por ejemplo:

```text
/data/forms
/data/site
```

y mantener el resto del filesystem del contenedor read-only.

## 5.2 PostgreSQL

Mantener dos identidades distintas:

- superusuario/bootstrap de PostgreSQL;
- rol de aplicación no-superuser.

La aplicación NO debe recibir `POSTGRES_PASSWORD`.

Portar el patrón de `docker/postgres/10-app-role.sh`:

- `NOSUPERUSER`;
- `NOCREATEDB`;
- `NOCREATEROLE`;
- `NOREPLICATION`;
- `NOBYPASSRLS`;
- límite de conexiones razonable;
- revocar privilegios innecesarios de `PUBLIC`.

PostgreSQL no debe publicar 5432 al host en producción.

## 5.3 Redes Docker

Mantener separación equivalente a:

```text
backend  -> app <-> db      internal:true
proxy    -> caddy <-> app   internal:true
edge     -> caddy <-> Internet
```

No dar salida a Internet al Core por defecto si no la necesita.

Cuando llegue el JS Runner, deberá seguir una política separada y explícita. No adelantar esa implementación durante el rebase inicial.

## 5.4 Caddy

Mantener:

- único punto público;
- TLS automático;
- redirect HTTP -> HTTPS;
- compresión;
- límite adicional de request body;
- eliminación de headers innecesarios;
- proxy exclusivamente hacia la app interna.

No publicar directamente FastAPI.

## 5.5 Entrada del contenedor

Mantener la secuencia conceptual:

```text
wait-for-db
    ↓
alembic upgrade head
    ↓
inicialización idempotente necesaria
    ↓
serve
```

Pero reemplazar el seed escolar por inicialización genérica del Core.

No crear alumnos/temas por defecto.

---

# 6. Qué debe eliminarse o reemplazarse completamente

## 6.1 `app/config.py`

Eliminar:

```python
MAX_TEAMS = 11
TEAM_SIZE = 4
TOTAL_STUDENTS = 44
```

Eliminar cualquier variable de configuración cuyo significado sea exclusivamente «registro de equipos».

Mantener y generalizar:

- entorno;
- dominio;
- timezone;
- conexión DB;
- admin;
- session secret;
- request size;
- rate limits;
- logging.

Agregar en el momento correspondiente:

```text
FORMS_DIR
SITE_DIR
```

El código de acceso deja de ser una propiedad global rígida del sistema. Debe transformarse en configuración de acceso por formulario cuando ese hito sea implementado.

## 6.2 Modelos de dominio

NO migrar como modelos principales:

```text
app/models/student.py
app/models/topic.py
app/models/team.py
app/models/team_member.py
```

Sus invariantes deben inspirar el modelo genérico, pero no sobrevivir como tablas obligatorias.

Crear modelos nuevos orientados al Core, de acuerdo con los hitos acordados. La dirección prevista es:

```text
forms_registry
form_versions
submissions
submission_values
reservations
admin_sessions
admin_audit_log
```

Los nombres y columnas finales deben definirse en el hito correspondiente, no improvisarse únicamente para imitar el modelo viejo.

## 6.3 `AppSettings`

El singleton actual `registration_open` no escala a múltiples formularios.

No copiarlo literalmente.

Distinguir:

- configuración de instancia;
- estado/configuración de cada formulario.

El estado OPEN/CLOSED deberá ser por formulario.

## 6.4 `seed.py` y `seed_data.py`

Eliminar toda dependencia del roster y topics escolares.

El nuevo inicializador solo debe crear datos de infraestructura verdaderamente genéricos si son necesarios.

Los formularios de ejemplo deben cargarse como packages dentro de `examples/` o mediante mecanismos de importación explícitos, no como seed obligatorio de producción.

## 6.5 `app/schemas/registration.py`

No migrar `RegistrationIn`, `PersonOut`, `TopicOut`, etc. como API oficial.

Reemplazarlos con schemas genéricos de:

```text
FormDefinition
ElementDefinition
ResourceDefinition
SubmissionRequest
SubmissionResponse
ValidationError
ConflictError
```

Pydantic deberá continuar usando `extra="forbid"` donde la especificación sea cerrada.

Tipos estrictos deben seguir siendo la norma. No aceptar coerciones silenciosas como `"1" -> 1` cuando el schema declare un entero estricto.

## 6.6 `app/services/registration.py`

Este archivo contiene una de las mejores partes del prototipo, pero también el mayor acoplamiento al dominio.

NO portarlo como `register_team()` renombrado.

Extraer sus ideas:

- una única ruta de escritura por submission;
- transacción única;
- pre-checks solo para mensajes amigables;
- correctness garantizada por PostgreSQL;
- inserciones en orden determinista cuando múltiples recursos puedan colisionar;
- retries limitados para SQLSTATE 40001/40P01;
- traducción de conflictos a 409;
- rollback total;
- lectura coherente de disponibilidad.

Estas ideas deberán reaparecer en servicios genéricos, por ejemplo:

```text
app/services/submissions.py
app/services/reservations.py
app/services/rules.py
```

No crear estos archivos antes del hito que los necesite.

## 6.7 `app/services/admin.py`

Conservar:

- auditoría;
- CSV seguro;
- confirmación antes de borrado;
- transacciones administrativas.

Eliminar/generalizar:

- `TeamView`;
- `list_teams()`;
- `get_team()`;
- `delete_team()`;
- headers CSV fijos de integrantes/tema;
- acciones `TEAM_DELETED`.

La exportación genérica debe derivar columnas de la definición/version del formulario.

La función `_cell()` que neutraliza formula injection de spreadsheets es valiosa y debe conservarse o reemplazarse por una función equivalente cubierta por tests.

## 6.8 Rutas

Eliminar como API estable:

```text
/api/register
/api/students/available
/api/topics/available
/api/availability
```

El nuevo contrato debe comenzar versionado:

```text
/api/v1/
```

La API pública debe ser genérica por formulario, por ejemplo:

```text
GET  /api/v1/forms/{slug}
GET  /api/v1/forms/{slug}/definition
GET  /api/v1/forms/{slug}/state
POST /api/v1/forms/{slug}/submissions
```

No es obligatorio implementar todos durante el primer hito. Sí es obligatorio no consolidar nuevas rutas no versionadas como API oficial.

## 6.9 Templates y frontend

No portar textos ni estructura escolar.

La UI original puede usarse como referencia de:

- accesibilidad;
- manejo de estados;
- errores;
- CSRF;
- responsive layout.

Pero el nuevo frontend builtin debe renderizar definiciones genéricas.

No incrustar conocimiento de `student`, `topic`, `member_2`, etc.

---

# 7. Base de datos: estrategia de rebase

El nuevo FormManager es un repositorio nuevo. No debe fingir que su esquema genérico es una continuación directa de la migración escolar `0001_initial_schema.py`.

## Regla

Crear una nueva migración inicial coherente con FormManager.

No copiar la migración de TeamRegistration y después crear una serie de migraciones destructivas para renombrar/eliminar `students`, `teams`, etc.

Eso solo arrastraría deuda histórica y datos personales hacia un producto nuevo.

La migración de bases TeamRegistration existentes hacia FormManager queda fuera de v1 salvo que se solicite explícitamente en un hito posterior.

Si posteriormente se implementa un importador, deberá ser una herramienta explícita y separada.

---

# 8. Form packages en filesystem

La definición de formularios debe salir del código Python.

La dirección establecida es:

```text
FORMS_DIR/
└── <opaque-form-id>/
    ├── form.toml
    ├── elements.toml
    ├── resources.toml
    ├── rules.json
    ├── resources/
    ├── assets/
    └── ui/            # opcional
```

## 8.1 Identificador

Usar un ID opaco aleatorio, aproximadamente 16 caracteres o entropía equivalente.

No usar IDs secuenciales como mecanismo de descubrimiento público.

El ID no es un secreto ni sustituye autenticación.

## 8.2 `form.toml`

Contiene configuración global del formulario:

- schema version;
- id;
- slug;
- título;
- subtítulo;
- descripción;
- estado;
- configuración de acceso;
- límites globales;
- configuración opcional del frontend builtin;
- mensajes de presentación.

No crear `appearance.toml`.

## 8.3 `elements.toml`

Debe contener exclusivamente el esquema de entrada y condiciones locales.

NO contiene estilo.

Ejemplo:

```toml
[[element]]
id = "email"
type = "email"
label = "Correo"
required = true
```

No incluir:

```text
color
font
x
y
width
CSS class
animation
layout
```

## 8.4 `resources.toml`

Define datasets que los elementos pueden consumir.

V1 deberá dirigirse a recursos estáticos:

```text
CSV
TXT
JSON
TOML
```

JavaScript será un provider opcional en un hito posterior y nunca debe ejecutarse dentro del proceso principal de FastAPI.

## 8.5 `rules.json`

Contiene reglas declarativas globales o relacionales.

No ejecutar Python ni JavaScript arbitrario como lenguaje de reglas.

---

# 9. Esquema de entrada y calidad de datos

La migración debe conservar la filosofía estricta observada en `RegistrationIn` del prototipo y generalizarla.

Pipeline deseado:

```text
input
  ↓
syntax/type validation
  ↓
local element constraints
  ↓
explicit normalization
  ↓
resource validation
  ↓
rules
  ↓
transaction
  ↓
PostgreSQL
```

## 9.1 Tipos v1 previstos

```text
text
text_long
integer
decimal
boolean
email
url
date
time
datetime
select
multi_select
resource_select
resource_multi_select
```

Estos son tipos de datos, no widgets de UI.

No crear tipos Core llamados `checkbox`, `radio`, `dropdown` o `toggle` solo por su representación visual.

## 9.2 Restricciones locales

Pueden vivir en `elements.toml`:

```text
required
min
max
min_length
max_length
pattern
min_selected
max_selected
```

## 9.3 No coerción mágica

No convertir automáticamente:

```text
"18 años" -> 18
"sí" -> true
```

si el tipo no lo define expresamente.

## 9.4 Normalización

Solo aplicar transformaciones declaradas cuando alteren el valor visible:

```toml
[element.normalize]
trim = true
collapse_whitespace = true
case = "upper"
```

## 9.5 Valores de opciones

Separar siempre `value` de `label`.

Guardar el valor canónico, no el texto mostrado.

---

# 10. Markdown

Markdown se utiliza únicamente para contenido de presentación del formulario:

- título/subtítulo cuando corresponda;
- descripciones;
- instrucciones;
- ayuda;
- mensajes de confirmación.

Las respuestas de usuarios NO se interpretan como Markdown.

Debe existir soporte para Markdown inline y block de manera segura.

Raw HTML debe estar deshabilitado o sanitizado estrictamente.

No permitir esquemas peligrosos como `javascript:`.

El Markdown fuente es canónico; HTML es una representación derivada.

No implementar Markdown antes del hito correspondiente si todavía no existe el Form Loader básico.

---

# 11. Resources: reglas de migración

El prototipo usa `Student` y `Topic` como tablas permanentes. FormManager debe reemplazar esa idea por Resources.

Un Resource es una fuente de datos que el Core transforma a un dataset canónico.

Todos los loaders deben terminar en una estructura equivalente a:

```json
{
  "id": "item_001",
  "label": "Visible para la persona",
  "data": {
    "any": "structured metadata"
  }
}
```

El Core no debe depender del formato original.

### Recursos estáticos

```text
CSV
TXT
JSON
TOML
```

### JavaScript futuro

El JS provider será:

- opcional;
- ejecutado en un contenedor/runtime separado;
- no manipulable por inputs de respondientes;
- productor de datasets únicamente;
- sin autoridad para aceptar/rechazar submissions;
- sin acceso a DB, secretos, cookies, request body o Docker socket;
- sin red/filesystem por defecto;
- con output validado por el Core.

NO adelantar el JS Runner durante los hitos iniciales.

---

# 12. Concurrencia: comportamiento que sí debe sobrevivir

El archivo `tests/test_concurrency.py` demuestra una propiedad fundamental del prototipo: **PostgreSQL decide el ganador cuando dos requests compiten**.

FormManager debe conservar esa filosofía.

La UI puede mostrar «disponible», pero esa disponibilidad nunca es una reserva.

Las reglas globales como:

```text
valor único
opción máximo N veces
resource item máximo N veces
máximo N submissions
```

deben resolverse en la transacción de submission y protegerse en la base de datos mediante una estrategia apropiada:

- unique constraints;
- reservation rows;
- índices;
- locking cuando sea necesario;
- constraints;
- retries limitados para deadlocks/serialization failures.

Pre-checks pueden existir para devolver mensajes amigables, pero no son la garantía de correctness.

## 12.1 Regla de rollback

Si una submission escribe parcialmente cinco valores y el sexto entra en conflicto, la transacción completa debe revertirse.

No debe quedar:

- submission incompleta;
- reservations huérfanas;
- values parciales;
- contadores inconsistentes.

## 12.2 Orden determinista

Cuando una operación adquiera múltiples reservas/recursos capaces de colisionar, procesarlos en orden determinista para reducir riesgo de deadlocks, de forma equivalente al orden por `student_id` del prototipo.

---

# 13. HTTP y errores

Conservar la disciplina del proyecto original:

- 201 para creación exitosa;
- 400 para request inválida a nivel HTTP;
- 401 para ausencia de auth donde corresponde;
- 403 para auth/CSRF/access denegado;
- 404 para recursos inexistentes;
- 409 para conflicto de estado/concurrencia;
- 413 para body demasiado grande;
- 422 para datos que no cumplen schema;
- 429 para rate limit;
- 503 para dependencia temporalmente no disponible o formulario temporalmente incapaz de aceptar.

Errores API deben incluir un código machine-readable.

No devolver:

- stack traces;
- SQL;
- nombres internos de tablas;
- mensajes crudos de psycopg;
- valores secretos;
- input completo cuando no sea necesario.

La estrategia actual de `RequestValidationError` —no reflejar automáticamente el valor recibido— debe conservarse.

---

# 14. API headless-first

El nuevo FormManager debe considerar `/api/v1/` como contrato oficial.

La UI builtin es un cliente del Core, no una capa con privilegios especiales.

Un frontend externo debe poder crear una submission sin cargar HTML de FormManager.

No permitir nunca:

```text
frontend -> PostgreSQL
custom UI -> internal service bypass
JS resource provider -> submission commit
```

Toda submission sigue:

```text
Client
  ↓
API/Core
  ↓
Element validation
  ↓
Resource validation
  ↓
Rules engine
  ↓
Transaction
  ↓
Database constraints/reservations
  ↓
COMMIT
```

---

# 15. Frontend: qué conservar y qué no

La interfaz original funciona bien como referencia de UX, pero el nuevo producto es headless-first.

Mantener como objetivos:

- HTML semántico;
- responsive;
- teclado;
- foco visible;
- mensajes de error claros;
- estados loading/empty/error;
- dependencias frontend mínimas;
- no depender de CDN para funcionamiento básico.

No conservar:

- textos escolares;
- columnas rígidas representante/integrantes/tema;
- contadores fijos 44/11;
- lógica JS específica de alumnos/temas.

Modos previstos:

```text
builtin
custom
headless
```

No implementar React/Node dentro de la imagen Core.

Una UI React externa deberá compilarse fuera de FormManager y consumir `/api/v1/`.

---

# 16. Admin: qué mantener

Mantener inicialmente:

- login seguro;
- sesión server-side;
- CSRF;
- rate limit de login;
- logout;
- auditoría;
- confirmaciones destructivas;
- exportación segura;
- timestamps UTC y representación en timezone configurada.

Transformar el dashboard de:

```text
estado global + equipos
```

a:

```text
lista de formularios
  ↓
formulario seleccionado
  ├── definición/estado
  ├── submissions
  ├── resources
  ├── reglas
  └── exportación
```

No construir un editor visual complejo durante el rebase.

---

# 17. Auditoría

Conservar `AdminAuditLog` o un equivalente genérico.

Las acciones deben dejar de ser escolares.

Ejemplos futuros:

```text
ADMIN_LOGIN
ADMIN_LOGIN_FAILED
ADMIN_LOGOUT
FORM_CREATED
FORM_OPENED
FORM_CLOSED
FORM_UPDATED
FORM_DELETED
SUBMISSION_DELETED
FORM_EXPORTED
RESOURCE_REFRESHED
```

La metadata debe ser mínima y no contener submissions completas ni secretos.

---

# 18. Exportaciones

Portar la defensa contra CSV formula injection.

Cualquier exportación CSV debe neutralizar celdas que comiencen con caracteres interpretables como fórmulas por hojas de cálculo, incluyendo al menos:

```text
=
+
-
@
TAB
CR
```

Conservar soporte UTF-8 correcto.

La exportación genérica debe derivar headers del schema/version del formulario, no de columnas escolares fijas.

---

# 19. Tests que deben migrarse como patrones

No copiar literalmente tests con nombres de alumnos. Reescribirlos con fixtures sintéticos.

## 19.1 PostgreSQL real

Tests de integración y concurrencia críticos deben seguir usando PostgreSQL real.

NO sustituirlos por SQLite.

SQLite puede usarse para tests aislados si algún día tiene sentido, pero nunca como prueba de garantías específicas de PostgreSQL.

## 19.2 Concurrencia

Conservar equivalentes genéricos de:

1. dos requests por el mismo valor exclusivo -> 1 éxito, 1 conflicto;
2. dos requests compartiendo un resource item -> 1 éxito, 1 conflicto;
3. requests completamente independientes -> ambas exitosas;
4. muchos contendientes por una misma reserva -> exactamente un ganador;
5. adquisición en distinto orden -> no deadlock;
6. request bloqueada esperando índice/reserva hasta commit;
7. request esperando que gana cuando la primera transacción hace rollback;
8. rollback completo después de escrituras parciales.

## 19.3 Seguridad

Conservar tests equivalentes para:

- access control;
- CSRF;
- bad Origin;
- rate limiting;
- spoofed forwarded headers;
- cookies Secure/HttpOnly/SameSite;
- headers de seguridad;
- body demasiado grande;
- SQL injection mediante tipos manipulados;
- strict schemas;
- admin sin autenticación;
- password hashing;
- no exposición accidental de input en errores.

## 19.4 Configuración

Conservar tests que producción no arranca con secretos inseguros/faltantes.

---

# 20. Tooling y calidad

Portar la disciplina del proyecto original:

```text
pytest
ruff
black
mypy --strict
bandit
pip-audit
```

Mantener comandos Make equivalentes:

```text
make test
make test-unit
make test-integration
make test-concurrency
make lint
make format
make typecheck
make security-check
make check
```

Ajustar nombres del test DB y project name a FormManager.

Antes de cerrar cada hito, ejecutar como mínimo las verificaciones afectadas.

No dejar el proyecto en estado donde «los tests viejos se quitaron porque molestaban» sin reemplazarlos por tests genéricos equivalentes.

---

# 21. OpenAPI y documentación interactiva

El prototipo deshabilita `docs_url`, `redoc_url` y `openapi_url` porque era una app temporal cerrada.

FormManager es headless-first, por lo que una especificación OpenAPI puede ser útil.

Durante la migración:

- no exponer documentación interactiva públicamente por accidente en producción;
- sí permitir generar OpenAPI para desarrollo/SDKs si el nuevo diseño lo requiere;
- hacer esta decisión configurable y documentada.

No considerar el hecho de que TeamRegistration deshabilitaba OpenAPI como un requisito eterno del producto.

---

# 22. Creación y carga segura de form packages

Cuando se implemente el Form Loader:

- validar `schema_version`;
- rechazar propiedades desconocidas;
- detectar IDs duplicados;
- detectar referencias a resources inexistentes;
- detectar rules inválidas;
- resolver rutas de forma segura;
- prevenir `../` path traversal;
- no seguir symlinks fuera de `FORMS_DIR` sin una política explícita;
- no considerar válido un directorio solo porque existe.

Creación de nuevos forms:

```text
/forms/.tmp-<id>/
        ↓
escribir
        ↓
validar todo
        ↓
rename atómico
        ↓
/forms/<id>/
```

Nunca publicar un form parcialmente escrito.

---

# 23. Filesystem y PostgreSQL: división definitiva

Mantener esta regla durante todo el rebase:

```text
Filesystem = definición
PostgreSQL = runtime/state
```

Filesystem:

- `form.toml`;
- `elements.toml`;
- `resources.toml`;
- `rules.json`;
- static resources;
- assets;
- custom UI.

PostgreSQL:

- registry/cache mínimo de forms;
- versions/runtime references;
- submissions;
- typed values;
- reservations;
- mutable transactional state;
- admin sessions;
- audit.

Nunca usar `responses.json`/`responses.csv` como fuente de verdad de submissions activas.

---

# 24. Reglas sobre JavaScript durante la migración

El JS Runner NO debe incorporarse al Core simplemente porque es fácil ejecutar `node`, `eval`, `exec`, `subprocess` o una librería embebida.

Cuando llegue su hito:

- contenedor/runtime separado;
- opcional mediante profile;
- sin DB;
- sin secretos;
- sin Docker socket;
- sin input del respondiente;
- sin network por defecto;
- sin filesystem por defecto salvo paths explícitos;
- CPU/RAM/PID/time limits;
- output serializado;
- output validado por Core;
- solo produce datasets.

Hasta entonces, soportar únicamente static resources.

---

# 25. Política de commits/migración

Cada hito debe ser pequeño y revisable.

Claude NO debe implementar en una sola tanda:

```text
Form Loader + Resources + Rules Engine + JS Runner + Builder + Custom UI
```

Seguir los hitos entregados por el usuario.

En cada hito:

1. analizar el estado actual;
2. listar qué archivos tocará;
3. implementar únicamente el alcance solicitado;
4. añadir/actualizar tests;
5. correr tests;
6. correr lint/typecheck relevantes;
7. documentar decisiones nuevas;
8. no adelantarse a hitos futuros.

Si una función futura exige una interfaz, diseñar un seam limpio, pero no implementar prematuramente la función futura.

---

# 26. Matriz de migración archivo por archivo

| Origen TeamRegistration | Acción | Destino / regla |
|---|---|---|
| `app/config.py` | REFACTOR | `Settings` genérico; borrar constantes escolares |
| `app/db/base.py` | KEEP/RENAME | conservar naming conventions |
| `app/db/session.py` | KEEP/GENERALIZE | `application_name=formmanager` |
| `app/logging_setup.py` | KEEP/HARDEN | ampliar sensitive keys |
| `app/main.py` | REFACTOR | título/rutas/services genéricos; `/api/v1` |
| `app/middleware.py` | KEEP/ADAPT | conservar límites/headers/logging |
| `app/web.py` | REFACTOR | templates builtin genéricos, services container modular |
| `app/security/csrf.py` | KEEP | mismas garantías |
| `app/security/passwords.py` | KEEP | Argon2id + dummy hash |
| `app/security/rate_limit.py` | KEEP/GENERALIZE | buckets por form/action |
| `app/security/sessions.py` | PARTIAL REFACTOR | admin casi intacto; public state genérico |
| `app/models/admin_session.py` | KEEP | puede conservarse |
| `app/models/audit.py` | KEEP/GENERALIZE | acciones genéricas |
| `app/models/settings.py` | REPLACE | no singleton global `registration_open` |
| `app/models/student.py` | DELETE | reemplazado por Resources |
| `app/models/topic.py` | DELETE | opciones/resources genéricos |
| `app/models/team.py` | DELETE | reemplazado por Submission |
| `app/models/team_member.py` | DELETE | reemplazado por values/reservations |
| `app/schemas/registration.py` | REPLACE | schemas genéricos |
| `app/services/registration.py` | REDESIGN | extraer transacciones/concurrencia a Submission/Reservation services |
| `app/services/admin.py` | REFACTOR | admin genérico; conservar audit y CSV hardening |
| `app/routes/api.py` | REPLACE | API versionada por form |
| `app/routes/public.py` | REFACTOR | runtime builtin genérico |
| `app/routes/admin.py` | REFACTOR | lista/forms/submissions/resources |
| `app/seed.py` | REPLACE | init genérico; no datasets privados |
| `app/seed_data.py` | DO NOT COPY | contiene datos específicos/personales |
| `app/templates/*` | REPLACE | UI builtin genérica |
| `app/static/*` | REUSE SELECTIVELY | solo componentes/UX no específicos |
| `alembic/0001...` | DO NOT COPY AS HISTORY | crear nueva `0001` de FormManager |
| `docker/postgres/10-app-role.sh` | KEEP | actualizar nombres defaults |
| `docker/entrypoint.sh` | KEEP/ADAPT | migrate + generic init + serve |
| `Dockerfile` | KEEP/ADAPT | nombre/proyecto; writable data mount explícito |
| `docker-compose.yml` | KEEP/ADAPT | nombre FormManager, data volume, misma segmentación |
| `docker-compose.test.yml` | KEEP/ADAPT | DB test genérica |
| `Caddyfile` | KEEP/ADAPT | misma postura de proxy/TLS |
| `scripts/backup.sh` | KEEP/ADAPT | DB FormManager; documentar forms dir backup por separado |
| `scripts/restore.sh` | KEEP/ADAPT | restauración genérica |
| `scripts/smoke_test.*` | REWRITE | flujo genérico con fixtures falsos |
| `tests/test_concurrency.py` | REWRITE, PRESERVE PATTERNS | generic reservations |
| `tests/test_security.py` | REWRITE, PRESERVE GUARANTEES | sin datos reales |
| `tests/test_registration.py` | REPLACE | submission engine tests |
| `tests/test_admin.py` | REFACTOR | forms/submissions generic admin |
| `tests/test_seed.py` | REPLACE | form/init idempotency |
| `tests/test_unit.py` | REFACTOR | element/resource/rule validation |
| `README.md` | REWRITE | producto FormManager |
| `SECURITY.md` | REWRITE USING SAME THREAT DISCIPLINE | riesgos de generic/headless/resources |
| `DEPLOY_AZURE.md` | GENERALIZE | despliegue FormManager, no una noche/clase |
| `Makefile` | KEEP/ADAPT | mismo quality gate |
| `pyproject.toml` | KEEP/ADAPT | nombre `formmanager`; strict quality |

---

# 27. Backups: cambio importante

TeamRegistration solo necesita respaldar PostgreSQL.

FormManager tendrá definición en filesystem y estado en PostgreSQL.

Por tanto un backup completo futuro deberá contemplar **ambos**:

```text
PostgreSQL dump
FORMS_DIR
SITE_DIR si existe
```

No mezclar secretos `.env` dentro de exports de formularios.

Durante los primeros hitos, documentar claramente qué está cubriendo el backup existente y qué todavía no.

---

# 28. Criterio de éxito del rebase

La migración se considera arquitectónicamente correcta cuando el caso TeamRegistration puede reconstruirse como un **formulario de ejemplo** sin código Python específico.

Debe poder expresarse aproximadamente mediante:

```text
form.toml
    -> título, límites, estado/acceso

elements.toml
    -> representante, integrante2, integrante3, integrante4, tema

resources.toml
    -> alumnos ficticios / temas

rules.json
    -> los cuatro deben ser distintos
    -> alumno/resource item máximo 1 uso global
    -> tema/opción máximo 1 uso global
    -> máximo N submissions
```

Y el Core debe aplicar esas garantías con su modelo genérico de submissions/reservations.

En ese momento deben poder eliminarse definitivamente del Core las palabras/conceptos:

```text
Student
Topic
Team
TeamMember
representative como concepto del sistema
```

`representative` podrá existir únicamente como ID de un elemento definido por un formulario concreto.

---

# 29. Regression gates obligatorios

Antes de aceptar cada etapa de migración, verificar que NO se haya degradado ninguna de estas propiedades:

- app corre como non-root;
- DB no está publicada al host;
- app no está publicada directamente al host;
- app no recibe password de superuser PostgreSQL;
- secrets no están en Git;
- admin usa Argon2id;
- admin session token no se guarda plaintext en DB;
- CSRF sigue activo en mutaciones con cookie auth;
- security headers siguen presentes;
- request body tiene límite;
- logs no contienen secretos/bodies/IPs innecesarios;
- SQLAlchemy usa queries parametrizadas;
- schemas rechazan propiedades inesperadas;
- conflictos concurrentes dependen de DB, no de frontend;
- rollback es completo;
- tests críticos corren sobre PostgreSQL real;
- CSV export no permite formula injection;
- Caddy continúa siendo el único entrypoint público.

Si un hito necesita cambiar una de estas propiedades, Claude debe detenerse, explicar por qué y proponer una alternativa de seguridad equivalente antes de hacerlo.

---

# 30. Lo que Claude NO debe hacer

Durante la migración queda expresamente prohibido:

- copiar `seed_data.py` al nuevo repo;
- introducir los nombres reales en fixtures, demos o docs;
- conservar `MAX_TEAMS=11`, `TEAM_SIZE=4` o `TOTAL_STUDENTS=44` como conceptos del Core;
- usar SQLite para validar concurrencia crítica;
- convertir todos los valores de submissions a strings por comodidad;
- permitir propiedades desconocidas silenciosamente en definitions;
- ejecutar JS arbitrario dentro de FastAPI;
- usar `eval()` para rules o resources;
- confiar en validación del frontend;
- exponer PostgreSQL;
- montar `/var/run/docker.sock`;
- ejecutar el Core como root sin necesidad demostrable;
- permitir CORS `*` por defecto;
- deshabilitar CSRF para «hacer funcionar» custom UI;
- almacenar passwords en plaintext;
- devolver errores crudos de PostgreSQL;
- romper los quality gates y simplemente borrar tests;
- implementar hitos futuros no solicitados;
- hacer un «big bang rewrite» sin checkpoints.

---

# 31. Orden recomendado para iniciar el nuevo repositorio

Para el primer trabajo de Claude en el repo nuevo:

1. Copiar únicamente la infraestructura reusable y seguridad base.
2. Renombrar el package/project a FormManager.
3. Eliminar inmediatamente cualquier dominio TeamRegistration.
4. Crear tests mínimos de infraestructura y seguridad.
5. Dejar el Core arrancando sin ningún formulario hardcodeado.
6. Introducir `FORMS_DIR`.
7. Implementar después el Hito de Form Package/Form Loader.

No empezar portando `Student`, `Topic`, `Team` ni `register_team()`.

La primera versión arrancable del nuevo repo debe poder mostrar algo equivalente a:

```text
FormManager Core running
0 forms loaded
Database healthy
```

sin requerir datos escolares para iniciar.

---

# 32. Filosofía final de la migración

TeamRegistration demostró que el enfoque funciona:

- PostgreSQL puede ser la autoridad de concurrencia;
- FastAPI puede mantenerse pequeño;
- Docker puede aislar correctamente los servicios;
- una UI ligera es suficiente;
- validación estricta evita datos inconsistentes;
- la seguridad puede mantenerse razonable incluso en un proyecto pequeño.

FormManager debe conservar esas fortalezas sin conservar el caso particular que las originó.

La regla de decisión durante todo el rebase es:

> **Si una pieza existe porque es necesaria para cualquier motor de formularios seguro, se generaliza y se conserva. Si existe porque había 44 alumnos formando 11 equipos para elegir 11 temas, se elimina del Core y, como máximo, se convierte en un ejemplo sintético.**

