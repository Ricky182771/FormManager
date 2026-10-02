# FormManager: arquitectura (Hito 2)

Este documento describe **lo que existe** tras el Hito 2. Los principios y el diseño futuro están en `PROJECT_RULES.md` y `REBASE.md`; aquí no se repiten. El contrato de `form.toml` está en [`FORM_SCHEMA.md`](FORM_SCHEMA.md) y el de `elements.toml` en [`ELEMENTS_SCHEMA.md`](ELEMENTS_SCHEMA.md).

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

| Almacén | Contenido |
|---|---|
| Filesystem (`FORMS_DIR`) | **Fuente canónica** de la definición: un paquete por formulario (`form.toml`, `elements.toml`, `resources.toml`, `rules.json`, directorios opcionales). |
| PostgreSQL | `admin_sessions`, `admin_audit_log`, `forms_registry` (índice mínimo de formularios válidos cargados), `alembic_version`. |

`forms_registry` no guarda definiciones: solo `id`, `slug`, `relative_path`, `schema_version`, `title`, `status`, `updated_at`. No hay tablas de submissions, reservations, resources ni versiones.

## Módulos

```text
app/
├── main.py            create_app(): servicios, middleware, routers, errores; lifespan carga el catálogo
├── config.py          Settings de instancia (incluye FORM_DEFINITION_MAX_BYTES)
├── storage.py         prepare_forms_dir(): el directorio existe y es usable (no lo lee)
├── forms/
│   ├── package.py     regex de ID/slug, new_form_id(), FormDocument (form.toml), FormPackage
│   ├── diagnostics.py DiagnosticCode, Diagnostic, safe_name()
│   ├── elements.py    ElementsSchema y modelos inmutables de elementos; parser manual de elements.toml
│   ├── answers.py     validate_answers(): validación local y pura de un payload de respuestas
│   ├── fsutil.py      primitivas de filesystem seguras (dir_fd + O_NOFOLLOW); únicas en usar os.open
│   ├── loader.py      discovery, validación estructural, resolución de duplicados
│   ├── catalog.py     CatalogSnapshot inmutable + FormCatalog.reload()
│   ├── registry.py    sync filesystem → forms_registry
│   └── creator.py     create_form_package() interno y atómico (sin endpoint)
├── models/            AdminSession, AdminAuditLog, FormRegistryEntry
├── routes/            health, public (/), admin (/admin/*), api (/api/v1/forms...)
├── web.py             contenedor Services (incluye catalog), sesión DB, plantillas
└── ...                logging_setup, middleware, wait_for_db, db/, security/, services/audit.py
```

## Arranque

```text
python -m app.wait_for_db     (backoff 0.5s → 5s, deadline 90s)
alembic upgrade head          (0001 → 0002)
create_app(): prepare_forms_dir(FORMS_DIR)   (falla el arranque si no es usable)
lifespan: FormCatalog.reload()
    scan FORMS_DIR → validar paquetes → rechazar duplicados → sync forms_registry → publicar snapshot
uvicorn --workers 1 --proxy-headers
```

- Sin formularios, arranca con 0.
- Un paquete inválido es solo un diagnóstico (log `form_load_failed`); no tumba la instancia ni a otros paquetes.
- Un fallo de la sync con PostgreSQL **aborta el arranque**: no se sirve con filesystem y registry divergentes, y nunca se presenta como "formulario inválido".

## Form Loader

**Discovery.** Abre `FORMS_DIR` con `O_DIRECTORY|O_NOFOLLOW` y lista sus hijos directos, ordenados por nombre. Ignora entradas que empiezan por `.` (incluido `.tmp-*`) y archivos sueltos. Un symlink en la raíz produce `SYMLINK_NOT_ALLOWED`; un directorio cuyo nombre no es un ID válido, `INVALID_DIRECTORY_NAME`.

**Validación de un paquete** (`load_package`, la misma función para el discovery y el creador):

1. El nombre del directorio debe ser un ID válido.
2. Se abre con `openat(O_DIRECTORY|O_NOFOLLOW)` relativo al padre.
3. `resources/`, `assets/` y `ui/`: si existen, directorios reales (sin symlink). No se leen.
4. Cada archivo de definición: `lstat` sin seguir symlinks → archivo regular → tamaño ≤ límite → `openat(O_NOFOLLOW|O_NONBLOCK)` → `fstat` confirma el mismo inode → lectura acotada a límite+1 bytes → UTF-8 → `tomllib`/`json`.
5. `form.toml` con `FormDocument` (pydantic, `extra="forbid"`, strict); los otros tres, `schema_version == 1`; además `elements.toml` con `parse_elements` (parser manual, ver abajo).
6. `form.toml.id` debe coincidir con el nombre del directorio.

Se recogen todos los diagnósticos del paquete (máximo 20 por archivo). Cada archivo se lee una sola vez por carga; el `ElementsSchema` resultante pasa a `FormPackage.elements` y el contenido de resources/rules se descarta tras comprobarlo.

**Duplicados.** Índices por `id` y por `slug` (O(N)). Todos los participantes de una colisión quedan inválidos (`DUPLICATE_SLUG` / `DUPLICATE_FORM_ID`).

**Plataforma.** Las primitivas de `app/forms/fsutil.py` requieren Linux/POSIX (`dir_fd`, `O_NOFOLLOW`, `O_DIRECTORY`, `renameat`). Es la plataforma soportada del runtime v1 (imagen Docker). No hay capa de compatibilidad con Windows.

## Elements Schema y validación de respuestas

Contrato completo: [`ELEMENTS_SCHEMA.md`](ELEMENTS_SCHEMA.md).

- **Modelo.** Dataclasses `frozen`/`slots`, una por familia de tipo (`TextElement` para `text`/`text_long`, `IntegerElement`, `DecimalElement`, `BooleanElement`, `EmailElement`, `UrlElement`, `DateElement`, `TimeElement`, `DateTimeElement`, `SelectElement`, `MultiSelectElement`), unidas en el tipo `Element`. `ElementsSchema` guarda la tupla en orden de declaración y un `by_id` de solo lectura.
- **Parser.** Manual y explícito (no pydantic): cada `[[element]]` se contrasta con una lista blanca de propiedades por tipo, lo que distingue una propiedad desconocida de una que no aplica al tipo. Informa de todos los problemas de cada elemento.
- **`validate_answers(schema, payload)`.** Componente separado del loader, puro: no persiste, no consulta PostgreSQL, Resources ni Rules. Devuelve `ValidationResult(valid, values, errors)` con valores canónicos tipados o errores estructurados (como mucho uno por elemento, 20 en total). No tiene consumidor HTTP todavía.
- Nada de esto está en la API ni en PostgreSQL: los elementos viven en filesystem → parser → memoria. No hay migración nueva.

## Catálogo

`FormCatalog` vive en `app.state.services.catalog`. Lecturas: `forms()` (ordenados por slug), `get_by_id()`, `get_by_slug()`, `count`, `diagnostics`.

`reload()`: un `threading.Lock` serializa recargas; construye un `CatalogSnapshot` nuevo (tuplas y `MappingProxyType`, inmutables), sincroniza el registry y solo entonces sustituye la referencia. Un lector siempre ve un snapshot completo. Si la sync falla, el snapshot anterior permanece y el error se propaga.

No hay watcher ni hot reload. `reload()` es interno; no hay endpoint que lo dispare.

## `forms_registry` y sincronización

Migración `0002_forms_registry` (downgrade: `DROP TABLE`).

| Columna | Tipo | Notas |
|---|---|---|
| `id` | `varchar(16)` PK | CHECK `^[A-Za-z0-9_-]{16}$` |
| `slug` | `varchar(80)` | `UNIQUE DEFERRABLE INITIALLY IMMEDIATE`, CHECK de formato |
| `relative_path` | `varchar(255)` | relativo a `FORMS_DIR` (hoy igual al ID); CHECK: no vacío, no empieza por `/`, sin `..` |
| `schema_version` | `smallint` | CHECK ≥ 1 |
| `title` | `varchar(200)` | |
| `status` | `varchar(16)` | CHECK en los cinco estados |
| `updated_at` | `timestamptz` | última vez que **cambió la metadata** de la fila (inserción o actualización) |

`updated_at` no es "última carga": una sync sin cambios no escribe nada, y así es idempotente de verdad. PostgreSQL es la única fuente de tiempo: `DEFAULT now()` al insertar y `SET updated_at = now()` al actualizar.

Algoritmo (`sync_registry`, una transacción):

1. `LOCK TABLE forms_registry IN SHARE ROW EXCLUSIVE MODE` (syncs concurrentes se serializan).
2. `SET CONSTRAINTS uq_forms_registry_slug DEFERRED` (permite intercambiar slugs entre dos formularios).
3. Borra las filas cuyo ID ya no es un formulario válido.
4. En orden de ID: inserta las nuevas, actualiza solo las que cambiaron.
5. `COMMIT` (la unicidad de slug se comprueba aquí). Cualquier error → rollback completo y propagación.

**Política de borrado (solo Hito 1):** un formulario que desaparece o pasa a ser inválido se elimina del registry, porque todavía no lo referencia nada. Deberá revisarse cuando existan submissions o estado histórico.

## Creación interna de paquetes

`create_form_package(forms_dir, slug=..., title=..., ...)`, sin endpoint HTTP ni UI:

```text
validar entradas con FormDocument → ID con secrets → comprobar slug libre y ID inexistente
FORMS_DIR/.tmp-<random>/<id>/   escribir los 4 archivos (O_CREAT|O_EXCL, fsync)
load_package(.tmp-<random>, <id>)   el mismo validador estricto que el discovery
renameat(.tmp-<random>/<id> → FORMS_DIR/<id>)   mismo filesystem, atómico
rmdir .tmp-<random>
```

Ante cualquier fallo se borra el directorio de preparación. Nunca se sobrescribe un paquete existente. El catálogo solo ve el formulario nuevo tras un `reload()`. La unicidad del slug no es segura frente a dos creaciones concurrentes: el futuro admin deberá serializarlas.

## HTTP

| Ruta | Descripción |
|---|---|
| `GET /health` | `{"status":"ok","database":"ok"}` o `503`. |
| `GET /` | Estado: Core, base de datos, formularios cargados (N). |
| `GET/POST /admin/login`, `POST /admin/logout`, `GET /admin` | Admin mínimo; el panel muestra el mismo contador. |
| `GET /api/v1/forms` | Formularios válidos, **ordenados por slug** (único y estable). Campos: `id`, `slug`, `title`, `status`, `schema_version`. |
| `GET /api/v1/forms/{slug}` | Metadata de un formulario: lo anterior + `subtitle`, `description` (texto fuente). `404 FORM_NOT_FOUND` si no existe. |
| `/docs`, `/redoc`, `/openapi.json` | Deshabilitados. |

No existen `POST /api/v1/forms`, `/definition`, `/elements`, `/resources` ni `/submissions`. La API nunca devuelve rutas del filesystem ni contenido de elements/resources/rules.

**Visibilidad:** la lista refleja el catálogo cargado, incluidos formularios `draft`. No es la política pública final; ver `FORM_SCHEMA.md`.

### Errores

```json
{"error": {"code": "FORM_NOT_FOUND", "message": "El formulario no existe."}}
```

Códigos: `BAD_REQUEST`, `UNAUTHENTICATED`, `FORBIDDEN`, `NOT_FOUND`, `FORM_NOT_FOUND`, `METHOD_NOT_ALLOWED`, `PAYLOAD_TOO_LARGE`, `VALIDATION_ERROR`, `RATE_LIMITED`, `INTERNAL_ERROR`, `SERVICE_UNAVAILABLE`. Nunca trazas, SQL, DSN ni rutas internas.

## Logging del loader

`form_load_started`, `form_loaded` (`form_id`, `slug`, `relative_path`), `form_load_failed` (`relative_path`, `file`, `error_code`, `detail`), `form_registry_synced` (`registry_inserted/updated/deleted`), `form_registry_sync_failed` (`error_type`), `form_catalog_loaded` (`forms_valid`, `forms_invalid`). Nunca el contenido de los archivos ni rutas absolutas.

## Base de datos

- SQLAlchemy 2.x, naming convention determinista (`pk_`, `uq_`, `ix_`, `fk_`, `ck_`).
- Engine con `pool_pre_ping`, timeouts de conexión, sentencia y lock.
- Historia Alembic: `0001` (admin), `0002` (forms_registry), ambas con downgrade. Un test comprueba que modelos y migraciones no divergen.

## UI provisional

Plantillas Jinja2 sin JavaScript, borrador sin dirección visual (ENERGY 1 / RHYTHM 1 / MOTION 1). En el Hito 1 solo cambió el contador y el texto del estado vacío.

## Preparado para el Hito 2

- `FormPackage.elements` + `validate_answers` son la base de la futura API de definición y de submissions: el endpoint solo tendrá que parsear JSON (con `parse_float` estricto) y llamar al validador.
- `load_package` es el punto donde se añadirá la validación semántica de resources/rules, con los mismos diagnósticos.
- `get_by_slug` queda listo para `/f/{slug}` y para endpoints de definición.

## Diferido

| Pieza | Hito |
|---|---|
| `resource_select` / `resource_multi_select` (hoy `UNSUPPORTED_ELEMENT_TYPE`) | Hito de Resources |
| `pattern` en elementos (diferido por riesgo de ReDoS) | Hito propio |
| Exposición de elementos por API, serialización JSON de valores canónicos | Hito de API de definición / submissions |
| Resources, Rules Engine, Submissions, reservations, FormVersion | Posteriores |
| Política de visibilidad por `status`, acceso por formulario | Hito de publicación/acceso |
| Markdown renderizado | Hito de Markdown |
| Endpoint/UI de creación, edición y borrado de formularios | Admin genérico |
| Recarga sin reinicio (endpoint admin o señal) | Por definir |
| Valor exclusivo, reservas, rollback de escrituras parciales, retries 40001/40P01 | Hito de Submissions/Rules/Reservations |
| Exportación CSV con neutralización de fórmulas | Hito de exportación |
| `SITE_DIR` / página de inicio personalizada | Hito de frontends custom |
