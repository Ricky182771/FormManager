# FormManager — Reglas de diseño, arquitectura y seguridad

> Estado: borrador inicial  
> Documento vivo: estas reglas deberán actualizarse conforme se tomen nuevas decisiones de arquitectura.

FormManager es un motor self-hosted para definición, validación y procesamiento de formularios.

Su objetivo principal no es proporcionar una interfaz gráfica compleja, sino ofrecer un **Core robusto, predecible, seguro y desacoplado de la presentación**.

La interfaz incluida por FormManager es solamente una implementación de referencia y conveniencia.

---

# 1. Principios fundamentales

## 1.1 Headless-first

FormManager DEBE diseñarse como un sistema **headless-first**.

El Core NO DEBE depender de la interfaz gráfica incluida para funcionar.

Toda operación fundamental debe poder realizarse mediante:

- API;
- configuración;
- archivos de definición;
- interfaces externas.

Un desarrollador debe poder utilizar:

- HTML/CSS propio;
- JavaScript;
- React;
- Svelte;
- Vue;
- una aplicación móvil;
- otro backend;
- cualquier cliente HTTP compatible;

sin modificar el Core de FormManager.

La UI incluida debe considerarse:

> Un cliente oficial sencillo de FormManager incluido por comodidad.

Y NO:

> Una parte indispensable del motor de formularios.

---

# 2. Separación de responsabilidades

FormManager deberá mantener una separación clara entre:

```text
Definición
    ↓
Validación
    ↓
Reglas
    ↓
Estado
    ↓
Persistencia
    ↓
Presentación
```

Cada capa debe tener responsabilidades claras.

La presentación NO debe decidir:

- si una respuesta es válida;
- si un recurso está disponible;
- si una opción alcanzó su límite;
- si una regla se cumple;
- si una reserva puede realizarse.

Estas decisiones corresponden al Core.

---

# 3. Filosofía de almacenamiento

FormManager utilizará dos mecanismos principales de almacenamiento:

```text
Filesystem
    ↓
Define QUÉ ES el formulario.

PostgreSQL
    ↓
Registra QUÉ HA OCURRIDO con el formulario.
```

## 3.1 El filesystem contendrá

- definición de formularios;
- elementos;
- reglas;
- recursos estáticos;
- proveedores de recursos;
- assets;
- interfaces personalizadas;
- metadatos necesarios para reconstruir la definición.

## 3.2 PostgreSQL contendrá

- submissions;
- respuestas;
- reservas;
- contadores;
- estado runtime;
- sesiones;
- auditoría;
- información transaccional;
- índices necesarios para concurrencia;
- referencias a formularios cargados.

Las respuestas NO DEBEN almacenarse en archivos como:

```text
responses.json
responses.csv
responses.toml
```

como fuente de verdad runtime.

La concurrencia y consistencia de las respuestas pertenece a PostgreSQL.

---

# 4. Directorio de formularios

El directorio de formularios debe poder configurarse desde el despliegue.

Ejemplo:

```env
FORMS_DIR=/data/forms
```

Docker debe permitir montar cualquier directorio del host:

```yaml
volumes:
  - /ruta/del/host/forms:/data/forms
```

FormManager NO debe asumir que los formularios viven en una ruta fija del host.

---

# 5. Identidad de formularios

Cada formulario tendrá un identificador interno opaco y aleatorio.

Ejemplo:

```text
K8mP4qT2xN7rV5sA
```

La longitud inicial recomendada es aproximadamente 16 caracteres.

Este valor:

- NO representa una contraseña;
- NO sustituye autenticación;
- NO debe considerarse secreto.

Su objetivo es:

- identificar el formulario internamente;
- evitar IDs secuenciales fácilmente enumerables;
- desacoplar identidad interna de nombres visibles.

El formulario podrá tener además un `slug` humano:

```text
inscripcion-taller
```

Ejemplo de URL:

```text
/f/inscripcion-taller
```

---

# 6. Estructura de un formulario

La estructura mínima prevista es:

```text
forms/
└── K8mP4qT2xN7rV5sA/
    ├── form.toml
    ├── elements.toml
    ├── resources.toml
    ├── rules.json
    │
    ├── resources/
    │   └── ...
    │
    ├── assets/
    │   └── ...
    │
    └── ui/
        └── ...           # opcional
```

No debe existir un archivo `appearance.toml`.

La configuración visual básica de la UI incluida, cuando exista, deberá formar parte de `form.toml`.

---

# 7. `form.toml`

`form.toml` describe el formulario como entidad.

Puede contener:

- ID;
- slug;
- título;
- subtítulo;
- descripción;
- estado;
- límites globales;
- configuración de acceso;
- configuración de publicación;
- mensajes;
- configuración de la UI incluida;
- comportamiento general;
- configuración Markdown.

Ejemplo conceptual:

```toml
schema_version = 1

id = "K8mP4qT2xN7rV5sA"
slug = "inscripcion-taller"

title = "Inscripción a taller"
subtitle = "Formulario de inscripción"

description = """
Elige **un horario** y deja tus datos de contacto.
"""

status = "open"

[submission]
max_responses = 100

[access]
mode = "code"

[frontend]
mode = "builtin"
```

`form.toml` NO debe definir la lógica interna compleja de las respuestas.

Esa responsabilidad pertenece a `rules.json`.

---

# 8. Markdown

Markdown se utilizará exclusivamente para contenido perteneciente al diseño y explicación del formulario.

Ejemplos:

- título;
- subtítulo;
- descripción;
- instrucciones;
- ayuda;
- descripciones de campos;
- mensajes de confirmación;
- textos informativos.

Las respuestas proporcionadas por los usuarios NO se interpretarán como Markdown.

## 8.1 Markdown inline

Podrá utilizarse en textos cortos.

Ejemplos:

```md
**Negrita**
*Cursiva*
`código`
~~tachado~~
[enlace](...)
```

## 8.2 Markdown block

Podrá utilizarse en contenido descriptivo más extenso.

Ejemplos:

```md
## Instrucciones

- Elemento uno
- Elemento dos

> Verifica tus datos antes de continuar.
```

## 8.3 Seguridad Markdown

FormManager NO debe permitir HTML arbitrario dentro del Markdown.

Debe deshabilitarse o sanitizarse:

```html
<script>
<iframe>
<style>
<object>
```

También deberán rechazarse esquemas peligrosos como:

```text
javascript:
```

El texto Markdown será la fuente canónica.

El HTML generado será únicamente una representación.

---

# 9. `elements.toml`

`elements.toml` representa exclusivamente el **esquema de datos aceptado por el formulario**.

NO representa diseño visual.

NO debe contener:

- colores;
- CSS;
- clases visuales;
- posiciones;
- tamaños;
- columnas visuales;
- animaciones;
- iconos;
- fuentes;
- coordenadas;
- layout.

Ejemplo:

```toml
[[element]]
id = "email"
type = "email"
label = "Correo"
required = true
```

---

# 10. Elementos como datos

Todo elemento de `elements.toml` debe representar un valor potencial de respuesta.

Por ello, en la versión inicial no es necesario declarar:

```toml
kind = "field"
```

porque todo elemento será un campo de datos.

Ejemplo:

```toml
[[element]]
id = "age"
type = "integer"
label = "Edad"
required = true
min = 0
max = 120
```

---

# 11. IDs de elementos

Los IDs de elementos deben ser:

- estables;
- únicos dentro del formulario;
- independientes de su etiqueta visible.

Ejemplo:

```toml
id = "contact_email"
label = "Correo de contacto"
```

Cambiar:

```toml
label = "Correo electrónico"
```

NO debe cambiar la identidad del campo.

Los IDs deberían admitir inicialmente:

```text
a-z
0-9
_
-
```

Ejemplos válidos:

```text
email
student_email
member-2
age
```

---

# 12. Datos estrictamente tipados

FormManager debe priorizar la calidad de los datos desde el momento de captura.

El Core debe evitar que los datos sucios entren a la persistencia siempre que el esquema permita detectarlos.

La filosofía será:

```text
Input
  ↓
Validación del tipo estructural de entrada
  ↓
Canonicalización estructural obligatoria del tipo
  ↓
Validación de caracteres estructuralmente permitidos
  ↓
Normalización explícita configurada
  ↓
Canonicalización Unicode final (NFC, solo text/text_long)
  ↓
Ausencia/vacío y `required`
  ↓
Restricciones locales sobre el VALOR CANÓNICO FINAL
  ↓
Rules Engine
  ↓
Transacción
  ↓
PostgreSQL
```

Las restricciones locales (longitud, rango...) nunca se evalúan antes de una transformación que pueda cambiar el valor: `case = "upper"` puede alargar un texto, así que `max_length` se comprueba después. El detalle exacto está en `ELEMENTS_SCHEMA.md`.

---

# 13. Tipos iniciales de elementos

La versión inicial deberá considerar, como mínimo:

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

Estos son tipos de DATOS.

FormManager Core NO debe tratar widgets visuales como tipos de datos.

Por ejemplo:

```text
checkbox
toggle
radio
dropdown
```

son decisiones de presentación.

`resource_select` y `resource_multi_select` están reconocidos pero **no son utilizables** hasta que exista el subsistema Resources: un `elements.toml` que los use es inválido (`UNSUPPORTED_ELEMENT_TYPE`). Sus propiedades no están definidas todavía.

Un frontend podrá representar:

```toml
type = "boolean"
```

como:

- checkbox;
- switch;
- botones Sí/No.

El Core únicamente entiende `boolean`.

---

# 14. Restricciones locales

`elements.toml` puede contener condiciones básicas aplicables al valor individual.

Ejemplos:

```text
required
min
max
min_length
max_length
pattern        # DIFERIDO
min_selected
max_selected
```

`pattern` está **diferido por seguridad** y no forma parte del contrato implementado de Elements v1: el módulo `re` de Python no ofrece una garantía satisfactoria contra ReDoS. Se diseñará en un hito propio; hasta entonces declararlo es un error.

`required` es **obligatorio** en cada elemento y es un booleano explícito: no tiene valor por defecto. Un campo ausente y un `null` no son equivalentes: `null` es siempre un tipo inválido, y la ausencia de respuesta se representa omitiendo la clave. Ver `ELEMENTS_SCHEMA.md`.

Ejemplo:

```toml
[[element]]
id = "age"
type = "integer"
label = "Edad"
required = true
min = 0
max = 120
```

Estas condiciones pertenecen a `elements.toml` porque pueden evaluarse sin consultar otras respuestas ni otros campos.

---

# 15. No realizar conversiones mágicas

FormManager NO debe intentar adivinar valores mal formados.

Ejemplo:

Para:

```toml
type = "integer"
```

puede aceptarse:

```text
18
```

pero NO debe convertir automáticamente:

```text
"18 años"
```

en:

```text
18
```

Las conversiones implícitas deben ser mínimas, predecibles y documentadas.

---

# 16. Normalización

La normalización debe ser explícita cuando pueda modificar el significado visible del dato.

Ejemplo:

```toml
[element.normalize]
trim = true
collapse_whitespace = true
case = "upper"
```

Esto permitiría convertir:

```text
"  alice   example "
```

en:

```text
"ALICE EXAMPLE"
```

El Core NO debe realizar transformaciones agresivas no declaradas.

Las normalizaciones declaradas se aplican siempre en el orden fijo `trim` → `collapse_whitespace` → `case`, sea cual sea su orden en el archivo.

Distinta de la normalización declarada es la **canonicalización estructural** del tipo, que no es configurable y forma parte de su contrato: Unicode NFC en las respuestas `text`/`text_long` (para que `é` precompuesto y `e` + acento combinado no se almacenen distinto), CRLF/CR → LF en `text_long`, `HH:MM` → `HH:MM:SS`, datetime → UTC y decimal con exactamente `decimal_places` decimales. Ver `ELEMENTS_SCHEMA.md`.

---

# 17. Valores canónicos

FormManager debe almacenar valores en representaciones canónicas.

Ejemplos:

Fecha:

```text
2026-10-02
```

Hora:

```text
18:30:00
```

Fecha y hora:

```text
2026-10-03T00:30:00Z
```

Booleanos:

```text
true
false
```

Un frontend puede mostrar una representación distinta, pero la fuente de datos debe permanecer normalizada.

---

# 18. Decimales

Los valores `decimal` NO deben utilizar floating point binario como representación primaria.

Python debe utilizar tipos equivalentes a:

```text
Decimal
```

y PostgreSQL:

```text
NUMERIC
```

cuando la precisión exacta sea relevante.

---

# 19. Opciones

Los elementos de selección deben separar:

```text
value
```

de:

```text
label
```

Ejemplo:

```toml
[[element]]
id = "session"
type = "select"
label = "Turno"
required = true

[[element.options]]
value = "am"
label = "Turno matutino"
```

La respuesta almacenada será:

```text
"am"
```

y NO:

```text
"Turno matutino"
```

Esto permite modificar posteriormente la representación humana sin alterar el significado histórico del dato.

---

# 20. Validación estricta de configuración

Los schemas deben ser estrictos.

Propiedades desconocidas deben generar error.

Ejemplo inválido:

```toml
[[element]]
id = "name"
type = "text"
banana = "yes"
```

FormManager deberá reportar algo equivalente a:

```text
Unknown property "banana" for element "name".
```

Las propiedades desconocidas NO deben ignorarse silenciosamente.

---

# 21. `resources.toml`

`resources.toml` declarará datasets disponibles para ser consumidos por elementos.

Los elementos podrán referenciarlos mediante:

```toml
resource = "rooms"
```

Los recursos son fuentes de datos.

NO son reglas.

NO deciden si una submission debe aceptarse.

---

# 22. Fuentes estáticas de recursos

FormManager deberá admitir inicialmente recursos almacenados en:

```text
CSV
TXT
JSON
TOML
```

Ejemplo:

```toml
[[resource]]
id = "rooms"
type = "file"
format = "csv"
source = "resources/rooms.csv"

key = "id"
label = "name"
```

---

# 23. Dataset canónico

Sin importar su formato de origen, todo recurso deberá transformarse internamente a una representación canónica.

Conceptualmente:

```json
{
  "id": "room_a",
  "label": "Sala A",
  "data": {
    "building": "north",
    "capacity": 30
  }
}
```

El Core no debe necesitar saber si el dataset vino de:

- CSV;
- JSON;
- TOML;
- TXT;
- JavaScript.

---

# 24. Recursos JavaScript opcionales

FormManager podrá soportar recursos generados mediante JavaScript.

Esta funcionalidad será opcional.

JavaScript se utilizará EXCLUSIVAMENTE para:

> preparar datasets estructurados y entregarlos al Resource Manager.

NO será:

- lenguaje de reglas;
- lenguaje de validación de submissions;
- backend alternativo;
- extensión de permisos;
- forma de ejecutar acciones arbitrarias durante una respuesta.

---

# 25. JavaScript controlado por el desarrollador

Los proveedores JavaScript:

- serán escritos por el desarrollador o administrador;
- estarán registrados previamente;
- NO serán construidos a partir de input del usuario;
- NO recibirán código proporcionado por respondientes;
- NO podrán ser modificados mediante respuestas;
- NO podrán seleccionar dinámicamente scripts según input externo.

Principio obligatorio:

> Ningún valor enviado por un usuario debe modificar qué código JavaScript se ejecuta.

---

# 26. El JavaScript NO recibe input del respondiente

En la versión inicial, el proveedor JavaScript NO debe recibir:

- respuestas del formulario;
- request body;
- query parameters;
- cookies;
- headers;
- dirección IP;
- sesiones;
- datos arbitrarios enviados por usuarios.

Puede recibir únicamente un contexto controlado por FormManager.

Ejemplo:

```json
{
  "form_id": "K8mP4qT2xN7rV5sA",
  "resource_id": "available_schedules",
  "timestamp": "2026-10-02T06:00:00Z"
}
```

---

# 27. Contrato de proveedores JavaScript

Un proveedor puede implementar una interfaz equivalente a:

```js
export async function load(context) {
    return [
        {
            id: "morning",
            label: "Turno matutino",
            start: "08:00",
            end: "12:00"
        }
    ];
}
```

Su única responsabilidad es devolver datos.

NO puede decidir:

```text
aceptar submission
rechazar submission
reservar recurso
liberar recurso
modificar reglas
alterar sesiones
```

---

# 28. Validación de salida JavaScript

El Core NO debe confiar automáticamente en los datos producidos por JavaScript.

Toda salida de un provider deberá:

1. serializarse;
2. validarse;
3. comprobarse contra el schema del recurso;
4. convertirse al dataset canónico.

Ejemplo:

Si se espera:

```text
players = integer
```

y JavaScript devuelve:

```text
players = "muchos"
```

el recurso debe rechazarse.

Los resource providers también están sujetos a validación estricta.

---

# 29. JS Runner separado

El JavaScript NO debe ejecutarse dentro del mismo proceso de FastAPI.

Debe existir un runtime separado y opcional.

Arquitectura:

```text
caddy
app
db
js-runner   # opcional
```

El JS Runner deberá estar aislado del Core.

---

# 30. Seguridad del JS Runner

Por defecto, el JS Runner deberá ejecutarse con:

```text
filesystem del host: NO
Docker socket: NO
PostgreSQL: NO
variables secretas: NO
red: NO
privilegios Linux: mínimos
```

El contenedor debería utilizar medidas equivalentes a:

```yaml
read_only: true

cap_drop:
  - ALL

security_opt:
  - no-new-privileges:true
```

Además deberá establecer límites razonables de:

- memoria;
- CPU;
- procesos;
- tiempo de ejecución.

El runner NO debe tener acceso a:

```text
/var/run/docker.sock
.env
SESSION_SECRET
DATABASE_URL
credenciales admin
contraseña PostgreSQL
```

---

# 31. Capabilities futuras

Si más adelante un provider necesita capacidades adicionales, deberán concederse explícitamente.

Ejemplo conceptual:

```toml
[permissions]
network = false
filesystem = false
environment = false
```

Por defecto:

> Todo está denegado.

Cualquier ampliación deberá aplicar principio de mínimo privilegio.

---

# 32. Resources no son Rules

Un Resource Provider únicamente responde:

> ¿Qué datos existen?

`elements.toml` responde:

> ¿Qué datos puede proporcionar el usuario?

`rules.json` responde:

> ¿Qué combinaciones y comportamientos están permitidos?

Esta frontera NO debe romperse.

---

# 33. `rules.json`

`rules.json` contendrá lógica que exceda la validación local de un elemento.

Ejemplos:

- relaciones entre campos;
- unicidad;
- límites globales;
- reservas;
- cupos;
- dependencias;
- comportamiento condicional;
- acciones de formulario.

Ejemplo conceptual:

```json
{
  "type": "distinct",
  "fields": [
    "participant_a",
    "participant_b",
    "participant_c"
  ]
}
```

---

# 34. Reglas declarativas

Las reglas deberán ser preferentemente declarativas.

FormManager NO debe utilizar JavaScript ni Python arbitrario como lenguaje de reglas.

Ejemplo:

```json
{
  "type": "option_usage_limit",
  "field": "time_slot",
  "max_uses": 2
}
```

es preferible a:

```js
if (...) {
    ...
}
```

Esto permite:

- validación;
- análisis;
- seguridad;
- traducción a mecanismos transaccionales;
- compatibilidad entre clientes.

---

# 35. Rules Engine y base de datos

`rules.json` describe la intención.

PostgreSQL garantiza el estado real.

Ejemplo:

```json
{
  "type": "option_usage_limit",
  "field": "time_slot",
  "max_uses": 2
}
```

NO debe implementarse únicamente como:

```text
SELECT
↓
parece disponible
↓
INSERT
```

El Core deberá utilizar:

- transacciones;
- constraints;
- índices;
- locks cuando corresponda;
- reservations;
- manejo de conflictos;

para garantizar que dos peticiones concurrentes no violen la regla.

---

# 36. PostgreSQL como fuente de verdad runtime

La disponibilidad visible en una UI es informativa.

La comprobación definitiva siempre debe realizarse durante la transacción.

Ejemplo:

```text
Usuario A ve opción libre.
Usuario B ve opción libre.

A envía.
B envía.

PostgreSQL determina quién gana.
```

Solo una operación podrá confirmar cuando exista una regla de exclusividad.

---

# 37. API como contrato oficial

FormManager debe considerar su API como el contrato principal entre Core e interfaces.

La UI builtin deberá utilizar las mismas reglas y operaciones fundamentales que una UI externa.

Un frontend personalizado no debe necesitar conocer:

- SQLAlchemy;
- tablas internas;
- rutas internas del filesystem;
- implementación de PostgreSQL;
- detalles privados del Rules Engine.

---

# 38. API versionada

Las rutas públicas del Core deben versionarse.

Ejemplo:

```text
/api/v1/
```

Esto permitirá evolucionar el backend sin romper clientes existentes.

---

# 39. Frontend builtin

FormManager incluirá una UI básica.

Sus objetivos son:

- funcionalidad;
- claridad;
- accesibilidad;
- responsive design;
- bajo consumo;
- personalización ligera.

NO debe intentar convertirse en un constructor visual avanzado.

NO se busca competir con herramientas de diseño.

---

# 40. Modos de frontend

FormManager debería contemplar:

```text
builtin
custom
headless
```

## builtin

FormManager renderiza su propia UI.

## custom

El formulario puede proporcionar archivos propios:

```text
ui/
├── index.html
├── style.css
├── app.js
└── assets/
```

## headless

FormManager únicamente expone el Core y su API.

La presentación es completamente externa.

---

# 41. React y otras herramientas

FormManager Core NO debe depender de:

- Node;
- npm;
- Vite;
- React;
- Webpack;
- frameworks frontend.

Un usuario podrá construir una aplicación React externamente y entregar únicamente sus archivos compilados.

Ejemplo:

```text
npm run build
        ↓
dist/
        ↓
forms/<id>/ui/
```

FormManager solamente servirá el resultado estático o permitirá que el frontend externo consuma la API.

---

# 42. Página de inicio personalizada

La instancia podrá permitir una página principal personalizada.

Ejemplo:

```text
/data/site/
├── index.html
├── style.css
├── app.js
└── assets/
```

Esto permitirá utilizar FormManager como motor detrás de un portal completamente personalizado.

La existencia de una página personalizada NO debe modificar el funcionamiento del Core.

---

# 43. Seguridad del frontend personalizado

Una UI personalizada NO obtiene privilegios especiales.

Debe utilizar las mismas APIs y validaciones que cualquier otro cliente.

NO debe poder:

- conectarse directamente a PostgreSQL;
- alterar reglas internas;
- acceder a secretos;
- evitar validación;
- reservar recursos sin pasar por el Core.

---

# 44. Validación en servidor obligatoria

Toda validación relevante debe repetirse en el servidor.

La validación frontend solo sirve para mejorar la experiencia del usuario.

Nunca debe ser considerada una frontera de seguridad.

```text
Frontend
   ↓
validación opcional

Core
   ↓
validación obligatoria
```

---

# 45. Creación atómica de formularios

Al crear un formulario, FormManager debería evitar dejar directorios parcialmente escritos.

Proceso recomendado:

```text
/forms/.tmp-ID/
```

1. crear archivos;
2. validarlos;
3. comprobar schemas;
4. confirmar que la definición es consistente;
5. realizar rename atómico:

```text
.tmp-ID → ID
```

Si ocurre un error, el formulario incompleto no debe aparecer como válido.

---

# 46. Archivos de definición como configuración no confiable

Aunque los archivos sean creados por un administrador, FormManager debe validarlos al cargarlos.

Debe comprobar:

- schema_version;
- propiedades válidas;
- IDs duplicados;
- referencias inexistentes;
- tipos inválidos;
- resources inexistentes;
- reglas inválidas;
- rutas inseguras.

El hecho de que un archivo esté en `FORMS_DIR` NO significa automáticamente que sea válido.

---

# 47. Prevención de path traversal

Todo acceso a archivos pertenecientes a formularios debe restringirse al directorio autorizado.

Entradas como:

```text
../../etc/passwd
```

NO deben permitir escapar de:

```text
FORMS_DIR
```

Las rutas deberán resolverse y validarse antes de cualquier lectura.

---

# 48. Secrets

Los secretos NO deben almacenarse dentro de los directorios de formularios.

Ejemplos:

```text
SESSION_SECRET
DATABASE_PASSWORD
ADMIN_PASSWORD
API secrets
```

deberán gestionarse mediante:

- variables de entorno;
- secretos Docker;
- mecanismos equivalentes.

Los archivos exportables de formulario NO deben contener secretos de infraestructura.

---

# 49. Arquitectura Docker

La arquitectura general continuará siguiendo:

```text
Internet
   ↓
Caddy
   ↓
FormManager Core
   ↓
PostgreSQL
```

Opcionalmente:

```text
FormManager Core
   ↓
JS Runner
```

PostgreSQL y el Core NO deben exponerse directamente a Internet.

Solo el reverse proxy debe publicar los puertos web necesarios.

---

# 50. Principio de mínimo privilegio

Los contenedores deberán:

- ejecutarse como usuarios no-root cuando sea posible;
- disponer únicamente de las redes necesarias;
- evitar capacidades Linux innecesarias;
- no montar el Docker socket;
- no acceder a secretos que no necesitan;
- no exponer puertos internos.

---

# 51. Seguridad por defecto

Las configuraciones iniciales deberán favorecer la opción más segura.

Ejemplos:

```text
raw HTML → deshabilitado
JS network → deshabilitado
JS filesystem → deshabilitado
PostgreSQL público → deshabilitado
CORS "*" → deshabilitado
Docker socket → no montado
```

El usuario podrá ampliar capacidades explícitamente cuando exista una razón válida.

---

# 52. Integridad sobre comodidad

Ante un conflicto entre:

```text
"ser permisivo con datos incorrectos"
```

y:

```text
"rechazar datos ambiguos"
```

FormManager deberá favorecer la integridad y previsibilidad.

Los errores deben ser claros para que el creador pueda corregir la definición o el usuario pueda corregir su respuesta.

---

# 53. FormManager no debe inventar datos

El Core NO debe:

- completar respuestas automáticamente sin una regla explícita;
- convertir valores ambiguos;
- corregir silenciosamente tipos incompatibles;
- asignar recursos arbitrariamente;
- reinterpretar valores no válidos.

Un formulario debe comportarse de manera determinista.

---

# 54. Exportabilidad

La definición de un formulario debe mantenerse suficientemente desacoplada como para permitir exportación e importación futura.

Una exportación podrá conceptualmente producir:

```text
my-form.form.zip
```

conteniendo:

```text
form.toml
elements.toml
resources.toml
rules.json
assets/
resources/
ui/
```

Las respuestas y estado runtime deberán tratarse por separado.

---

# 55. Compatibilidad de schema

Todos los archivos de definición deberán declarar una versión de schema cuando corresponda.

Ejemplo:

```toml
schema_version = 1
```

Esto permitirá:

- migraciones;
- compatibilidad hacia atrás;
- validación;
- mensajes de error claros;
- evolución del formato.

---

# 56. Objetivo general de calidad de datos

FormManager debe intentar prevenir datos inconsistentes desde el momento de captura.

La plataforma deberá priorizar:

- tipos explícitos;
- opciones canónicas;
- IDs estables;
- normalización declarada;
- restricciones claras;
- validación temprana;
- persistencia tipada.

Principio:

> FormManager no solo recopila información. Define un esquema que protege la calidad de esa información desde el momento de entrada.

---

# 57. Decisiones aún abiertas

Los siguientes aspectos todavía NO están completamente definidos y deberán discutirse antes de considerarlos parte estable del proyecto:

- lenguaje exacto para expresiones condicionales dentro de `rules.json`;
- posible uso de CEL;
- runtime exacto del JS Runner;
- Node.js vs Deno u otro runtime;
- formato exacto del Resource Dataset canónico;
- estrategia exacta de versionado de formularios;
- esquema definitivo de respuestas en PostgreSQL;
- modelo de plugins;
- proveedores externos adicionales;
- webhooks;
- carga de archivos;
- autenticación individual de respondientes;
- sistema de permisos multiusuario;
- API administrativa definitiva;
- formato final de exportación/importación.

Estas características NO deben implementarse de forma improvisada antes de definir su contrato.

---

# 58. Regla de arquitectura principal

Ante cualquier nueva característica deberá preguntarse:

> ¿Esta función pertenece a la definición, al Core, al Rules Engine, a Resources, a PostgreSQL o a la presentación?

Si una característica mezcla varias responsabilidades sin necesidad, deberá rediseñarse.

La meta es conservar esta separación:

```text
form.toml
    ↓
Configuración general

elements.toml
    ↓
Esquema de entrada

resources.toml
    ↓
Fuentes de datos

rules.json
    ↓
Lógica declarativa

Resource Providers
    ↓
Preparación de datasets

Core
    ↓
Validación y ejecución

PostgreSQL
    ↓
Estado e integridad

UI
    ↓
Presentación
```

---

# 59. Regla de seguridad principal

Ninguna interfaz, archivo de recurso ni provider externo debe poder saltarse el Core.

Toda submission válida debe seguir conceptualmente:

```text
Cliente
   ↓
API
   ↓
Schema Validator
   ↓
Element Validation
   ↓
Rules Engine
   ↓
Resource Validation
   ↓
Transaction
   ↓
Database Constraints
   ↓
COMMIT
```

Si alguna arquitectura futura permite:

```text
Cliente → PostgreSQL
```

o:

```text
Provider JS → aceptar submission
```

o:

```text
Frontend → ignorar reglas
```

esa arquitectura viola los principios de FormManager.

---

# 60. Filosofía del proyecto

FormManager debe ser:

- self-hosted;
- portable;
- headless-first;
- seguro por defecto;
- estricto con datos;
- modular;
- sencillo de desplegar;
- independiente de frameworks frontend;
- extensible sin sacrificar integridad.

Debe evitar convertirse innecesariamente en:

- un diseñador gráfico;
- un CMS;
- un framework frontend;
- una plataforma de ejecución arbitraria;
- un conjunto de scripts específicos por formulario.

El Core debe permanecer pequeño, comprensible y auditable.
