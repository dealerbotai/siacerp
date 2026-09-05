# ESQUEMA DE TRABAJO — SIAC ERP (AGENTS.md)
> **Este archivo es la CONSTITUCIÓN del proyecto.** Lo leen obligatoriamente 
> todas las IAs (Buffy, Cursor, Copilot, etc.) al iniciar sesión, y es la 
> referencia única para cualquier programador humano. Si existe conflicto 
> entre este archivo y cualquier otro documento, **este archivo gana**.
> 
> Viaja con el repositorio: aplica en cualquier máquina que lo clone.

---

## 0. Cómo usar este documento (leyenda)
- **`[REGLAS]`** — reglas **obligatorias e innegociables**. Se numeran con prefijo por área (N = nomenclatura, A = arquitectura, D = base de datos, C = componentes, U = UI, P = permisos, V = validación, G = git, I = IA, RD = decisiones de diseño aprobadas por el usuario). Una IA **DEBE** cumplirlas todas y puede citarlas por número.
- **`[CONTEXTO]`** — explicación del *porqué*. No es obligación, es comprensión.
- **`[EJEMPLO]`** — código real o patrón del proyecto que ilustra la regla.
- **`🚫 PROHIBIDO`** — lo que nunca se debe hacer (aunque "funcione").

**Para una IA nueva:** lee completo este archivo + `README.md` + la estructura de `src/` antes de tocar una sola línea. Luego usa la **Checklist de conformidad** (sección 13) antes de dar tu trabajo por terminado.

---

## 1. Identidad del proyecto
**[CONTEXTO]** SIAC ERP (Sistema Integral de Administración y Control) es una aplicación de **escritorio** con arquitectura **Offline-First** para la gestión de una **fábrica/comercializadora de calzado**: órdenes de compra, inventario de insumos, planificación de producción, producto terminado y control de usuarios/permisos. 

El sistema opera 100% de manera local y autónoma. Supabase se utiliza únicamente como un motor remoto de sincronización multi-tenant para replicar cambios entre terminales cuando existe conexión a Internet.

| Aspecto | Valor |
|---|---|
| Interfaz | PySide6 (Qt for Python ≥ 6.5) |
| Base de datos local | SQLite (desarrollo/local) o PostgreSQL 14+ (estación principal/producción) |
| Sincronización Remota | Supabase (PostgreSQL Cloud) multi-tenant (sólo background si hay red) |
| Reportes | PDF (reportlab) y Excel (openpyxl) |
| Contraseñas | bcrypt |
| Idioma del código | **Español** (identificadores, UI, mensajes, BD, docstrings) |
| Licencia | Propietaria — no es open source (© 2026, M. F. Luevano) |

- **[REGLAS N-00]** Todo el código, nombres, mensajes al usuario, docstrings, comentarios y datos precargados se escriben en **español**.
- **[REGLAS N-01]** Está **PROHIBIDO** mezclar inglés y español en identificadores (p. ej. `get_orden` o `OrderModel` son incorrectos; lo correcto es `obtener_orden` / `OrdenModel`). Excepciones históricas documentadas: el componente registrado `complexGrid` y las clases del stack `ComplexGrid` (se conservan por compatibilidad, no son modelo a seguir).

---

## 1.1 Decisiones de diseño aprobadas (RD-*) — hoja de ruta
**[CONTEXTO]** Decisiones tomadas por el usuario; son la **dirección de diseño obligatoria**. Marcan el **estado objetivo**; mientras una decisión esté marcada como pendiente, el código actual sigue siendo la fuente de verdad del comportamiento. **PROHIBIDO** implementar decisiones pendientes "por su cuenta": requieren tarea aprobada y migración.

| ID | Decisión aprobada | Estado |
|---|---|---|
| **RD-1** | **Unificar puntos y tallas** en un solo catálogo: **`tallas_catalogo`**. Son la misma cosa; en calzado se avanza de medio en medio punto. Se configura con generación en serie "de X a Y talla" (**corrida** = rango de tallas). **Sin campo `orden`**: el orden se deriva del valor numérico. Caso particular: la **compra de suela** se maneja por **puntos cerrados** (se capturan solo las tallas que apliquen en la matriz). | ✅ Aplicada (`tallas_catalogo`) |
| **RD-2** | **Módulo Clientes y Pedidos** (próxima versión): pedidos de clientes que pueden **programarse** e integrarse en una **programación semanal**; la programación semanal alimentará las **órdenes de producción**. Alcance aún por definir con el cliente. Traerá sus propios estatus. | 🚧 Próximamente |
| **RD-3** | **Diseñador e impresor de etiquetas**: herramienta existente en otra terminal de trabajo (fuera de este repositorio por ahora). | 🔧 Externo |
| **RD-4** | **Git — Flujo de trabajo aprobado (fork workflow)**: `origin` = `dealerbotai/siacerp` (nuestro fork). `upstream` = `gorettiboots-commits/siacerp` (repo original). `productivo1` = rama de desarrollo activo. `main` = versión estable/producción. Flujo: `sincronizar.bat` (fetch upstream + merge → productivo1) → trabajar → `publicar.bat` (push a origin) → `release.bat` (merge productivo1 → main → tag → push origin → opcional PR a upstream). Scripts en raíz del proyecto. | ✅ Aplicada |
| **RD-5** | **Arquitectura de Motor BD y Sync**: **SQLite/PostgreSQL** como motor de lectura/escritura local offline. **Supabase** actúa exclusivamente como middleware de sincronización en segundo plano entre terminales multi-tenant. | 🎯 Implementación Offline-First Sync |
| **RD-6** | **Pruebas**: todo control/componente approved desde el Sandbox **DEBE** incluir su prueba `pytest` antes de registrarse en el catálogo. | ✅ Vigente (regla C-07) |
| **RD-7** | **Archivos de raíz** (`sitio web/`, `video.mp4`, `default.jpg`, `logo.png`) son **parte del proyecto** y se documentan (sección 3.1). `opencode.json` contiene **credenciales** y NO se sube a git. | ✅ Documentado |
| **RD-8** | **Auto-actualizador de aplicativo**: El sistema consulta de manera asíncrona un manifiesto remoto (`version.json`). Si detecta una versión superior a `__version__` y hay red, pregunta al usuario mediante un modal si desea actualizar automáticamente. | ✅ Implementada (reglas D-21 a D-25) |
| **RD-9** | **Identidad global por registro (columna `uuid`)**: dos terminales de la MISMA empresa pueden generar el mismo `id` INTEGER offline y pisarse en Supabase. Solución aditiva: columna `uuid` (uuid4) en cada tabla sincronizable; el `id` INTEGER local se conserva como clave interna y el `uuid` es la identidad estable de merge entre terminales. Implementación completa en repo: fase 1 local (`_migrar_uuids` + backfill + garantía en `sync_hooks` + upsert local por uuid); fase 2 de subida vía RPC `subir_registro_sync` (scripts remotos `mobile/supabase/005_...` y `006_...`: columna + índice único `(empresa_id, uuid)` + default `gen_random_uuid()`, merge por uuid conservando el id remoto, adopción de legados sin uuid, regla de convergencia por "huella" conmutable, y colisiones reales de id reubicadas en **espacio negativo** que nunca choca con secuencias/triggers/móvil). El móvil ya envía `uuid` en sus inserts. **Activación:** aplicar 005 y 006 en Supabase y luego encender `[sync] subir_por_uuid=1` en `config.ini` (el camino REST previo queda como respaldo). | ✅ Implementada (activar tras desplegar 005+006) |

---

## 2. Glosario de dominio (léelo antes de tocar datos)
**[CONTEXTO]** Este glosario elimina la ambigüedad más común del proyecto. Una IA que confunda estos términos producirá resultados incorrectos.

| Término | Significado en SIAC | Dónde vive |
|---|---|---|
| **Talla / Punto** | **Son la misma cosa**: catálogo único **`tallas_catalogo`** (RD-1, aplicado) con los valores históricos unificados (`00`–`13` y `22`–`31`), **sin campo `orden`**. Caso particular: suela por **tallas/puntos cerrados**. | `tallas_catalogo` |
| **Corrida** | **Rango de tallas** (de X a Y, en pasos de medio punto) usado en los procesos: p. ej. "corrida del punto 00 al 13" en un lote de compra. | concepto de proceso (no es tabla) |
| **Tenant / Sucursal** | Identificador de la empresa o estación de trabajo (`tenant_id`). Aísla los datos en Supabase. | Columna `tenant_id` (UUID) |
| **UUID v4 / uuid** | Identificador único global (uuid4) en la columna `uuid` de cada tabla sincronizable (RD-9, aplicado). El `id` INTEGER local se conserva como clave interna; el `uuid` es la identidad estable entre terminales de la misma empresa y la clave de merge en Supabase (evita que dos terminales offline se pisen). | Columna `uuid` de tablas sincronizables |
| **Cola de Sync (Outbox)**| Tabla local donde se registran las transacciones pendientes por enviar a Supabase. | `sync_queue` |
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

### Estatus actuales por catálogo
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

- **[REGLAS N-02]** **Puntos y tallas son la misma cosa** y están **unificados** en el catálogo único `tallas_catalogo` (RD-1). Todo el sistema habla de **tallas** ("corrida" = rango de X a Y). **PROHIBIDO** volver a crear tablas/columnas `punto`/`puntos` o catálogos paralelos de medida.
- **[REGLAS N-02b]** Los **estatus NO forman una lista cerrada única**: varían por catálogo. Reglas obligatorias: español, minúscula, `snake_case`; todo estatus **NUEVO** se documenta en la tabla de estatus de esta sección.

---

## 3. Estructura del repositorio
``` siacerp/
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
    ├── models/                 # Capa de acceso a datos (SQL Local) — {Entidad}Model
    ├── controllers/            # Lógica de negocio — {Modulo}Controller
    ├── services/               # Servicios (sync_service.py, actualizacion_service.py...)
    ├── views/                  # Vistas Qt + diálogos (dialogs.py, sandbox, kanban…)
    ├── components/             # Componentes aprobados (catálogo) + __init__.py
    └── utils/                  # Helpers: export_utils, folios, table_utils, updater_utils...