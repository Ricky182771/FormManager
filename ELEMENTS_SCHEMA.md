# `elements.toml` (schema_version 1)

Este documento describe **el contrato implementado en el Hito 2**: qué datos acepta un formulario y cómo se validan y canonicalizan sus respuestas. Lo que no aparece aquí no existe. El paquete y `form.toml` están en [`FORM_SCHEMA.md`](FORM_SCHEMA.md).

`elements.toml` describe datos, no presentación: no hay colores, CSS, layout, iconos, widgets ni tamaños. Los tipos son semánticos (`boolean`, no `checkbox`). Tampoco describe reglas entre campos, cupos ni reservas: eso pertenece a `rules.json` en un hito posterior.

## Raíz

```toml
schema_version = 1   # obligatorio: entero exactamente 1 (true, 1.0 o "1" se rechazan)

[[element]]          # opcional: 0 a 200 elementos
# ...
```

- Cualquier otra clave en la raíz es un error (`INVALID_ELEMENTS_SCHEMA`). `element` debe ser un array de tablas.
- **Cero elementos es válido** (un borrador; es lo que escribe el creador interno). Más de 200 → `TOO_MANY_ELEMENTS`.

## Propiedades comunes

| Clave | Obligatoria | Regla |
|---|---|---|
| `id` | sí | `^[a-z][a-z0-9]*(?:[_-][a-z0-9]+)*$`, 1-64 caracteres ASCII. Empieza por letra; sin puntos, barras, espacios, Unicode, separadores consecutivos ni separador final. Único en el formulario (comparación exacta: `a_b` y `a-b` son distintos). |
| `type` | sí | Uno de los tipos de abajo. |
| `label` | sí | No vacío ni solo espacios, ≤ 200 caracteres, sin caracteres de control. Texto fuente (el Markdown no se interpreta todavía). |
| `required` | **sí** | `true` o `false`, booleano real. No hay valor por defecto. |
| `description` | no | Si aparece: no vacío ni solo espacios, ≤ 2000 caracteres; se permiten LF y TAB, ningún otro carácter de control. Texto fuente. |

El `id` es la identidad del dato; cambiar el `label` no cambia su significado. No existen `default`, `placeholder`, `help_url`, `kind` ni metadata extensible: son propiedades desconocidas.

## Tipos

| `type` | Entrada JSON aceptada | Propiedades propias | Valor canónico (Python) | Serialización prevista |
|---|---|---|---|---|
| `text` | string de una línea | `min_length`, `max_length`, `normalize` | `str` | string |
| `text_long` | string multilínea | `min_length`, `max_length`, `normalize` | `str` | string |
| `integer` | número entero JSON | `min`, `max` | `int` | número |
| `decimal` | **string** | `decimal_places` (obligatoria), `min`, `max` | `Decimal` | string de punto fijo (`"12.50"`) |
| `boolean` | `true` / `false` | — | `bool` | `true` / `false` |
| `email` | string | `normalize` (solo `trim`, `case = "lower"`) | `str` | string |
| `url` | string | — | `str` | string |
| `date` | string `YYYY-MM-DD` | `min`, `max` | `datetime.date` | `"2026-10-02"` |
| `time` | string `HH:MM` o `HH:MM:SS` | `min`, `max` | `datetime.time` | `"18:30:00"` |
| `datetime` | string RFC 3339 con offset | `min`, `max` | `datetime` en UTC | `"2026-10-03T00:30:00Z"` |
| `select` | string (un `value`) | `options` | `str` | string |
| `multi_select` | array de strings | `options`, `min_selected`, `max_selected` | `tuple[str, ...]` | array |
| `resource_select` | — | — | — | — |
| `resource_multi_select` | — | — | — | — |

La serialización JSON de los valores canónicos se fijará con la API que los exponga; la columna indica la forma ya decidida.

**Tipos respaldados por recursos.** `resource_select` y `resource_multi_select` forman parte de la dirección v1 pero **no son utilizables todavía**: requieren el subsistema Resources. Si aparecen, el paquete es inválido con `UNSUPPORTED_ELEMENT_TYPE`. Ninguna propiedad suya (`resource = ...`) está definida.

**Widgets.** `checkbox`, `radio`, `dropdown`, `toggle`, `textarea`, `date-picker`... son presentación: `UNKNOWN_ELEMENT_TYPE`.

## Restricciones por tipo

Una propiedad conocida que no aplica al tipo es un error, nunca se ignora (`email` con `min = 10` → `INVALID_CONSTRAINT`).

| Propiedad | Tipos | Valor en TOML | Reglas del schema |
|---|---|---|---|
| `min_length`, `max_length` | `text`, `text_long` | entero | 1 ≤ valor ≤ máximo duro del tipo; `min_length ≤ max_length`. |
| `min`, `max` | `integer` | entero | Dentro de int64; `min ≤ max`. |
| `decimal_places` | `decimal` | entero | Obligatoria, 0-18. |
| `min`, `max` | `decimal` | **string** con la gramática decimal | Como máximo `decimal_places` decimales y 38 dígitos; `min ≤ max`. |
| `min`, `max` | `date` | fecha local TOML (`2026-01-01`) | No strings ni datetimes. |
| `min`, `max` | `time` | hora local TOML (`08:00:00`) | Sin fracciones de segundo. |
| `min`, `max` | `datetime` | offset datetime TOML (`2026-10-02T08:00:00-06:00`) | Con offset (uno naive es inválido), sin fracciones; se guarda en UTC. |
| `options` | `select`, `multi_select` | array de tablas | Ver Opciones. |
| `min_selected`, `max_selected` | `multi_select` | entero | 1 ≤ valor ≤ número de opciones; `min ≤ max`. |
| `normalize` | `text`, `text_long`, `email` | tabla | Ver Normalización. |

Todas las comparaciones son **inclusivas**. Un booleano nunca cuenta como entero.

**`pattern` está diferido.** No forma parte de Elements v1: el módulo `re` de Python no ofrece garantía contra backtracking catastrófico (ReDoS) y no se acepta un motor parcial. Declararlo produce `UNSUPPORTED_ELEMENT_PROPERTY`; no existe el error de respuesta `PATTERN_MISMATCH`. Se diseñará en un hito propio.

## Opciones

```toml
[[element]]
id = "session"
type = "select"
label = "Sesión"
required = true

[[element.options]]
value = "am"
label = "Matutina"

[[element.options]]
value = "pm"
label = "Vespertina"
```

- Entre 1 y 200 opciones; cada una solo `value` y `label`.
- `value`: string `^[a-z0-9]+(?:[_-][a-z0-9]+)*$`, 1-64 caracteres (puede empezar por dígito: `2026`). Nunca entero ni booleano. Duplicado → `DUPLICATE_OPTION_VALUE`.
- `label`: misma regla que el label del elemento. Duplicado dentro del mismo elemento → `DUPLICATE_OPTION_LABEL` (opciones visualmente indistinguibles).
- El orden es el de declaración. La respuesta almacena el `value`, nunca el `label`.

## Normalización

```toml
[element.normalize]
trim = true                  # booleano
collapse_whitespace = true   # booleano
case = "upper"               # "lower" | "upper"
```

| Tipo | Claves permitidas |
|---|---|
| `text` | `trim`, `collapse_whitespace`, `case` (`lower`/`upper`) |
| `text_long` | `trim`, `case` (`collapse_whitespace` destruiría los saltos de línea) |
| `email` | `trim`, `case = "lower"` |

Cualquier otra clave, valor o tipo → `INVALID_NORMALIZATION`. No existen autocorrección, fuzzy matching, eliminación de acentos, transliteración ni extracción de números.

**Orden fijo**, independiente del orden en el TOML: `trim` → `collapse_whitespace` → `case`.

- `trim`: `str.strip()`; elimina el espacio en blanco Unicode inicial y final (incluidos NBSP y U+3000).
- `collapse_whitespace`: cada racha de espacio en blanco Unicode (`\s`, el mismo conjunto que `str.isspace()`) se sustituye por un espacio U+0020. Sin `trim`, puede quedar un espacio inicial o final.
- `case`: `str.lower()` / `str.upper()`, mapeo Unicode completo e independiente del locale. Puede cambiar la longitud (`"ß".upper()` → `"SS"`, `"İ".lower()` → `"i̇"`).

## Canonicalización estructural

Forma parte del tipo, no es configurable y no es "normalización de negocio":

| Tipo | Canonicalización |
|---|---|
| `text`, `text_long` | Unicode **NFC** al final (`e` + acento combinado → `é`). |
| `text_long` | `\r\n` y `\r` → `\n`, antes de validar caracteres. |
| `time` | `HH:MM` → `HH:MM:00`. |
| `datetime` | Conversión a UTC; el offset original no se conserva. Sin segundos → `:00`. |
| `decimal` | Exactamente `decimal_places` decimales (`"12.5"` → `12.50`); `-0` → `0`. Nunca redondea. |
| `multi_select` | Orden de declaración de las opciones; el orden del cliente no tiene significado. |

`email` y `url` no se canonicalizan: el valor validado se guarda tal cual (salvo la normalización que declare el autor en `email`).

## Pipeline de validación de una respuesta

Para cada elemento, en este orden. El primer paso que falla produce el único error del elemento.

1. **Tipo estructural de entrada.** `null` nunca es válido (`INVALID_TYPE`).
2. **Ausencia semántica.** Para los tipos que llegan como string, un string cuyo `strip()` es vacío (`""`, `"   "`, `"\t"`) es "sin respuesta". Para `multi_select`, `[]`. Se decide sobre el string recibido, antes de las reglas de caracteres: `"\t"` en un `text` es "sin respuesta", no `INVALID_CHARACTERS`. Ninguna normalización ni canonicalización posterior puede convertir un valor no vacío en vacío, así que el resultado es el mismo que decidirlo tras normalizar.
3. **Canonicalización estructural previa** (`text_long`: saltos de línea).
4. **Caracteres estructuralmente permitidos.**
5. **Normalización explícita** (`trim` → `collapse_whitespace` → `case`).
6. **Canonicalización Unicode final** (NFC en `text`/`text_long`).
7. **Formato del tipo** (email, URL, fecha, decimal...) y su canonicalización.
8. **Restricciones locales sobre el valor canónico final** (longitud, rango, decimales, número de selecciones). Nunca antes de una transformación que pueda cambiar el valor.
9. Se devuelve el valor canónico.

Excepción de orden sin efecto sobre el valor: en `email` y `url` el máximo de longitud (254 / 2048) se comprueba justo antes de la sintaxis, para no analizar entradas enormes; ninguno de los dos pasos transforma el valor. En `decimal`, el exceso de decimales se informa antes que el límite de 38 dígitos.

### Presencia: ausente, `null`, vacío

| Entrada | `required = true` | `required = false` |
|---|---|---|
| clave ausente | `FIELD_REQUIRED` | se omite de `values` |
| `null` | `INVALID_TYPE` | `INVALID_TYPE` |
| string en blanco (tipos string) | `FIELD_REQUIRED` | se omite de `values` |
| `[]` (`multi_select`) | `FIELD_REQUIRED` | se omite de `values` |
| `false` (`boolean`), `0` (`integer`), `"0"` (`decimal`) | válido | válido |

`required` significa "presente y no vacío", nunca `truthy(value)`: `false` y `0` son respuestas. `required = true` en un `boolean` no exige `true`. Ni `None`, ni `""`, ni `[]` se devuelven jamás como valor canónico: la ausencia es la ausencia de la clave. `min_selected` no convierte en obligatorio un `multi_select` opcional (`[]` sigue siendo "sin respuesta").

### Campos desconocidos

Toda clave del payload que no sea un `id` declarado produce `UNKNOWN_FIELD`; nunca se ignora. El `element_id` del error solo repite la clave si cumple la regex de `id`; en otro caso es `null`.

## Reglas por tipo

### `text` / `text_long`

- `text`: una línea. Rechaza C0 (incluidos CR, LF y TAB), DEL, C1 (U+0080-U+009F) y surrogates sueltos → `INVALID_CHARACTERS`.
- `text_long`: igual, pero LF y TAB están permitidos (tras convertir CR/CRLF a LF).
- Los caracteres de formato Unicode (Cf, p. ej. controles bidi) se permiten: son legítimos en texto RTL.
- Máximo duro: `text` 1000, `text_long` 10 000 code points. Si no se declara `max_length`, se aplica el máximo duro.
- La longitud es `len()` de Python (code points) sobre el valor final. **Nota para frontends:** el `maxlength` de HTML cuenta unidades UTF-16, así que un emoji cuenta 2 allí y 1 aquí. El servidor decide.
- Las respuestas nunca se interpretan como Markdown.

### `integer`

Solo número entero JSON. Se rechazan `"18"`, `18.0`, `1e2`, `true`, `"18 años"` (`INVALID_TYPE`). Rango global int64 con signo (`VALUE_TOO_SMALL`/`VALUE_TOO_LARGE` con `constraint = "int64"`).

### `decimal`

- **Solo string JSON**, para no perder precisión en clientes (JavaScript). Un número JSON → `INVALID_TYPE`.
- Gramática: `^-?(0|[1-9][0-9]*)(\.[0-9]+)?$`, dígitos ASCII. Sin `+`, exponentes, `NaN`, `Infinity`, `.5`, `5.`, ceros a la izquierda, separadores ni espacios → `INVALID_FORMAT`.
- Más decimales que `decimal_places` (contados en el texto recibido, también los ceros finales) → `TOO_MANY_DECIMAL_PLACES`. Nunca se redondea.
- Como máximo **38 dígitos canónicos** (dígitos de la parte entera + `decimal_places`; signo y punto no cuentan). Si se superan → `INVALID_FORMAT`.
- Se usa un contexto `Decimal` local; no depende de la precisión global del proceso.

### `boolean`

Solo `true`/`false`. `"true"`, `"yes"`, `"1"`, `1`, `0` → `INVALID_TYPE`.

### `email`

Subconjunto sintáctico conservador, solo ASCII, sin DNS, sin MX, sin comprobación de existencia:

- parte local *dot-atom* (caracteres `A-Za-z0-9!#$%&'*+/=?^_`` ` ``{|}~-`, sin punto inicial, final ni consecutivo), ≤ 64;
- dominio: una o más etiquetas LDH de 1-63 caracteres sin guion inicial ni final (`user@localhost` es válido; punycode `xn--` se acepta como ASCII normal);
- total ≤ 254 (`TOO_LONG`); el resto de fallos → `INVALID_FORMAT`.
- No se admiten local parts entre comillas, comentarios, IP literales, EAI ni dominios Unicode directos.
- No hay minúsculas implícitas: el autor declara `normalize.case = "lower"` si las quiere.

### `url`

- Absoluta, esquema `http` o `https` (sin distinguir mayúsculas, RFC 3986), host obligatorio, puerto opcional 1-65535.
- Host: nombre LDH (incluido `localhost`), IPv4 literal o IPv6 literal entre `[]` (sin zone ID). Un host totalmente numérico debe ser un IPv4 válido.
- Se rechazan `userinfo@`, otros esquemas, URLs relativas, caracteres fuera del ASCII imprimible, espacios y percent-encoding inválido. Path, query y fragment solo con caracteres de RFC 3986 o `%XX`.
- ≤ 2048 caracteres (`TOO_LONG`); el resto de fallos → `INVALID_FORMAT`.
- Se guarda tal cual, sin normalizar.
- **No es una defensa SSRF.** FormManager no visita la URL. Si una feature futura hace peticiones salientes (webhooks, fetch...), esa feature deberá aplicar su propia política anti-SSRF.

### `date`

Solo `YYYY-MM-DD` con dígitos ASCII. Fechas imposibles (`2026-02-30`), año 0000, formatos locales (`02/10/2026`) y cualquier otra forma → `INVALID_FORMAT`. No hay heurísticas.

### `time`

`HH:MM` o `HH:MM:SS`, 24 h. Se rechazan fracciones de segundo, offsets, `24:00` y `23:59:60`.

### `datetime`

Subconjunto de RFC 3339: `YYYY-MM-DDTHH:MM(:SS)?(Z|±HH:MM)`, con `T` y `Z` en mayúscula. **El offset es obligatorio**: un datetime naive → `INVALID_FORMAT`. Se rechazan fracciones, `-00:00` ("offset desconocido"), offsets fuera de rango y fechas que salen del rango representable al convertir a UTC.

### `select`

Un string igual, byte a byte, a un `value` (sin trim, distingue mayúsculas). Enviar el `label` → `INVALID_OPTION`.

### `multi_select`

Array JSON de strings, cada uno un `value`. Duplicado → `DUPLICATE_SELECTION` (no se deduplica). `min_selected`/`max_selected` → `TOO_FEW_SELECTED`/`TOO_MANY_SELECTED`.

## Resultado de la validación

`app.forms.answers.validate_answers(schema, payload) -> ValidationResult`. Es puro: no persiste, no consulta PostgreSQL, Resources ni Rules.

```python
ValidationResult(valid: bool, values: Mapping[str, CanonicalValue], errors: tuple[FieldError, ...])
FieldError(element_id: str | None, code: AnswerErrorCode, message: str, constraint: str | None)
```

- Si hay **cualquier** error, `values` está vacío: nunca se devuelven valores parciales.
- Como máximo un error por elemento y **20 en total**. Los elementos se evalúan en orden de declaración; los campos desconocidos van después, ordenados.
- `constraint` nombra la restricción incumplida (`required`, `min_length`, `max_length`, `min`, `max`, `int64`, `decimal_places`, `min_selected`, `max_selected`) cuando aplica.
- **Los códigos son el contrato estable.** Los mensajes son texto humano fijo por código, pueden cambiar y **nunca** incluyen el valor recibido, el label ni secretos.

| Código | Cuándo |
|---|---|
| `INVALID_PAYLOAD` | La raíz no es un objeto JSON. |
| `UNKNOWN_FIELD` | Clave no declarada. |
| `FIELD_REQUIRED` | Obligatorio y ausente o vacío. |
| `INVALID_TYPE` | Tipo JSON incorrecto, incluido `null`. |
| `INVALID_CHARACTERS` | Carácter no permitido en `text`/`text_long`. |
| `INVALID_FORMAT` | Sintaxis inválida (email, url, date, time, datetime, decimal). |
| `VALUE_TOO_SMALL` / `VALUE_TOO_LARGE` | Fuera de `min`/`max` o de int64. |
| `TOO_SHORT` / `TOO_LONG` | Longitud fuera de rango (incluidos los máximos de email y url). |
| `TOO_MANY_DECIMAL_PLACES` | Más decimales de los declarados. |
| `INVALID_OPTION` | Valor que no es un `value` declarado. |
| `DUPLICATE_SELECTION` | Opción repetida en `multi_select`. |
| `TOO_FEW_SELECTED` / `TOO_MANY_SELECTED` | Fuera de `min_selected`/`max_selected`. |

## Diagnósticos de carga

Si `elements.toml` es inválido, **todo el paquete** es inválido y queda fuera del catálogo y de `forms_registry`; los demás paquetes no se ven afectados. Los diagnósticos van al log (`form_load_failed`) con ruta relativa, archivo, código y un mensaje que identifica el elemento por posición e `id` (escapado); sin rutas absolutas ni valores de propiedades. Máximo 20 por archivo.

| Código | Causa |
|---|---|
| `UNSUPPORTED_SCHEMA_VERSION`, `MISSING_PROPERTY` | `schema_version` ausente o distinto de 1. |
| `INVALID_ELEMENTS_SCHEMA` | Clave desconocida en la raíz o `element` mal formado. |
| `TOO_MANY_ELEMENTS` | Más de 200 elementos. |
| `INVALID_ELEMENT_ID` | `id` fuera de la regex. |
| `DUPLICATE_ELEMENT_ID` | `id` repetido. |
| `UNKNOWN_ELEMENT_TYPE` | Tipo no previsto (incluidos widgets). |
| `UNSUPPORTED_ELEMENT_TYPE` | `resource_select`, `resource_multi_select`. |
| `UNKNOWN_ELEMENT_PROPERTY` | Propiedad que no existe en el contrato. |
| `UNSUPPORTED_ELEMENT_PROPERTY` | `pattern` (diferido). |
| `MISSING_ELEMENT_PROPERTY` | Falta `id`, `type`, `label`, `required`, `decimal_places` u `options`. |
| `INVALID_ELEMENT_PROPERTY` | Valor inválido de `label`, `required` o `description`. |
| `INVALID_CONSTRAINT` | Restricción con tipo o rango inválido, incoherente (`min > max`) o que no aplica al tipo. |
| `INVALID_OPTIONS` | `options` mal formado, fuera de 1-200, clave desconocida, `value` o `label` inválidos, o `options` en un tipo que no las admite. |
| `DUPLICATE_OPTION_VALUE`, `DUPLICATE_OPTION_LABEL` | Opciones repetidas. |
| `INVALID_NORMALIZATION` | `normalize` no es tabla, clave o valor no permitidos, o tipo sin normalización. |

## Ejemplos

Válido:

```toml
schema_version = 1

[[element]]
id = "full_name"
type = "text"
label = "Nombre completo"
required = true
max_length = 120

[element.normalize]
trim = true
collapse_whitespace = true
case = "upper"

[[element]]
id = "contact_email"
type = "email"
label = "Correo"
required = true

[element.normalize]
trim = true
case = "lower"

[[element]]
id = "fee"
type = "decimal"
label = "Cuota"
required = false
decimal_places = 2
min = "0"

[[element]]
id = "starts_at"
type = "datetime"
label = "Inicio"
required = true
min = 2026-01-01T00:00:00Z

[[element]]
id = "topics"
type = "multi_select"
label = "Temas"
required = true
max_selected = 2

[[element.options]]
value = "security"
label = "Seguridad"

[[element.options]]
value = "data"
label = "Datos"

[[element.options]]
value = "ux"
label = "Experiencia de uso"
```

Payload y resultado:

```json
{
  "full_name": "  alice   example ",
  "contact_email": "Alice@Example.COM",
  "starts_at": "2026-10-02T18:30-06:00",
  "topics": ["ux", "security"]
}
```

```text
valid = true
values = {
  "full_name": "ALICE EXAMPLE",
  "contact_email": "alice@example.com",
  "starts_at": datetime(2026, 10, 3, 0, 30, tzinfo=UTC),   # "2026-10-03T00:30:00Z"
  "topics": ("security", "ux"),
}
```

(`fee` es opcional y no se envió: no aparece en `values`.)

Inválidos:

```toml
[[element]]
id = "name"
type = "text"
label = "Nombre"
required = true
banana = "yes"           # UNKNOWN_ELEMENT_PROPERTY

[[element]]
id = "email"
type = "email"
label = "Correo"         # falta required → MISSING_ELEMENT_PROPERTY
min = 10                 # INVALID_CONSTRAINT

[[element]]
id = "accept"
type = "checkbox"        # UNKNOWN_ELEMENT_TYPE (usar boolean)
label = "Acepto"
required = true

[[element]]
id = "code"
type = "text"
label = "Código"
required = true
pattern = "^[A-Z]+$"     # UNSUPPORTED_ELEMENT_PROPERTY (diferido)
```

```json
{"age": "18"}                 → INVALID_TYPE (integer)
{"age": "18 años"}            → INVALID_TYPE
{"newsletter": "true"}        → INVALID_TYPE (boolean)
{"session": "Matutina"}       → INVALID_OPTION (es el label)
{"fee": 12.5}                 → INVALID_TYPE (decimal llega como string)
{"starts_at": "2026-10-02T18:30:00"} → INVALID_FORMAT (sin offset)
{"name": null}                → INVALID_TYPE
{"unexpected": 1}             → UNKNOWN_FIELD
```

## Implementación

- `app/forms/elements.py`: dataclasses inmutables (`frozen`, `slots`), una por familia de tipo, unidas en `Element`; `ElementsSchema(elements, by_id)`; parser manual con lista blanca de propiedades por tipo.
- `app/forms/answers.py`: `validate_answers`.
- `FormPackage.elements` contiene el `ElementsSchema` cargado. No se expone por API ni se guarda en PostgreSQL.
