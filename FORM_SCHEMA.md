# Form package y `form.toml` (schema_version 1)

Este documento describe **solo el contrato implementado en el Hito 1**. Lo que no aparece aquí no existe todavía.

## Paquete

```text
FORMS_DIR/
└── <form-id>/            nombre del directorio = id de form.toml
    ├── form.toml         obligatorio, validado semánticamente (abajo)
    ├── elements.toml     obligatorio, solo validación sintáctica
    ├── resources.toml    obligatorio, solo validación sintáctica
    ├── rules.json        obligatorio, solo validación sintáctica
    ├── resources/        opcional, no se lee
    ├── assets/           opcional, no se lee
    └── ui/               opcional, no se lee
```

Reglas estructurales:

- Solo se examinan los hijos directos de `FORMS_DIR`. No hay formularios anidados.
- Las entradas que empiezan por `.` se ignoran (incluidos los directorios de preparación `.tmp-*` del creador interno). Los archivos sueltos también.
- Ningún enlace simbólico dentro de la frontera del paquete: ni el directorio, ni los cuatro archivos, ni `resources/`, `assets/`, `ui/`.
- Los cuatro archivos deben ser archivos regulares (no directorios, FIFOs, sockets ni dispositivos), UTF-8 válido y de tamaño ≤ `FORM_DEFINITION_MAX_BYTES` (1 MiB por defecto). El tamaño se comprueba antes de leer y de parsear.
- `resources/`, `assets/` y `ui/`, si existen, deben ser directorios. Su contenido no se interpreta.

## `form.toml`

```toml
schema_version = 1
id = "K8mP4qT2xN7rV5sA"
slug = "workshop-registration"
title = "Inscripción a taller"
subtitle = "Formulario de inscripción"   # opcional
description = """
Elige **un horario**.
"""                                       # opcional
status = "draft"
```

| Clave | Obligatoria | Regla |
|---|---|---|
| `schema_version` | sí | Entero exactamente `1` (`true`, `1.0` o `"1"` se rechazan). |
| `id` | sí | `^[A-Za-z0-9_-]{16}$`. Debe ser idéntico al nombre del directorio. Opaco, no secreto, no secuencial. |
| `slug` | sí | `^[a-z0-9]+(?:-[a-z0-9]+)*$`, 1-80 caracteres. Único en la instancia. |
| `title` | sí | Texto no vacío (no solo espacios), ≤ 200 caracteres, sin caracteres de control. |
| `subtitle` | no | ≤ 300 caracteres, sin caracteres de control. |
| `description` | no | ≤ 20 000 caracteres; se permiten saltos de línea y tabuladores, ningún otro carácter de control. |
| `status` | sí | `draft`, `open`, `paused`, `closed` o `archived`. |

- **Cualquier otra clave es un error** (`UNKNOWN_FORM_PROPERTY`), incluidas tablas como `[submission]`, `[access]` o `[frontend]` que `PROJECT_RULES.md` menciona como dirección futura. Se añadirán al schema cuando su hito defina el contrato.
- `title`, `subtitle` y `description` se conservan como texto fuente. **No se renderiza Markdown** ni se produce HTML en este hito.
- `status` solo se valida, se registra y se expone. **No controla todavía ningún comportamiento ni la visibilidad pública** (ver "Visibilidad" abajo).

## `elements.toml`, `resources.toml`, `rules.json`

Hoy solo se comprueba que existen, son archivos regulares sin symlink, respetan el límite de tamaño, se parsean y declaran `schema_version = 1`:

```toml
# elements.toml y resources.toml
schema_version = 1
```

```json
{ "schema_version": 1, "rules": [] }
```

- `rules.json` debe tener un objeto como raíz. Se rechazan claves duplicadas y `NaN`/`Infinity`.
- El resto del contenido (`[[element]]`, `[[resource]]`, `rules`...) **no se interpreta todavía** y no se valida. Su semántica pertenece a hitos posteriores.

## Duplicados

Si dos paquetes declaran el mismo `slug` (o el mismo `id`), **todos** los participantes quedan inválidos en esa carga. No hay "first wins" ni dependencia del orden del filesystem.

## Diagnósticos

Un paquete inválido no impide arrancar ni afecta a los demás. Cada problema produce un diagnóstico interno `{relative_path, file, code, message}` que se registra en el log (`form_load_failed`). No se expone por API.

Códigos: `INVALID_DIRECTORY_NAME`, `SYMLINK_NOT_ALLOWED`, `MISSING_FILE`, `NOT_A_REGULAR_FILE`, `NOT_A_DIRECTORY`, `FILE_TOO_LARGE`, `UNREADABLE_FILE`, `INVALID_ENCODING`, `INVALID_TOML`, `INVALID_JSON`, `INVALID_JSON_ROOT`, `UNSUPPORTED_SCHEMA_VERSION`, `MISSING_PROPERTY`, `UNKNOWN_FORM_PROPERTY`, `INVALID_PROPERTY`, `INVALID_FORM_ID`, `INVALID_SLUG`, `INVALID_STATUS`, `FORM_ID_MISMATCH`, `DUPLICATE_FORM_ID`, `DUPLICATE_SLUG`.

## Visibilidad

En el Hito 1, `GET /api/v1/forms` devuelve el **catálogo cargado**: todo formulario válido, sea cual sea su `status` (incluido `draft`). Esto **no** define la política pública final. Los estados todavía no controlan la exposición; el hito de publicación/acceso decidirá qué estados son visibles públicamente.

## Carga

Los paquetes se cargan al arrancar. No hay watcher ni hot reload: un cambio en disco se aplica al reiniciar la app (o mediante `FormCatalog.reload()` interno).
