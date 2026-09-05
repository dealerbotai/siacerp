# ESQUEMA DE TRABAJO — SIAC ERP (AGENTS.md)

> **Este archivo es la CONSTITUCIÓN del proyecto.** Lo leen obligatoriamente
> todas las IAs (Buffy, Cursor, Copilot, etc.) al iniciar sesión, y es la
> referencia única para cualquier programador humano. Si existe conflicto
> entre este archivo y cualquier otro documento, **este archivo gana**.
>
> Viaja con el repositorio: aplica en cualquier máquina que lo clone.

---

## 0. Cómo usar este documento (leyenda)

- **`[REGLAS]`** — reglas **obligatorias e innegociables**. Se numeran con
  prefijo por área (N = nomenclatura, A = arquitectura, D = base de datos,
  C = componentes, U = UI, P = permisos, V = validación, G = git, I = IA,
  RD = decisiones de diseño aprobadas por el usuario).
  Una IA **DEBE** cumplirlas todas y puede citarlas por número.
- **`[CONTEXTO]`** — explicación del *porqué*. No es obligación, es comprensión.
- **`[EJEMPLO]`** — código real o patrón del proyecto que ilustra la regla.
- **`🚫 PROHIBIDO`** — lo que nunca se debe hacer (aunque "funcione").

**Para una IA nueva:** lee completo este archivo + `README.md` + la estructura
de `src/` antes de tocar una sola línea. Luego usa la **Checklist de
conformidad** (sección 13) antes de dar tu trabajo por terminado.

---

## 1. Identidad del proyecto

**[CONTEXTO]** SIAC ERP (Sistema Integral de Administración y Control) es una
aplicación de **escritorio** para la gestión de una **fábrica de calzado**:
órdenes de compra, inventario de insumos, planificación de producción,
producto terminado y control de usuarios/permisos.

| Aspecto | Valor |
|---|---|
| Interfaz | PySide6 (Qt for Python ≥ 6.5) |
| Base de datos | SQLite (local/desarrollo) o PostgreSQL 14+ (producción, ver RD-5) |
| Reportes | PDF (reportlab) y Excel (openpyxl) |
| Contraseñas | bcrypt |
| Idioma del código | **Español** (identificadores, UI, mensajes, BD, docstrings) |
| Licencia | Propietaria — no es open source (© 2026, M. F. Luevano) |

- **[REGLAS N-00]** Todo el código, nombres, mensajes al usuario, docstrings,
  comentarios y datos precargados se escriben en **español**.
- **[REGLAS N-01]** Está **PROHIBIDO** mezclar inglés y español en
  identificadores (p. ej. `get_orden` o `OrderModel` son incorrectos; lo
  correcto es `obtener_orden` / `OrdenModel`). Excepciones históricas
  documentadas: el componente registrado `complexGrid` y las clases del stack
  `ComplexGrid` (se conservan por compatibilidad, no son modelo a seguir).

---

## 1.1 Decisiones de diseño aprobadas (RD-*) — hoja de ruta

**[CONTEXTO]** Decisiones tomadas por el usuario; son la **dirección de diseño
obligatoria**. Marcan el **estado objetivo**; mientras una decisión esté
marcada como pendiente, el código actual sigue siendo la fuente de verdad del
comportamiento. **PROHIBIDO** implementar decisiones pendientes "por su cuenta":
requieren tarea aprobada y migración.

| ID | Decisión aprobada | Estado |
|---|---|---|
| **RD-1** | **Unificar puntos y tallas** en un solo catálogo: **`tallas_catalogo`**. Son la misma cosa; en calzado se avanza de medio en medio punto. Se configura con generación en serie "de X a Y talla" (**corrida** = rango de tallas). **Sin campo `orden`**: el orden se deriva del valor numérico. Caso particular: la **compra de suela** se maneja por **puntos cerrados** (se capturan solo las tallas que apliquen en la matriz). | ✅ Aplicada (`tallas_catalogo`) |
| **RD-2** | **Módulo Clientes y Pedidos** (próxima versión): pedidos de clientes que pueden **programarse** e integrarse en una **programación semanal**; la programación semanal alimentará las **órdenes de producción**. Alcance aún por definir con el cliente. Traerá sus propios estatus. | 🚧 Próximamente |
| **RD-3** | **Diseñador e impresor de etiquetas**: herramienta existente en otra terminal de trabajo (fuera de este repositorio por ahora). | 🔧 Externo |
| **RD-4** | **Git — Flujo de trabajo aprobado (fork workflow)**: `origin` = `dealerbotai/siacerp` (nuestro fork). `upstream` = `gorettiboots-commits/siacerp` (repo original). `productivo1` = rama de desarrollo activo. `main` = versión estable/producción. Flujo: `sincronizar.bat` (fetch upstream + merge → productivo1) → trabajar → `publicar.bat` (push a origin) → `release.bat` (merge productivo1 → main → tag → push origin → opcional PR a upstream). Scripts en raíz del proyecto. | ✅ Aplicada |
| **RD-5** | **Arquitectura de Motor BD y Sync**: **SQLite/PostgreSQL** como motor de lectura/escritura local offline. **Supabase** actúa exclusivamente como middleware de sincronización en segundo plano entre terminales multi-tenant. | 🎯 Implementación Offline-First Sync |
| **RD-6** | **Pruebas**: todo control/componente aprobado desde el Sandbox **DEBE** incluir su prueba `pytest` antes de registrarse en el catálogo. | ✅ Vigente (regla C-07) |
| **RD-7** | **Archivos de raíz** (`sitio web/`, `video.mp4`, `default.jpg`, `logo.png`) son **parte del proyecto** y se documentan (sección 3.1). `opencode.json` contiene **credenciales** y NO se sube a git. | ✅ Documentado |
| **RD-8** | **Auto-actualizador de aplicativo**: El sistema consulta de manera asíncrona un manifiesto remoto (`version.json`). Si detecta una versión superior a `__version__` y hay red, pregunta al usuario mediante un modal si desea actualizar automáticamente. | ✅ Implementada (reglas D-21 a D-25) |
| **RD-9** | **Identidad global por registro (columna `uuid`)**: dos terminales de la MISMA empresa pueden generar el mismo `id` INTEGER offline y pisarse en Supabase. Solución aditiva: columna `uuid` (uuid4) en cada tabla sincronizable; el `id` INTEGER local se conserva como clave interna y el `uuid` es la identidad estable de merge entre terminales. Implementación completa en repo: fase 1 local (`_migrar_uuids` + backfill + garantía en `sync_hooks` + upsert local por uuid); fase 2 de subida vía RPC `subir_registro_sync` (scripts remotos `mobile/supabase/005_...` y `006_...`: columna + índice único `(empresa_id, uuid)` + default `gen_random_uuid()`, merge por uuid conservando el id remoto, adopción de legados sin uuid, regla de convergencia por "huella" conmutable, y colisiones reales de id reubicadas en **espacio negativo** que nunca choca con secuencias/triggers/móvil). El móvil ya envía `uuid` en sus inserts. **Activación:** aplicar 005 y 006 en Supabase y luego encender `[sync] subir_por_uuid=1` en `config.ini` (el camino REST previo queda como respaldo). | ✅ Implementada (activar tras desplegar 005+006) |

> **Nota (2026-09-05):** el cuerpo de las reglas **D-11 a D-25** (RLS
> multi-tenant, servicios TypeScript móvil y auto-actualizador — citadas en
> CHANGELOG y en la fila RD-8) se perdió en un merge que truncó este
> documento (commit 282c03d) y no sobrevive en el historial. Deben
> re-documentarse; mientras tanto, las referencias existentes quedan como
> están.

---

## 2. Glosario de dominio (léelo antes de tocar datos)

**[CONTEXTO]** Este glosario elimina la ambigüedad más común del proyecto. Una
IA que confunda estos términos producirá resultados incorrectos.

| Término | Significado en SIAC | Dónde vive |
|---|---|---|
| **Talla / Punto** | **Son la misma cosa**: catálogo único **`tallas_catalogo`** (RD-1, aplicado) con los valores históricos unificados (`00`–`13` y `22`–`31`), **sin campo `orden`**. Caso particular: suela por **tallas/puntos cerrados** (solo se capturan las tallas que apliquen en la matriz). | `tallas_catalogo` |
| **Corrida** | **Rango de tallas** (de X a Y, en pasos de medio punto) usado en los procesos: p. ej. "corrida del punto 00 al 13" en un lote de compra. Se configura con la generación en serie. | concepto de proceso (no es tabla) |
| **Tenant / Empresa** | Identificador de la empresa o estación de trabajo (`tenant_id`; en el esquema remoto, `empresa_id`). Aísla los datos entre empresas en Supabase. | Columna `empresa_id` (UUID) |
| **UUID v4 / uuid** | Identificador único global (uuid4) en la columna `uuid` de cada tabla sincronizable (RD-9, aplicado). El `id` INTEGER local se conserva como clave interna; el `uuid` es la identidad estable entre terminales de la misma empresa y la clave de merge en Supabase (evita que dos terminales offline se pisen). | Columna `uuid` de tablas sincronizables |
| **Cola de Sync (Outbox)** | Tabla local donde se registran las transacciones pendientes por enviar a Supabase. | `sync_queue` |
| **Soft Delete** | Borrado lógico mediante `is_deleted = 1` para permitir que la eliminación se replique entre terminales. | Columna `is_deleted` |
| **Insumo** | Materia prima (piel, suela, forro…). | `insumos` |
| **Variante** | Un modelo × color × piel (× talla opcional). | `variantes` |
| **Modelo** | Modelo de zapato con su lista de materiales (BOM). | `modelos`, `lista_materiales` |
| **OC** | Orden de Compra. Folio `OC-0001`. Estatus: `pendiente`, `recibida`, `cancelada`, `recibida_con_diferencias`. Tipo: `orden` o `factura`. | `ordenes_compra` |
| **Factura** | Documento tipo `factura`: folio capturado **manualmente** (`FAC-...`), no recibe inventario, fila resaltada en verde claro `#daf2d0`. | `ordenes_compra.tipo` |
| **OP** | Orden de Producción. Folio `OP-0001`. Estatus: `planeada`, etc. | `ordenes_produccion` |
| **PT** | Producto Terminado (inventario por variante × talla). | `inventario_pt` |
| **Pares por punto/talla** | Cantidad de pares asignada a cada punto (OC) o talla (OP). | `detalle_orden_compra_puntos`, `matriz_tallas_op` |
| **Estación** | Etapa del taller: Corte, Pespunte, Montado, Ensuelado, Acabado, Empaque. | `estaciones_produccion` |
| **Sandbox** | Área de pruebas de controles (solo `admin`). | `src/views/sandbox_view.py` |
| **Control / Componente** | Widget reutilizable aprobado y registrado en el catálogo. | `src/components/` |

### Estatus actuales por catálogo (referencia — se amplía al crear módulos)

| Catálogo | Columna | Estatus válidos hoy |
|---|---|---|
| Orden de Compra | `ordenes_compra.estatus` | `pendiente`, `recibida`, `cancelada`, `recibida_con_diferencias` |
| Orden de Compra | `ordenes_compra.tipo` | `orden`, `factura` |
| Orden de Producción | `ordenes_produccion.estatus` | `planeada`, `en_produccion`, `terminada` |
| Orden de Producción | `ordenes_produccion.prioridad` | `normal` (ampliable) |
| Seguimiento por estación | `seguimiento_produccion.estatus` | `pendiente`, `en_proceso`, `completado` |
| Movimientos de inventario | `movimiento_inventario.tipo_movimiento` | `entrada`, `salida`, `ajuste` |
| Cola de Sincronización | `sync_queue.estatus` | `pendiente`, `enviado`, `error` |
| Catálogos | `activo` | `1` (activo) / `0` (desactivado) |

- **[REGLAS N-02]** **Puntos y tallas son la misma cosa** y están **unificados**
  en el catálogo único `tallas_catalogo` (RD-1). Todo el sistema habla de
  **tallas** ("corrida" = rango de X a Y). **PROHIBIDO** volver a crear
  tablas/columnas `punto`/`puntos` o catálogos paralelos de medida.
- **[REGLAS N-02b]** Los **estatus NO forman una lista cerrada única**: varían
  por catálogo (RD-2 traerá estatus de pedidos y programación). Reglas
  obligatorias: español, minúscula, `snake_case`; todo estatus **NUEVO** se
  documenta en la tabla de estatus de esta sección.

---

## 3. Estructura del repositorio

```
siacerp/
├── main.py                     # Único punto de entrada
├── run.bat                     # Lanzador sin consola (pythonw)
├── config.example.ini          # Plantilla de configuración
├── config.ini                  # Config LOCAL — NUNCA se sube a git
├── requirements.txt            # Dependencias de producción
├── requirements-dev.txt        # Dependencias de desarrollo (pytest)
├── DIRECTORIO.xlsx             # Plantilla de importación de proveedores
├── AGENTS.md                   # ESTE documento (constitución)
├── video.mp4                   # Video de bienvenida (splash de MainWindow)
├── default.jpg / logo.png      # Imágenes de la raíz (ver sección 3.1)
├── opencode.json               # Config OpenCode con CREDENCIAL — NO subir a git
├── scripts/
│   └── importar_directorio.py  # Importación masiva idempotente desde Excel
├── sitio web/                  # Landing page de la marca Goretti (ver 3.1)
├── tests/                      # Pruebas pytest (conftest.py con fixtures Qt)
└── src/
    ├── database/               # schema.sql + db_manager.py (esquema y migraciones)
    ├── models/                 # Capa de acceso a datos (SQL) — {Entidad}Model
    ├── controllers/            # Lógica de negocio — {Modulo}Controller
    ├── views/                  # Vistas Qt + diálogos (dialogs.py, sandbox, kanban…)
    ├── components/             # Componentes aprobados (catálogo) + __init__.py
    └── utils/                  # Helpers: export_utils, folios, table_utils,
                                # ui_helpers, icons, security, styles.qss, odoo_list
```

### 3.1 Assets y archivos de la raíz (RD-7)

| Archivo / carpeta | Qué es | Regla |
|---|---|---|
| `sitio web/` | Landing page de marketing de la marca Goretti (`inicio.html`, Tailwind + Google Fonts, carpeta `img/`). **Independiente del ERP**; no se conecta a la BD. | Parte del proyecto — editar sin afectar el ERP |
| `video.mp4` | Video de bienvenida usado por `MainWindow` como splash. | Parte del proyecto |
| `default.jpg` | Imagen en la raíz, sin uso detectado en el código. | Parte del proyecto — documentar si se usa |
| `logo.png` | Imagen en la raíz; el código usa `src/views/assets/logo.png` (posible duplicado). | Parte del proyecto |
| `opencode.json` | Configuración de OpenCode con **API key (credencial)**. | 🚫 **PROHIBIDO subir a git** — agregar a `.gitignore` |

---

## 4. Nomenclatura de código

### 4.1 Archivos

- **[REGLAS N-10]** Archivos en `snake_case`, en español, con **sufijo de capa**:
  `{entidad}_model.py`, `{modulo}_controller.py`, `{modulo}_view.py`,
  `{nombre}_utils.py`. Excepciones: `dialogs.py` (todos los diálogos) y
  `main.py`.
- **[REGLAS N-11]** Un archivo nuevo **DEBE** ubicarse en la capa que le
  corresponde (model/controller/view/utils/components) — jamás en la raíz de
  `src/` ni en una capa equivocada.

### 4.2 Clases

- **[REGLAS N-12]** Clases en `PascalCase`, español, con **sufijo de rol**:

| Rol | Sufijo | Ejemplo real |
|---|---|---|
| Modelo | `Model` | `ProveedorModel`, `OrdenCompraModel`, `TallasModel` |
| Controller | `Controller` | `OrdenesCompraController`, `ProduccionController` |
| Vista principal | `View` | `StockView`, `ProduccionView`, `LoginView` |
| Diálogo | `Dialog` | `DialogOrdenCompra`, `DialogInsumo` |
| Vista de listado | `ListView` | `OdooListView` |
| Widget/rol interno privado | `_` + rol | `_TabPuntos`, `_CardNotificacion`, `_KanbanColumn` |

- **[REGLAS N-13]** Clases **privadas** (uso interno de un archivo) llevan
  prefijo `_` y **no** se exportan en `__init__.py`.

### 4.3 Funciones y métodos

- **[REGLAS N-14]** `snake_case`, español, con **verbo al inicio**:
  `listar_*`, `crear_*`, `actualizar_*`, `obtener_*`, `buscar_*`, `guardar_*`,
  `desactivar_*`, `activar_*`, `exportar_*`, `imprimir_*`, `_cargar_*`,
  `_setup_*`, `_load_*`.
- **[REGLAS N-15]** Métodos privados con prefijo `_` (`_setup_ui`,
  `_load_data`, `_on_puntos_toggled`). Slots de señales Qt con prefijo `_on_`.
- **[REGLAS N-16]** **Type hints obligatorios** en firmas de funciones y
  métodos públicos (`-> None`, `-> int`, `-> list[dict]`, `QWidget | None`).
  Usar `from __future__ import annotations` cuando haga falta.
- **[REGLAS N-17]** El contrato de la sección 4.4 es el **patrón objetivo para
  código NUEVO**, no una garantía de las firmas existentes. Métodos reales como
  `guardar()`, `listar_por_insumo()`, `obtener_detalle()`, `folio_existe()` o
  `agregar_detalle()` son válidos y **no se "normalizan"** a otro nombre: el
  código que ya funciona se deja como está.

### 4.4 Patrones estándar por capa (contratos)

**[CONTEXTO]** Para que cualquier IA sepa qué esperar sin leer todo el código,
cada capa tiene un **contrato**:

- **Modelos** — métodos CRUD estándar con estas firmas (ver sección 6):
  - `listar(solo_activos: bool = True) -> list[dict]`
  - `obtener(id: int) -> dict | None`
  - `crear(...) -> int` (regresa `cursor.lastrowid`)
  - `actualizar(id: int, ...) -> None`
  - `desactivar(id: int) -> None` / `activar(id: int) -> None` (borrado lógico)
  - `buscar(termino: str) -> list[dict]`
  - En `__init__`: `self.db = DatabaseManager()`.
- **Controllers** — en `__init__` exponen los modelos como `self.{x}_model`;
  cada método público delega en uno o más modelos (la lógica compuesta vive
  aquí, no en la vista).
- **Vistas** — patrón fijo: `_setup_ui()` (construye UI), `_setup_tab_*()`,
  `_load_*()` (carga datos), `_buscar(texto)`, `_nueva_*()`, `_exportar()`,
  `_imprimir()`. Para `ComplexGrid`: renderers `_fila_x`, `_claves_x`,
  `_estilo_x`, `_tarjeta_x`, `_lista_x`.

---

## 5. Arquitectura por capas (MVC)

- **[REGLAS A-01]** **Las vistas NUNCA tocan la base de datos ni los modelos
  directamente.** Siempre pasan por su controller. Las vistas reciben el
  controller por constructor (`StockView(controller)`).
- **[REGLAS A-02]** **Los modelos solo hacen SQL.** No contienen lógica de
  negocio ni de UI, no llaman a otros modelos entre sí y no importan nada de
  `views/`.
- **[REGLAS A-03]** **Los controllers no importan Qt.** Contienen la lógica de
  negocio y agregan modelos.
- **[REGLAS A-04]** **`utils/` solo contiene helpers puros** (sin estado
  persistente) o widgets genéricos sin lógica de negocio.
- **[REGLAS A-05]** Flujo de arranque (no modificar sin causa):
  `main.py` → `QApplication` → `load_styles()` → `DatabaseManager().initialize_schema()`
  → `MainWindow` → `LoginView` → vistas según permisos.

---

## 6. Base de datos

### 6.1 Reglas de esquema

- **[REGLAS D-01]** Fuente de verdad del esquema: `src/database/schema.sql`
  (compatible SQLite **y** PostgreSQL). **Toda** tabla/columna nueva se agrega
  ahí con `CREATE TABLE IF NOT EXISTS` e `INSERT OR IGNORE` para datos
  iniciales.
- **[REGLAS D-02]** Nombres de tabla: **plural**, `snake_case`, español.
  - Tablas de detalle: prefijo `detalle_` (`detalle_orden_compra`,
    `detalle_orden_compra_puntos`).
  - Catálogos configurables: sufijo `_catalogo` (`tallas_catalogo`,
    `colores_catalogo`).
  - Junturas N:M: `tabla_a_tabla_b` (`proveedor_insumos`, `usuario_permisos`).
  - Acrónimos de módulo: `_op` (órdenes de producción), `_pt` (producto
    terminado), `_corrida` (tallas).
- **[REGLAS D-02b]** **Los nombres de tablas y columnas existentes están
  CONGELADOS.** Tablas históricas como `lista_materiales`, `unidades_medida`
  o `movimiento_inventario` no siguen la regla de plural y **NO se renombran**
  jamás. La regla D-02 aplica **solo a tablas/columnas nuevas**. Renombrar una
  tabla existente se considera cambio destructivo y requiere aprobación
  explícita del usuario.
- **[REGLAS D-03]** Columnas: `snake_case`, español, singular.
  - PK: `id INTEGER PRIMARY KEY AUTOINCREMENT`.
  - FK: `{tabla}_id INTEGER NOT NULL REFERENCES {tabla}(id)`.
  - Booleanos: `activo INTEGER NOT NULL DEFAULT 1` (0/1, borrado lógico).
  - Fechas: `created_at` / `updated_at` `TEXT NOT NULL DEFAULT (datetime('now'))`.
  - Estatus/valores enumerados: **español, minúscula** (`'pendiente'`,
    `'planeada'`, `'entrada'/'salida'/'ajuste'`, `tipo 'orden'/'factura'`).
- **[REGLAS D-04]** Toda consulta con parámetros usa **placeholders**
  (`?` en SQLite, `%s` en PostgreSQL). **PROHIBIDO** interpolar valores de
  usuario en SQL (`f"...{valor}..."`). Solo se permite f-string para nombres
  de tabla/columna validados en listas fijas.
- **[REGLAS D-05]** Toda lectura/escritura pasa por `DatabaseManager`
  (`fetch_all`, `fetch_one`, `execute`). Es **singleton**: una sola conexión.
  Nunca crear conexiones `sqlite3` sueltas.

### 6.2 Migraciones

- **[REGLAS D-06]** Las migraciones viven en `DatabaseManager._migrar()` y se
  ejecutan automáticamente en cada arranque tras `initialize_schema()`.
  **Nunca** se pide al usuario ejecutar SQL a mano.
- **[REGLAS D-07]** Las migraciones **DEBEN ser aditivas y no destructivas**:
  - Columna nueva: `ALTER TABLE ... ADD COLUMN` (verificando con
    `PRAGMA table_info` en SQLite o `IF NOT EXISTS` en PostgreSQL).
  - Cambio estructural de tabla: recrear con `PRAGMA foreign_keys=OFF`,
    renombrar a `_tmp`, crear tabla nueva, copiar datos, borrar `_tmp`,
    reactivar FKs — **nunca perder datos**.
  - Cada bloque va en `try/except` con `print("Migración ...: {e}")` para no
    abortar el arranque.

### 6.3 Folios

- **[REGLAS D-08]** Los folios secuenciales se generan únicamente con
  `src/utils/folios.py::siguiente_folio(tabla, columna, prefijo, digitos=4)`:
  formato `PREFIJO-0001`. Prefijos del sistema: `OC-` (compras), `OP-`
  (producción). Las **facturas** capturan su folio **manualmente** (`FAC-...`).
  En insumos se usa `INS-` (código de insumo).
- **[REGLAS D-09]** El campo `orden` de catálogos numéricos de medida quedó
  **eliminado** con la migración RD-1: `tallas_catalogo` no tiene `orden` y el
  orden se deriva de `CAST(talla AS REAL)`. No reintroducir `orden` en
  catálogos numéricos nuevos.
- **[REGLAS D-10]** Los estatus son **por catálogo** (tabla de la sección 2):
  español, minúscula, `snake_case`. Crear un estatus nuevo **sin documentarlo**
  en esa tabla está **PROHIBIDO**.

---

## 7. Controles y componentes (ciclo de vida)

**[CONTEXTO]** El Sandbox es el área donde se prueban controles/componentes
antes de aprobarlos. Vista: `src/views/sandbox_view.py` (`SandboxView`), visible
solo para el rol `admin`. Todo control experimental se desarrolla aquí como
prototipo (el prototipo **puede** ser código de prueba) hasta que el usuario
lo apruebe.

### Ciclo de vida de un control

1. **Prototipo en Sandbox**: la idea se desarrolla primero en `SandboxView`
   (p. ej. `DialogControlesTallas`) para probarla.
2. **Aprobar**: cuando el usuario diga **"aprobar X control de sandbox"**
   (o "aprobar X"), desarrollar el componente de forma **reutilizable** y
   agregarlo al **stack de componentes propios del sistema** en `src/components/`,
   registrándolo en el catálogo con `registrar_componente(...)`.
   El sandbox deja de ser el dueño del código: pasa a ser una demo que usa el
   componente aprobado.
3. **Listar**: cuando el usuario pida **"lista los componentes disponibles"**,
   responder con `src.components.listar_componentes()` (nombre + descripción).
4. **Usar**: cuando el usuario diga **"usa X componente en determinada tarea"**,
   importar el componente desde `src.components.obtener_componente("X")` (o con
   import directo) y aplicarlo en la tarea indicada.

### Reglas del catálogo

- **[REGLAS C-01]** Los componentes aprobados viven en `src/components/` o, si
  ya existían en `src/utils/`, se registran en el catálogo **sin duplicar
  código** (caso real: `odoo_list`).
- **[REGLAS C-02]** Todo componente aprobado **DEBE** registrarse en
  `src/components/__init__.py` con `registrar_componente(nombre, clase,
  descripcion)`.
- **[REGLAS C-03]** `nombre` de registro: `snake_case` en minúscula
  (`odoo_list`, `matriz_tallas`); `descripcion` en español, una frase.
  Excepción histórica congelada: `complexGrid` (se conserva por compatibilidad;
  los componentes NUEVOS usan `snake_case`).
- **[REGLAS C-04]** El sandbox es el **único** lugar para prototipos. Está
  **PROHIBIDO** crear componentes nuevos directamente en `src/components/`
  sin haber pasado por el Sandbox y la aprobación del usuario.
- **[REGLAS C-05]** Un componente aprobado expone su API pública en docstring
  (constructores, métodos y propiedades), y sus elementos de UI relevantes
  como **propiedades** para referenciarlos con precisión (ej. `celdas`,
  `encabezados` en `matriz_tallas`).
- **[REGLAS C-06]** El registro en `src/components/__init__.py` usa imports
  después de la definición con `# noqa: E402` (patrón ya establecido); un
  componente nuevo se registra con el mismo estilo para no romper el lint.
- **[REGLAS C-07]** Un componente solo se registra en el catálogo si incluye
  su **prueba `pytest`** en `tests/` (decisión RD-6, obligatoria para todo
  componente aprobado). La prueba debe correr con `QT_QPA_PLATFORM=offscreen`
  y no dejar timers/animaciones activos.

### Catálogo actual (a la fecha)

| Nombre | Descripción |
|---|---|
| `odoo_list` | Vista de listado con alternador tabla/lista/iconos (tarjetas), columnas ordenables y selección/doble clic configurable |
| `matriz_tallas` | Matriz de tallas por bloques: encabezado negro/texto blanco, filas de captura, navegación Enter/Tab y celdas sin flechas numéricas |
| `complexGrid` | Tabla de datos con búsqueda, filtros, agrupación, vistas lista/iconos/tabla, acciones por registro y exportación Excel/PDF/Imprimir |
| `date_picker` | Selector de fecha con calendario emergente (formato dd/MM/yyyy, conversión ISO para BD) |
| `campo_historico` | Campo de texto con histórico de capturas (`historico_campos`): al enfocar/clic despliega el histórico del campo y autocompleta; registra la captura al salir. Incluye `InstaladorHistorico` para aplicarlo a todo el sistema |

---

## 8. Interfaz de usuario

- **[REGLAS U-01]** Los estilos globales viven en `src/utils/styles.qss` y se
  cargan con `load_styles()`. El estilizado se hace por **`objectName`**
  (`btnPrimary`, `card`, `headerBar`, `sectionTitle`…), **no** con
  `setStyleSheet` inline salvo colores dinámicos (p. ej. `crear_tarjeta`).
- **[REGLAS U-02]** Usar los helpers de `src/utils/ui_helpers.py`:
  `crear_boton`, `crear_tarjeta`, `crear_seccion`, `crear_header`.
- **[REGLAS U-03]** Iconos desde `src/utils/icons.py` (`tile_icon`, `mono_icon`;
  SVG embebidos). **PROHIBIDO** emojis/iconos por string arbitrario.
- **[REGLAS U-04]** Listados → `ComplexGrid` o `OdooListView` (componentes del
  catálogo). Tablas de captura → estilo Excel con `table_utils.configurar_tabla_excel`.
- **[REGLAS U-05]** Colores de estado: fila **recibida** o tipo **factura** en
  OC → `#daf2d0`. Cualquier estado visual nuevo se documenta aquí.
- **[REGLAS U-06]** Todo texto visible al usuario en español, mayúsculas solo
  donde corresponda. Botones con verbo imperativo ("Guardar", "Cancelar").

---

## 9. Seguridad y permisos (ACL)

- **[REGLAS P-01]** El login es **obligatorio**; usuario inicial `admin` /
  `admin123` (cambiar en producción). Contraseñas con bcrypt
  (`src/utils/security.py`).
- **[REGLAS P-02]** Permisos por **módulo × acción**: acciones fijas
  `ver`, `crear`, `editar`, `eliminar`, `exportar`; módulos
  `ordenes_compra`, `produccion`, `inventario`, `configuracion`, `usuarios`.
- **[REGLAS P-03]** Las vistas reciben el diccionario `permisos` y verifican
  con el helper `tiene(permisos, modulo, accion)` de `src/models/accesos_model.py`
  antes de habilitar/ocultar acciones. **PROHIBIDO** mostrar botones de
  acciones sin permiso.
- **[REGLAS P-04]** El **Sandbox** se muestra únicamente al rol `admin`.

---

## 10. Procesos de validación

- **[REGLAS V-01]** Lint: `flake8 . --select=E9,F63,F7,F82 --show-source`
  (errores bloqueantes en CI). Línea máxima: **127** caracteres
  (`.flake8`).
- **[REGLAS V-02]** Tests: `pytest` desde la raíz (`pytest.ini` define
  `pythonpath = .`). Las pruebas Qt requieren `QT_QPA_PLATFORM=offscreen` y
  usan el fixture de sesión `qapp` + teardown autouse de `tests/conftest.py`
  (evita el segfault de PySide6 al cerrar). **NO** escribir tests que creen
  timers/animaciones sin detenerlos. Todo componente aprobado DEBE traer su
  prueba (reglas C-07 / RD-6).
- **[REGLAS V-03]** **Antes de declarar terminado un cambio** se DEBE correr
  (al menos sobre el área modificada):
  1. `flake8 . --select=E9,F63,F7,F82 --show-source --statistics`
  2. `pytest`
  3. Una revisión del diff (la hace un revisor/IA) buscando violaciones a este
     documento.
- **[REGLAS V-04]** CI (`.github/workflows/siaci.yml`): Ubuntu + Python 3.12,
  `QT_QPA_PLATFORM=offscreen`, `LIBGL_ALWAYS_SOFTWARE=1`, instala
  `libegl1 libgl1 libxkbcommon0 libdbus-1-3`, corre flake8 (select E9,F63,F7,F82)
  y pytest. Un cambio que rompa CI **no** se considera terminado.

---

## 11. Git y repositorio

- **[REGLAS G-01]** **Flujo git (decisión RD-4):** se hizo merge de
  `productivo1` → `main`; `main` es la **versión oficial** hasta el primer
  release. Después del release: **rama por tarea** (`feature/nombre`) + PR
  hacia `productivo1` y `main`. El CI escucha `productivo1` y `main`.
- **[REGLAS G-02]** **PROHIBIDO** subir `config.ini` (puede contener
  credenciales), `goretti_erp.db` o datos de producción.
- **[REGLAS G-03]** Mensajes de commit en español, descriptivos del cambio
  (`"Agrega migración de columnas de pago en OC"`).
- **[REGLAS G-04]** No ejecutar `git push` / `git commit` ni scripts con
  efectos en producción sin orden explícita del usuario.

---

## 12. Reglas obligatorias para IAs (I)

### Antes de editar (pre-condiciones)

- **[REGLAS I-01]** Leer este `AGENTS.md` completo y el `README.md`; explorar
  la estructura `src/` y los archivos vecinos al que se va a tocar.
- **[REGLAS I-02]** Verificar con `src.components.listar_componentes()` si ya
  existe un componente que resuelva la tarea. **PROHIBIDO** reimplementar lo
  que ya existe (código, helpers, componentes).
- **[REGLAS I-03]** Antes de usar una librería: verificar que esté en
  `requirements.txt`. **PROHIBIDO** asumir librerías disponibles o agregarlas
  sin autorización.
- **[REGLAS I-04]** No modificar datos de producción ni `config.ini`. Los
  cambios de esquema van por migraciones aditivas (D-06/D-07).

### Durante la edición

- **[REGLAS I-05]** Hacer el **menor cambio posible** que cumpla la petición
  (regla de minimalismo). No refactorizar código ajeno "de paso".
- **[REGLAS I-06]** Respetar estrictamente nomenclatura (sección 4), contratos
  por capa (4.4), esquema y folios (sección 6) y ciclo de componentes
  (sección 7).
- **[REGLAS I-07]** Ante una decisión importante o ambigua (nombres de tablas,
  cambios destructivos, nuevas dependencias, alcance de un cambio): **preguntar
  al usuario antes de actuar**.
- **[REGLAS I-08]** Si el usuario usa `@Agente`, se DEBE invocar a ese agente.

### Después de editar

- **[REGLAS I-09]** Correr la validación (V-03) y la **Checklist de
  conformidad** (sección 13).
- **[REGLAS I-10]** Al renombrar un símbolo exportado (función/clase/variable),
  actualizar **todas** sus referencias (búsqueda previa) y documentar el
  cambio.

---

## 13. Checklist de conformidad (correr SIEMPRE antes de terminar)

- [ ] Leí AGENTS.md y README.md completos.
- [ ] No violé ninguna regla N-*, A-*, D-*, C-*, U-*, P-*, V-*, G-*, I-*,
      ni las decisiones RD-*.
- [ ] No implementé decisiones RD pendientes (RD-1, RD-2, RD-4) sin tarea aprobada.
- [ ] Si creé estatus nuevos, los documenté en la tabla de estatus (sección 2).
- [ ] No reimplementé nada que ya exista en el catálogo/helpers.
- [ ] La vista no toca modelos/BD; el modelo no tiene lógica de UI.
- [ ] SQL con placeholders; sin interpolación de valores del usuario.
- [ ] Cambios de BD: aditivos, en `schema.sql` y/o `_migrar()`, sin borrar datos.
- [ ] Folios solo vía `siguiente_folio(...)` (o manual solo para facturas).
- [ ] Permisos verificados con `tiene(permisos, modulo, accion)`.
- [ ] Type hints presentes; español en todo identificador y texto visible.
- [ ] `flake8 . --select=E9,F63,F7,F82` sin errores.
- [ ] `pytest` en verde.
- [ ] Diff revisado por un revisor buscando violaciones a este documento.
