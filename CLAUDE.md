# CLAUDE.md — Reglas de trabajo para FormManager

> Este archivo contiene instrucciones operativas obligatorias para Claude Code al trabajar en este repositorio.  
> FormManager es un proyecto **self-hosted, headless-first, seguro por defecto y estricto con la calidad de los datos**.

---

# 0. Jerarquía de instrucciones

Al trabajar en este repositorio, respeta este orden de prioridad:

1. La solicitud explícita y actual del usuario.
2. El prompt del hito o tarea actual.
3. Este archivo `CLAUDE.md`.
4. `PROJECT_RULES.md`.
5. `REBASE.md`.
6. `ARCHITECTURE.md`, `SECURITY.md` y demás documentación técnica.
7. El comportamiento existente del código y sus tests.

Si dos fuentes se contradicen de forma que pueda afectar arquitectura, seguridad, datos o compatibilidad:

- NO improvises;
- NO elijas silenciosamente una interpretación;
- señala la contradicción antes de continuar.

---

# 1. Regla principal de trabajo

Trabaja **un hito a la vez**.

NO implementes características pertenecientes a hitos posteriores salvo que el usuario lo ordene explícitamente.

NO conviertas una tarea pequeña en un refactor masivo.

NO "aproveches" una tarea para introducir:

- nuevas abstracciones no solicitadas;
- nuevos frameworks;
- nuevos servicios;
- nuevas tablas;
- nuevos formatos;
- nuevas APIs;
- nuevas dependencias;
- nuevos mecanismos de autenticación;
- nuevos motores de reglas.

Si una característica futura necesita prepararse, crea únicamente el seam mínimo necesario y documenta que su implementación queda diferida.

---

# 2. Lectura obligatoria antes de programar

Antes de modificar código en una tarea importante:

1. Lee este `CLAUDE.md`.
2. Lee `PROJECT_RULES.md`.
3. Lee `REBASE.md` cuando la tarea implique migración, rebase o comparación con TeamRegistration.
4. Lee la documentación específica del componente afectado.
5. Inspecciona el código existente.
6. Inspecciona los tests relacionados.
7. Revisa `git status`.

Nunca programes basándote únicamente en nombres de archivos o en suposiciones sobre cómo "debería" estar implementado algo.

---

# 3. Repositorio de referencia TeamRegistration

Cuando exista el repositorio:

```text
../TeamRegistration
```

trátalo como **solo lectura**.

Puedes:

- leer archivos;
- comparar implementaciones;
- estudiar tests;
- estudiar seguridad;
- estudiar Docker;
- estudiar SQL;
- estudiar middleware;
- estudiar scripts.

NO debes:

- modificarlo;
- formatearlo;
- ejecutar migraciones destructivas sobre él;
- borrar archivos;
- crear commits;
- usarlo como directorio de trabajo;
- copiar datos personales al nuevo proyecto.

TeamRegistration es una referencia de implementación, NO la arquitectura final.

---

# 4. Regla de migración

Al portar código desde TeamRegistration, pregunta siempre:

> ¿Esta pieza existe porque cualquier motor de formularios seguro la necesita, o porque el flujo de negocio específico del prototipo la necesitaba?

Si es genérica:

- consérvala;
- generalízala;
- prueba que mantiene sus invariantes.

Si es específica del flujo del prototipo:

- NO la portes al Core;
- elimínala de la migración;
- como máximo conviértela después en ejemplo con datos sintéticos.

NO hagas renombres falsamente genéricos.

Ejemplo prohibido:

```text
<entidad legacy del prototipo>  -> ResourceItem
<agrupación legacy del prototipo> -> Submission
<catálogo legacy del prototipo>  -> Option
```

si por debajo sigue existiendo lógica específica de:

- cantidades fijas de participantes, grupos u opciones;
- roles fijos del flujo original;
- constantes de negocio hardcodeadas;
- el flujo escolar específico del prototipo.

---

# 5. Datos personales y fixtures

El Core de FormManager NO debe contener datos personales reales.

Está prohibido copiar al nuevo repositorio:

- nombres reales de personas;
- listas reales de grupos;
- respuestas reales;
- backups reales;
- hashes reales;
- tokens;
- `.env`;
- logs de producción;
- secretos;
- direcciones IP históricas;
- cualquier dato identificable del prototipo.

Para tests y ejemplos usa exclusivamente datos sintéticos, por ejemplo:

```text
ALICE EXAMPLE
BOB EXAMPLE
CAROL EXAMPLE
DAVE EXAMPLE
```

Al finalizar una migración relevante, realiza una búsqueda global para detectar contaminación del dominio anterior.

---

# 6. No destruir trabajo del usuario

Nunca ejecutes sin autorización explícita:

```bash
git reset --hard
git clean -fd
git clean -fdx
git checkout -- .
rm -rf .
rm -rf <directorio-importante>
```

Tampoco sobrescribas cambios locales existentes solo porque dificulten tu tarea.

Si `git status` muestra cambios no tuyos:

- protégelos;
- evita pisarlos;
- trabaja alrededor de ellos;
- informa si bloquean la tarea.

NO hagas `git push` salvo instrucción explícita.

NO reescribas historial Git salvo instrucción explícita.

---

# 7. Commits

No crees commits automáticamente salvo que el usuario lo solicite o el flujo de trabajo lo requiera explícitamente.

Si se solicita un commit:

- revisa antes `git diff`;
- no incluyas secretos;
- no incluyas datos runtime;
- no incluyas archivos de usuario;
- usa un mensaje claro y limitado al hito.

No uses mensajes como:

```text
update
changes
fix stuff
```

Prefiere:

```text
core: add generic form package loader
security: preserve server-side admin sessions
docs: define resource provider contract
```

---

# 8. Arquitectura fundamental

FormManager debe permanecer:

- self-hosted;
- headless-first;
- seguro por defecto;
- estricto con datos;
- modular;
- portable;
- independiente de frameworks frontend;
- auditable;
- pequeño en su Core.

La UI builtin es un cliente oficial de conveniencia.

El Core NO depende de ella.

---

# 9. Separación de responsabilidades

Mantén esta frontera:

```text
form.toml
    -> configuración general del formulario

elements.toml
    -> esquema de datos aceptado

resources.toml
    -> fuentes de datasets

rules.json
    -> lógica declarativa

Resource Providers
    -> preparación de datasets

Core
    -> validación y ejecución

PostgreSQL
    -> estado runtime e integridad

UI
    -> presentación
```

Si una implementación mezcla innecesariamente estas responsabilidades, rediseña antes de continuar.

---

# 10. Filesystem vs PostgreSQL

Principio obligatorio:

```text
Filesystem
    define QUÉ ES el formulario.

PostgreSQL
    registra QUÉ HA OCURRIDO con el formulario.
```

El filesystem puede contener:

- definiciones;
- recursos estáticos;
- assets;
- UI personalizada;
- providers;
- metadata de configuración.

PostgreSQL debe contener:

- submissions;
- valores;
- reservas;
- sesiones;
- auditoría;
- contadores;
- estado runtime;
- información transaccional.

NO uses archivos JSON/CSV/TOML como fuente de verdad para submissions concurrentes.

---

# 11. `elements.toml`

`elements.toml` describe exclusivamente datos.

NO debe contener:

- estilos;
- CSS;
- colores;
- layout;
- iconos;
- posiciones;
- tamaños;
- animaciones;
- clases visuales;
- widgets de UI.

Ejemplo correcto:

```toml
[[element]]
id = "email"
type = "email"
label = "Correo"
required = true
```

Ejemplo incorrecto:

```toml
color = "blue"
width = "50%"
widget = "fancy-card"
```

Los tipos son semánticos, NO visuales.

---

# 12. Tipos de datos

La versión inicial contempla como mínimo:

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

NO conviertas widgets visuales en tipos del Core.

Por ejemplo:

```text
checkbox
toggle
radio
dropdown
```

pertenecen al frontend.

El Core entiende:

```text
boolean
select
```

---

# 13. Calidad de datos

FormManager debe impedir datos sucios tan pronto como sea posible.

Pipeline esperado:

```text
Input
  ->
Validación sintáctica
  ->
Validación de tipo
  ->
Restricciones locales
  ->
Normalización explícita
  ->
Rules Engine
  ->
Transacción
  ->
PostgreSQL
```

No realices conversiones mágicas.

Ejemplo:

```text
"18 años"
```

NO se convierte automáticamente a:

```text
18
```

si el campo espera un entero.

---

# 14. Normalización

La normalización que cambie la representación visible del dato debe estar declarada.

Ejemplo:

```toml
[element.normalize]
trim = true
collapse_whitespace = true
case = "upper"
```

No inventes normalizaciones globales agresivas.

No uses fuzzy matching para transformar silenciosamente valores.

---

# 15. Valores canónicos

Conserva tipos y formatos canónicos.

Ejemplos:

```text
date      -> 2026-10-02
time      -> 18:30:00
datetime  -> 2026-10-03T00:30:00Z
boolean   -> true / false
```

Para decimales exactos usa:

- Python `Decimal`;
- PostgreSQL `NUMERIC`.

NO conviertas todo a strings.

---

# 16. `value` vs `label`

En opciones y recursos, separa siempre identidad de presentación.

Ejemplo:

```toml
[[element.options]]
value = "am"
label = "Turno matutino"
```

La persistencia usa:

```text
"am"
```

La UI muestra:

```text
"Turno matutino"
```

Cambiar el `label` NO debe alterar el significado histórico del dato.

---

# 17. Markdown

Markdown solo se usa para contenido de presentación del formulario:

- títulos;
- subtítulos;
- descripciones;
- instrucciones;
- ayuda;
- mensajes;
- descripciones de elementos.

Las respuestas del usuario NO se interpretan como Markdown.

El Markdown:

- NO admite HTML arbitrario;
- NO admite `javascript:` URLs;
- debe sanitizarse;
- conserva el Markdown como fuente canónica.

---

# 18. Resources

Un Resource responde únicamente:

> ¿Qué datos existen?

NO decide si una submission es válida.

Los recursos pueden provenir de:

```text
CSV
TXT
JSON
TOML
JavaScript opcional
```

Todo recurso debe convertirse al mismo modelo canónico antes de ser usado por el Core.

---

# 19. JavaScript Resource Providers

JavaScript es opcional y se utiliza EXCLUSIVAMENTE para preparar datasets.

NO es:

- lenguaje de reglas;
- backend alternativo;
- validator de submissions;
- mecanismo de autorización;
- mecanismo para modificar DB;
- extensión general del Core.

El código JavaScript:

- lo escribe el desarrollador/administrador;
- está registrado previamente;
- nunca proviene del respondiente;
- nunca se selecciona en función del input del respondiente.

---

# 20. Input del usuario y JavaScript

El provider JavaScript NO debe recibir:

- answers;
- body de requests;
- cookies;
- headers;
- query params;
- IP;
- sesiones;
- tokens;
- input arbitrario del respondiente.

Solo puede recibir contexto generado y controlado por FormManager.

---

# 21. JS Runner

Cuando se implemente, el JavaScript debe ejecutarse en un runtime separado del proceso FastAPI.

Nunca uses:

```python
eval(...)
exec(...)
```

para ejecutar JavaScript o reglas.

El JS Runner debe ser opcional, aislado y con mínimo privilegio.

Por defecto:

```text
network      DENY
filesystem   DENY
environment  DENY
database     DENY
Docker       DENY
```

Nunca montar:

```text
/var/run/docker.sock
```

---

# 22. Rules Engine

Las reglas son declarativas.

NO uses JavaScript ni Python arbitrario como lenguaje de reglas.

Ejemplo esperado:

```json
{
  "type": "option_usage_limit",
  "field": "time_slot",
  "max_uses": 2
}
```

NO:

```js
if (...) {
    ...
}
```

---

# 23. Concurrencia

Las reglas globales NO pueden depender únicamente de:

```text
SELECT -> parece libre -> INSERT
```

PostgreSQL es la fuente de verdad runtime.

Utiliza, según corresponda:

- transacciones;
- unique constraints;
- índices;
- locks;
- reservations;
- rollback;
- manejo explícito de conflictos.

Dos solicitudes concurrentes nunca deben poder violar una regla de exclusividad.

---

# 24. API

La API es el contrato oficial entre Core y clientes.

Debe versionarse:

```text
/api/v1/
```

Una UI propia, una UI React, una app móvil y la UI builtin deben pasar por las mismas reglas del Core.

Ninguna UI obtiene privilegios especiales.

---

# 25. Frontend builtin

La UI builtin debe ser:

- ligera;
- accesible;
- responsive;
- funcional;
- sencilla;
- poco dependiente;
- fácil de reemplazar.

NO conviertas FormManager en un diseñador gráfico.

NO agregues React/Vue/Svelte al Core solo para la UI builtin.

---

# 26. Frontends custom

Los frontends personalizados:

- consumen la API;
- no acceden directamente a DB;
- no evitan validaciones;
- no leen secretos;
- no modifican Rules directamente en runtime;
- no obtienen acceso privilegiado.

El Core debe funcionar incluso si se elimina toda UI pública builtin.

---

# 27. Node y frameworks frontend

El Core NO debe depender de:

- Node;
- npm;
- Vite;
- React;
- Vue;
- Svelte;
- Webpack.

Un desarrollador puede compilar su frontend externamente y entregar archivos estáticos.

Eso NO convierte Node en dependencia de FormManager Core.

---

# 28. Validación en servidor

Toda validación relevante se repite en el servidor.

La validación del frontend solo mejora UX.

Nunca confíes en:

- `required` HTML;
- tipos `<input>`;
- JavaScript cliente;
- campos ocultos;
- valores deshabilitados en UI.

Todos los requests se consideran manipulables.

---

# 29. Configuración no confiable

Los archivos del formulario también se validan estrictamente.

No asumas que son seguros porque los creó un administrador.

Valida:

- schema version;
- propiedades desconocidas;
- tipos;
- IDs;
- duplicados;
- referencias;
- paths;
- resources;
- rules.

Propiedades desconocidas deben producir error.

NO se ignoran silenciosamente.

---

# 30. Path traversal

Toda ruta proveniente de definición debe resolverse dentro de sus directorios autorizados.

Nunca permitas que:

```text
../../etc/passwd
```

escape de:

```text
FORMS_DIR
```

o del paquete de formulario correspondiente.

Usa resolución canónica de paths y comprobación del parent autorizado.

---

# 31. Creación atómica de formularios

Cuando se implemente creación de forms:

```text
/forms/.tmp-ID/
```

1. escribe archivos;
2. valida;
3. verifica consistencia;
4. hace rename atómico a `ID`.

Un formulario parcialmente creado nunca debe aparecer como válido.

---

# 32. Secrets

Nunca guardes secretos de infraestructura dentro de un form package.

NO deben aparecer en:

```text
form.toml
elements.toml
resources.toml
rules.json
ui/
assets/
```

Secrets pertenecen a:

- variables de entorno;
- Docker secrets;
- mecanismos equivalentes.

Nunca hagas commit de `.env`.

---

# 33. Passwords

Contraseñas administrativas:

- Argon2id;
- nunca texto plano;
- nunca hash rápido;
- nunca log.

Conserva dummy verification para reducir diferencias observables cuando corresponda.

---

# 34. Sesiones

Las sesiones administrativas deben ser server-side.

El cliente recibe un token opaco.

La DB conserva solo un derivado seguro/HMAC/hash del token cuando corresponda.

Cookies:

- HttpOnly;
- Secure en producción;
- SameSite apropiado;
- prefijo `__Host-` cuando sea compatible.

NO uses JWT en `localStorage` para sesiones admin.

---

# 35. CSRF

Toda mutación autenticada por cookies debe protegerse contra CSRF.

Mantén:

- token criptográfico;
- comparación segura;
- validación de Origin;
- `Sec-Fetch-Site` cuando exista.

No desactives CSRF para "hacer funcionar" un frontend.

Corrige el cliente.

---

# 36. Rate limiting

El rate limiting:

- es defensa de abuso;
- NO es identidad;
- NO es mecanismo de integridad.

Mientras sea in-memory, usa un solo worker ASGI o cambia explícitamente el backend del limiter antes de escalar workers.

Nunca dependas del limiter para garantizar unicidad o concurrencia.

---

# 37. Logging

Logs estructurados.

Nunca registres:

- contraseñas;
- hashes;
- cookies;
- session tokens;
- CSRF completos;
- Authorization;
- API keys;
- secrets;
- DATABASE_URL con contraseña;
- body completo de submissions;
- `.env`.

Mantén allowlist de campos extras.

---

# 38. Errores

No expongas:

- stack traces;
- SQL;
- DSN;
- paths internos sensibles;
- nombres de tablas cuando no sea necesario;
- secrets.

Los errores públicos deben ser:

- estables;
- estructurados;
- útiles;
- no excesivamente informativos.

---

# 39. PostgreSQL

PostgreSQL es la DB de producción.

No sustituyas tests críticos de:

- transacciones;
- locks;
- constraints;
- concurrencia;

con SQLite.

SQLite puede usarse solo donde la prueba no dependa de comportamiento específico de PostgreSQL y esté justificado.

---

# 40. Privilegios PostgreSQL

Separa:

```text
bootstrap role
application role
```

El rol de aplicación debe tener mínimo privilegio.

NO debe ser:

- SUPERUSER;
- CREATEDB;
- CREATEROLE;
- REPLICATION;
- BYPASSRLS.

El contenedor app no debe recibir la contraseña bootstrap si no la necesita.

---

# 41. Docker

Arquitectura:

```text
Internet
   ->
Caddy
   ->
FormManager Core
   ->
PostgreSQL
```

Opcional:

```text
FormManager Core
   ->
JS Runner
```

Solo Caddy expone puertos públicos web.

NO publiques:

```text
5432
8000
8080
```

salvo entorno de desarrollo explícito y aislado.

---

# 42. Seguridad de contenedores

Siempre que sea viable:

- non-root;
- `read_only: true`;
- mounts writable mínimos;
- `cap_drop: ALL`;
- `no-new-privileges:true`;
- PID limit;
- memory limit;
- CPU limit donde tenga sentido;
- healthchecks;
- sin Docker socket;
- sin host networking.

No deshabilites hardening sin documentar por qué.

---

# 43. Caddy

Caddy debe ser el entrypoint público.

Mantén:

- TLS;
- redirect HTTP -> HTTPS;
- reverse proxy;
- headers seguros;
- límites razonables.

FastAPI no debe exponerse directamente en producción.

---

# 44. CORS

Mismo origen por defecto.

NO uses:

```text
Access-Control-Allow-Origin: *
```

salvo que exista una razón explícita y un diseño de API pública que lo justifique.

No habilites CORS por costumbre.

---

# 45. CSP

Mantén una CSP estricta.

No la relajes con:

```text
unsafe-inline
unsafe-eval
*
```

solo para facilitar una UI.

Si un frontend custom necesita una política diferente, debe diseñarse conscientemente y sin debilitar el Core innecesariamente.

---

# 46. Dependencias

Antes de añadir una dependencia:

1. explica qué problema resuelve;
2. comprueba que no exista ya una solución razonable en el stack;
3. evalúa superficie de ataque;
4. evita paquetes enormes para funciones triviales;
5. fija versiones según la política del proyecto;
6. actualiza documentación y lock/requirements necesarios.

No introduzcas frameworks por preferencia personal.

---

# 47. Código muerto

No dejes:

- compat shims con TeamRegistration;
- imports no usados;
- modelos vacíos "para el futuro";
- endpoints no utilizados;
- feature flags sin consumidor;
- TODOs que sustituyan funcionalidad obligatoria.

Si una pieza ya no pertenece al proyecto, elimínala cuando sea seguro hacerlo.

---

# 48. Refactors

Los refactors deben:

- mantener comportamiento salvo que la tarea diga lo contrario;
- mantener tests relevantes;
- ser limitados al scope;
- evitar renombres masivos innecesarios.

No mezcles:

```text
feature + refactor grande + cambio de dependencias + cambio de arquitectura
```

en una sola tarea salvo instrucción explícita.

---

# 49. Tests

Toda funcionalidad nueva relevante debe tener tests.

Toda corrección de bug debería incluir una prueba que falle antes y pase después.

No elimines un test simplemente porque dificulta la implementación.

Si un test ya no aplica:

1. identifica qué garantía protegía;
2. determina si esa garantía sigue siendo necesaria;
3. crea el equivalente genérico si corresponde;
4. solo entonces retira el test viejo.

---

# 50. Concurrency tests

Toda feature con:

- unicidad;
- reservas;
- límites globales;
- cupos;

debe tener pruebas concurrentes contra PostgreSQL real.

No aceptes como suficiente un test secuencial.

---

# 51. Security tests

Mantén tests para:

- auth;
- CSRF;
- sessions;
- rate limits;
- headers;
- path traversal;
- XSS;
- request size;
- permisos;
- secrets;
- aislamiento de containers cuando sea verificable.

---

# 52. Tooling obligatorio

Mantén y ejecuta, según el hito:

```text
pytest
ruff
black
mypy --strict
bandit
pip-audit
```

No declares terminado un hito si las comprobaciones obligatorias fallan.

Si una herramienta genera un falso positivo:

- documéntalo;
- justifica el ignore;
- limita el ignore al caso concreto.

---

# 53. Mypy

No silencies typing masivamente con:

```python
# type: ignore
```

o:

```python
Any
```

solo para conseguir un build verde.

Usa tipos concretos.

Los ignores deben ser:

- locales;
- justificados;
- mínimos.

---

# 54. Lint

No desactives reglas globales solo porque una implementación nueva las viola.

Corrige el código primero.

Cambiar configuración de lint requiere una justificación técnica.

---

# 55. Tests antes de terminar

Antes de declarar una tarea importante completada:

1. ejecuta tests relacionados;
2. ejecuta suite completa cuando sea razonable;
3. ejecuta lint;
4. ejecuta formatting check;
5. ejecuta typecheck;
6. ejecuta security checks relevantes;
7. valida Docker si la tarea afecta deployment;
8. revisa `git diff`.

---

# 56. Docker validation

Si modificas:

- Dockerfile;
- Compose;
- Caddy;
- entrypoint;
- healthchecks;
- networking;
- filesystem mounts;

ejecuta al menos:

```bash
docker compose config
docker compose build
```

Y cuando el entorno lo permita:

```bash
docker compose up -d
docker compose ps
```

Comprueba explícitamente puertos publicados y salud.

---

# 57. Migraciones Alembic

Nunca edites una migración ya aplicada en producción salvo que el usuario lo ordene conscientemente y se entienda el impacto.

En el nuevo repositorio FormManager la historia empieza limpia.

Cada nueva migración:

- debe ser determinista;
- debe tener downgrade razonable cuando sea posible;
- no debe incluir datos personales;
- no debe depender de estados locales accidentales.

---

# 58. Seeds

Los seeds del Core deben ser:

- genéricos;
- idempotentes;
- sin datos personales.

No uses seed para ocultar configuración hardcodeada.

No añadas "datos demo" a producción automáticamente salvo decisión explícita.

---

# 59. Backups

Cambios que afecten persistencia deben considerar:

- backup;
- restore;
- compatibilidad.

A futuro, un backup completo de FormManager requerirá al menos:

```text
PostgreSQL + FORMS_DIR
```

No asumas que uno sustituye al otro.

---

# 60. Documentación sincronizada

Cuando una tarea cambia un contrato público o arquitectura, actualiza la documentación relevante en el mismo trabajo.

No dejes código y docs contradiciéndose.

Documentos especialmente importantes:

```text
PROJECT_RULES.md
REBASE.md
ARCHITECTURE.md
SECURITY.md
README.md
API.md
FORM_SCHEMA.md
ELEMENTS_SCHEMA.md
RESOURCES_SCHEMA.md
RULES_SCHEMA.md
JS_PROVIDERS.md
```

Solo crea los documentos correspondientes cuando su hito exista.

---

# 61. README honesto

README debe describir lo que realmente existe.

NO anuncies funcionalidades futuras como implementadas.

Usa lenguaje explícito como:

```text
Planned
Experimental
Not implemented yet
```

cuando corresponda.

---

# 62. Decisiones aún abiertas

No cierres silenciosamente decisiones marcadas como abiertas en `PROJECT_RULES.md`.

Ejemplos:

- lenguaje condicional exacto;
- CEL;
- runtime JS;
- formato final de ResourceDataset;
- versionado de forms;
- modelo definitivo de submissions;
- plugin system;
- webhooks;
- file upload;
- auth de respondientes;
- multiusuario.

Si el hito exige cerrar alguna, presenta la decisión y su razonamiento antes de hacer que se vuelva difícil de revertir.

---

# 63. No sobreingeniería

No introduzcas prematuramente:

- microservicios;
- Kubernetes;
- Redis;
- message queues;
- event buses;
- service mesh;
- CQRS;
- GraphQL;
- plugin frameworks complejos.

Solo cuando una necesidad concreta lo justifique.

---

# 64. No degradar seguridad por velocidad

Está prohibido resolver temporalmente problemas mediante:

```text
desactivar CSRF
permitir CORS *
ejecutar como root
abrir PostgreSQL
usar chmod 777
montar Docker socket
guardar passwords en texto plano
desactivar TLS
desactivar validación
usar eval
```

Si una función no puede implementarse de forma razonablemente segura en el hito actual:

- detente;
- explica el bloqueo;
- propone una alternativa segura.

---

# 65. Performance

No optimices prematuramente.

Primero:

- corrección;
- integridad;
- seguridad;
- claridad.

Cuando optimices:

- mide;
- identifica cuello real;
- conserva tests;
- evita caches que cambien semántica sin invalidación clara.

---

# 66. Errores de configuración

Los errores de configuración deben fallar de forma clara.

No uses defaults inseguros para:

- secrets;
- DB credentials;
- admin credentials;
- producción.

En producción, secretos obligatorios faltantes deben impedir startup.

---

# 67. Startup

El startup debe ser determinista.

Patrón general:

```text
wait for DB
  ->
migrate
  ->
generic initialization
  ->
validate required runtime state
  ->
serve
```

No uses sleeps fijos como mecanismo principal para esperar DB.

---

# 68. Healthchecks

`/health` debe:

- comprobar que la app vive;
- comprobar DB de forma ligera;
- no revelar secretos;
- no realizar trabajo pesado;
- no depender de datos de usuario.

---

# 69. API errors

Los clientes deben poder reaccionar a códigos estables.

Prefiere:

```json
{
  "error": {
    "code": "RESOURCE_ALREADY_RESERVED",
    "field": "room",
    "message": "..."
  }
}
```

sobre parsing de texto humano.

Los mensajes pueden cambiar; los códigos deben ser más estables.

---

# 70. UI y lógica

Nunca dupliques lógica crítica solo en UI.

Si la UI puede:

```text
ocultar opción
deshabilitar botón
evitar selección
```

el backend igualmente valida esa condición.

---

# 71. Accesibilidad

La UI builtin debe priorizar:

- labels reales;
- focus visible;
- teclado;
- contraste;
- mensajes de error asociados;
- semántica HTML;
- ARIA solo donde sea necesario.

No sacrifiques accesibilidad por estética.

---

# 72. Diseño visual

La UI builtin debe ser deliberadamente moderada.

Objetivo:

```text
limpia
moderna
simple
personalizable
```

No:

```text
excesivamente animada
pesada
dependiente de JS
dependiente de frameworks
```

El proyecto es Core-first, no UI-first.

---

# 73. Página custom y archivos estáticos

Una `ui/` personalizada o `/data/site/`:

- no obtiene acceso especial;
- no puede leer archivos fuera de su raíz;
- no puede acceder a secrets;
- no puede llamar endpoints admin sin auth;
- no puede saltarse Rules Engine.

Sirve archivos de forma segura y con Content-Type correcto.

---

# 74. Import/export futuro

Cuando se implemente:

- evita zip-slip;
- extrae en temporal;
- valida todo antes de instalar;
- nunca importa secrets de infraestructura;
- nunca confía en paths del archive;
- instala atómicamente.

---

# 75. Scope de una tarea

Antes de programar, declara brevemente:

- objetivo;
- archivos afectados;
- comportamiento que cambia;
- comportamiento que NO debe cambiar;
- tests que se ejecutarán.

No hace falta un ensayo, pero sí claridad.

---

# 76. Si algo no está definido

Cuando falte una decisión:

### Si es local y reversible

Elige la solución mínima coherente con los documentos y registra la suposición.

### Si afecta:

- formato público;
- schema;
- API;
- seguridad;
- persistencia;
- compatibilidad;
- arquitectura futura;

NO la decidas silenciosamente.

Pregunta o presenta opciones.

---

# 77. Entrega de cada tarea

Al finalizar una tarea importante, resume:

1. qué se cambió;
2. qué archivos se tocaron;
3. qué decisiones se tomaron;
4. qué NO se implementó;
5. qué tests se ejecutaron;
6. resultados;
7. limitaciones;
8. riesgos/deuda real;
9. siguiente hito preparado.

No declares:

```text
"todo funciona"
```

sin haber ejecutado verificaciones.

---

# 78. Regla de finalización

Una tarea NO está terminada porque el código compile.

Debe cumplir:

```text
correcto
+
probado
+
seguro
+
documentado
+
dentro del scope
```

---

# 79. Filosofía final para Claude Code

Al trabajar en FormManager:

> Prefiere una base pequeña y correcta a una arquitectura grande y prematura.

> Prefiere un error explícito a una conversión silenciosa.

> Prefiere una regla declarativa a código arbitrario.

> Prefiere PostgreSQL como garantía runtime a confiar en la UI.

> Prefiere separar presentación de lógica.

> Prefiere conservar invariantes de seguridad antes que copiar estructura del prototipo.

> Prefiere detenerse ante una decisión arquitectónica no definida antes que inventarla.

> Nunca conviertas FormManager nuevamente en una aplicación específica para un único formulario.
