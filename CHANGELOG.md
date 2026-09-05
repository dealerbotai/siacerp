# Changelog — SIAC ERP

> Registro de cambios notables de cada versión.
> Formato basado en [Keep a Changelog](https://keepachangelog.com/es/1.1.0/).
> El proyecto sigue [CalVersioning](https://calver.org/) con formato `YYYY.M.DD`.

---

## [Unreleased] — 2026-09-05

### Added
- **Capa de acceso a datos agnóstica al motor (SQLite/PostgreSQL):**
  - `src/database/dialectos.py`: dialectos SQLite/PostgreSQL (placeholder, `ahora()`, `auto_incremento()`, booleano, BLOB, introspección y helpers de respaldo: FK, insert-or-ignore, secuencias)
  - `DatabaseManager._adaptar`: convierte placeholders `?` → `%s` automáticamente en PostgreSQL; los modelos existentes no cambian
  - `src/database/base_repositorio.py`: repositorio base con CRUD genérico, filtros multi-tenant y hooks de sync
  - Migrados a `BaseRepositorio`: `TallasModel`, `ColoresModel`, `UnidadesMedidaModel`, `ProveedorModel` e `InsumoModel`
  - `respaldo_bd_utils.py` sin ramas por motor (delega en el dialecto)
- **Identidad global por registro `uuid` (RD-9, fases 1 y 2):**
  - Fase 1 local: migración `_migrar_uuids` (columna + backfill), `sync_hooks` garantizan uuid al encolar, `_upsert_local` resuelve por uuid (colisión de ids entre terminales)
  - Fase 2 remota: RPC `subir_registro_sync` (migración 006) — merge por uuid conservando el id remoto, adopción de filas legadas sin uuid, regla de convergencia por "huella" y reubicación de colisiones en id negativo
  - `SupabaseService`: `llamar_rpc()`, `subir_registro_por_uuid()`, `subir_por_uuid_habilitado()`
  - `SyncService._enviar_registro`: usa el snapshot vivo (uuid garantizado) y cae al REST histórico si el RPC no está desplegado (HTTP 404); se activa con `[sync] subir_por_uuid=1`
  - Migraciones Supabase `005_agregar_uuid_identidad.sql` y `006_subir_por_uuid.sql`
  - App móvil: `generarUuid()` y `uuid` en los inserts de pedidos/programación

### Changed
- **AGENTS.md:** Eliminada la duplicación del documento (dos versiones concatenadas) y documentada la decisión **RD-9** con su glosario

### Fixed
- Migraciones 005/006 tolerantes a tablas no existentes en el proyecto (modelos/variantes/proveedores `_movil`) y al trigger de timestamp sin columna `updated_at` (caso de la migración 004)
- `test_ficha_tecnica_model.py`: reescrito contra la API actual de la ficha técnica (la anterior probaba un diseño eliminado)
- `test_campo_historico.py`: aislado en BD temporal y corregido el orden "más reciente primero" (formato de marca con segundos + guarda monótona); suite completa en verde: **265 pruebas**

---

## [Unreleased] — 2026-08-31

### Added
- **Captura de pedidos desde app móvil:**
  - Selector de clientes con búsqueda por nombre/RFC
  - Captura de líneas con modelo, piel, color
  - Grilla de tallas por línea (pares por talla)
  - Creación de pedido con folio automático en Supabase
  - FAB botón flotante en pantalla de pedidos
- **Impresión de etiquetas desde programación móvil:**
  - Botón «Imprimir» en cada línea de programación
  - Genera etiquetas por cada talla/pares de la línea
  - Envía solicitud a `impresiones_etiqueta` en Supabase
- **Sincronización automática escritorio → Supabase:**
  - Sync automática al iniciar (después del login)
  - Sync periódica cada 2 minutos
  - Sync inmediata después de cada cambio en models
  - Verificación de red antes de cada sync
  - Tablas de detalle de pedido sincronizadas
- **Migraciones Supabase numeradas (001-004):**
  - 001: Tabla `impresiones_etiqueta` con RLS
  - 002: Actualización de nombre de empresa
  - 003: Vista de estatus de producción
  - 004: Columna `updated_at` en `programacion_linea_tallas_movil`
- **Script de sincronización inicial** (`sincronizar_datos_movil.py`):
  - Sincroniza clientes, pedidos, detalles, programación y tallas
  - Usa `service_role_key` para bypass RLS
- **Bug fix auth.ts:** Corregido `.catch()` en Supabase `insert()` (PostgrestFilterBuilder no es Promise)
- **Safe area en app móvil:** Respeto de insets.top para evitar overlap con barra de estado
- **Tab «Pedidos» renombrado:** De «Clientes» a «Pedidos» en el tab bar
- **Protección de eliminación en programación:** Líneas en producción no se pueden eliminar (móvil + escritorio)

### Changed
- **App móvil recompilada** con todas las mejoras de UI y funcionalidad
- **Documentación README actualizada** con nuevas funcionalidades y métricas
- **Versión del instalador** actualizada a 1.2.0

### Fixed
- **Login móvil crasheaba:** TypeError por `.catch()` en `PostgrestFilterBuilder`
- **Empresas mostraba «SIAC ERP»:** Nombre actualizado a «EskinBoots» en Supabase
- **Pedidos sin líneas:** Tablas de detalle no sincronizadas a Supabase
- **Programación sin datos:** Tablas de programación no incluidas en sync automática

---

## [Unreleased] — 2026-08-30

### Added
- **Módulo Clientes, Pedidos y Programación en app móvil:**
  - Pantalla de listado de clientes con búsqueda
  - Pantalla de listado de pedidos con filtros por estatus
  - Pantalla de detalle de pedido con matriz de tallas
  - Pantalla de programación semanal con selector de semana
  - Solo visible para rol `admin` (no super_admin)
  - Tab «Clientes» y tab «Prog.» en el tab bar
- **Selector de empresa para super_admin en app móvil:**
  - Pantalla `PantallaCambiarEmpresa` para cambiar contexto
  - Barra de empresa en la parte superior de la app
  - Botón «Ver datos» en cada empresa del panel Admin
  - Botón «Quitar filtro» para volver a vista global
  - Todas las pantallas se recargan al cambiar empresa
  - Sistema de listeners `registrarCambioEmpresa()`
- **Panel de administración móvil mejorado:**
  - Botón «Activar/Desactivar» por empresa con confirmación
  - Al desactivar: bloquea login en desktop y móvil
  - Botón «Ver datos» para cambiar contexto
- **Protocolo de validación RLS en AGENTS.md (sección 6.4):**
  - Reglas D-11 a D-17 para validación de Row Level Security
  - Template SQL completo para tablas multi-tenant
  - Errores comunes a evitar
  - Checklist de conformidad actualizado (12 items nuevos)
- **Template de servicios TypeScript multi-tenant (sección 6.5):**
  - Reglas D-18 a D-20 para servicios del móvil
  - Template completo con 5 funciones (listar, buscar, obtener, crear, actualizar)
  - Patrón `obtenerEmpresaId()` para super_admin context
- **Migración SQL `migrar_rls_super_admin.sql`:**
  - Función `es_super_admin()` (SECURITY DEFINER)
  - Función `empresa_esta_activa()` (SECURITY DEFINER)
  - Función `verificar_login_movil()` (SECURITY DEFINER)
  - 20+ políticas de bypass RLS para super_admin
  - Políticas de empresa activa en todas las tablas
  - 5 políticas DELETE faltantes agregadas
  - `empresa_id DROP NOT NULL` para perfiles de super_admin
- **Verificación de empresa activa en login:**
  - App móvil: verifica empresa antes de permitir login (excepto super_admin)
  - Escritorio: verifica empresa vía Supabase después de login local
  - Mensaje de error «Empresa desactivada» cuando aplica
- **Rol super_admin:** Usuario con acceso total a todas las empresas (funcionalidad interna)
  - Función SQL `es_super_admin()` (SECURITY DEFINER) para evitar recursión en RLS
  - Policies RLS actualizadas: super_admin ve todos los datos de todas las empresas
- **Dashboard de super_admin en escritorio:**
  - Panel de administración interna (solo visible con rol super_admin)
  - KPIs globales: total empresas, usuarios, insumos, OCs, OPs
  - Tabla de empresas con nombre, RFC, estado y métricas
  - Tabla de usuarios con username, nombre, rol, estado
  - Selección de empresa para ver sus usuarios
  - **Botón activar/desactivar** empresas con confirmación
  - Carga lazy (se instancia solo al primer clic)
  - Arquitectura MVC completa: model, controller, view
- **App móvil completa (React Native + Supabase):**
  - Pantalla de login con autenticación Supabase Auth
  - Pantalla de Inventario con búsqueda y alertas de stock bajo
  - Pantalla de Detalle de Insumo con indicador visual
  - Pantalla de Órdenes de Compra con filtros por estatus
  - Pantalla de Detalle de OC con partidas y costos
  - Pantalla de Producción con filtros y badge de prioridad
  - Pantalla de Detalle OP con **Kanban vertical** de estaciones
  - Cambio de estatus: Iniciar, Avanzar, Editar pares procesados
  - Reporte de incidencias desde el móvil
  - React Navigation (Stack + Tabs) con 4 módulos
  - Navegación: Inventario, Órdenes, Producción, Etiquetas
- **Arquitectura multi-tenant completa:**
  - `empresa_id` en 15 tablas de la BD local del escritorio
  - `empresa_id` en 10 tablas de Supabase
  - RLS (Row Level Security) por empresa en todas las tablas
  - Aislamiento total: cada empresa solo ve sus datos
  - 3 empresas de prueba creadas y verificadas
- **Servicio de conexión a Supabase para escritorio** (`supabase_service.py`):
  - Login con Supabase Auth
  - Verificación de licencia por empresa
  - CRUD con service_role key (bypass RLS)
  - Listado de usuarios por empresa
- **Servicio de sincronización bidireccional** (`sync_service.py`):
  - Sync local → Supabase (sube datos modificados)
  - Sync Supabase → local (baja datos de otras terminales)
  - Intervalo configurable (default: 5 minutos)
  - Funciona en background con threading
  - Upsert inteligente (inserta o actualiza)
- **Migración `empresa_id` en BD local** (`_migrar_empresa_id`):
  - 15 tablas migradas automáticamente al arrancar
  - Compatible SQLite y PostgreSQL
  - Lee `empresa_id` de `config.ini [supabase]`
- **Script de registro de empresas** (`registrar_empresa.py`):
  - Crea empresa, usuario Auth y perfil en un solo comando
  - Usa service_role key (no necesita login previo)
  - Maneja duplicados automáticamente
  - Muestra `empresa_id` para configurar nueva terminal
- **Esquema Supabase multi-tenant** (`schema_multi_tenant.sql`):
  - Tabla `empresas` con RLS
  - `empresa_id` en todas las tablas de datos
  - Índices para rendimiento
  - Policies RLS por empresa
- **Migraciones Supabase** (`migrar_multi_tenant_paso1.sql`, `paso2.sql`):
  - Paso 1: Crear tabla empresas + agregar empresa_id
  - Paso 2: Actualizar políticas RLS multi-tenant
- **Pantalla DetalleOC** (`PantallaDetalleOC.tsx`):
  - Detalle de orden de compra con partidas y costos
- **Tipos TypeScript actualizados** (`tipos.ts`):
  - Interfaces para todas las entidades multi-tenant
- **Documentación multi-tenant en README:**
  - Sección dedicada con diagramas de arquitectura
  - Guia de registro y configuración de terminales
  - Tabla de tablas con empresa_id
  - Credenciales de prueba

### Changed
- **AGENTS.md:** Agregadas reglas D-11 a D-20 (RLS + servicios TypeScript multi-tenant)
- **Checklist de conformidad:** 12 items nuevos de verificación RLS y TypeScript
- **App móvil auth.ts:** Verifica empresa activa antes de login, soporte `empresaContexto`
- **App móvil App.tsx:** Barra de empresa para super_admin, recarga automática al cambiar contexto
- **Escritorio main_window.py:** Verifica empresa activa vía Supabase después de login local
- **Dashboard del sistema:** Pantalla de resumen con 6 tarjetas KPI clicables
  - OC pendientes, compras del mes, producción en curso, insumos stock bajo, pares en PT, movimientos del día
  - Gráfica de barras de compras por mes (QPainter)
- **Ficha técnica rediseñada:** Layout split con paneles izquierdo/derecho
  - Panel izquierdo: datos generales, comentarios/firmas, fotos
  - Panel derecho: características + materiales con costos
- **Costos BOM en ficha técnica:** Costo unitario por insumo
- **Impresión de ficha técnica profesional:** Formato "Hoja de especificación de diseño"
- **Carga de HTML grande en preview_impresion:** Archivos temporales >1.5MB
- **App móvil - Tab bar:** Respeta área segura de Android (`useSafeAreaInsets`)
- **config.ini:** Agregado `service_role_key` y `empresa_id`
- **.gitignore:** Agregado `mobile/.env`, `mobile/node_modules/`, `mobile/.expo/`
- **Tabla de sincronización README:** Actualizada con multi-tenant

### Fixed
- Impresión de ficha técnica mostraba página en blanco con HTML grande
- `loadFinished` tardío podía disparar PDF sin datos
- App móvil: tab bar se mostraba detrás de botones de Android
- Script registrar_empresa.py: manejo de respuestas vacías de Supabase

---

## [v1.0.0] — 2026-08-20

> **Primer release oficial del sistema.**

### Added
- **Onboarding wizard:** Asistente de primera configuración para nuevos usuarios
- **Empaquetado PyInstaller:** Generación de ejecutable `onedir` con datos en `%APPDATA%\SIAC`
- **GridHibrido:** Componente wrapper de ComplexGrid con toolbar de 2 filas (módulo + grid) y barra de estado
- **Plantilla compartida de impresión** (`print_template.py`): Bloques HTML reutilizables (cabecera, ondas, pie, wrap_hoja) con tema mint/salvia
- **Refactorización de impresión:** Todos los reportes usan la plantilla compartida

### Changed
- **Toolbar superior:** Módulos al lado izquierdo, Sandbox/Salir al lado derecho
- **ComplexGrid → GridHibrido:** Se reemplaza ComplexGrid directo por el wrapper con toolbar unificada

---

## [Histórico] — 2026-08-04 al 2026-08-19

### 2026-08-19

#### Changed
- Refactoriza impresión con plantilla compartida `print_template` (WYSIWYG)
- Mejora dialogos de stock y movimientos

### 2026-08-18

#### Fixed
- Alineación de toolbar: módulos a la izquierda, Sandbox/Salir a la derecha

### 2026-08-17

#### Added
- **Vista de Logs del Sistema:** Diálogo con filtros, detalle, limpieza y exportación (solo admin en Ayuda)
- **Buscador global (Ctrl+K):** Búsqueda de registros en cualquier módulo con navegación directa
- **Atajos de teclado:** Ctrl+1 a Ctrl+6 para módulos, Ctrl+K buscador, Ctrl+, configuración
- **Prototipo GridHibridoDemo en Sandbox:** Prueba del grid híbrido antes de aprobar
- **Toolbar con colores por módulo:** Ícono arriba/abajo estilo prototipo
- **Estilo oscuro del toolbar:** Gradiente `#1e293b`, botones indigo, status bar oscura
- **Manual de Usuario SIAC ERP en PDF (v1.0):** Script generador con reportlab
- **Cola de impresión de etiquetas:** Gestión de solicitudes desde app móvil (vía Supabase)

#### Changed
- Sincronización productivo1: variantes, toolbar, impresión, mobile, docs

### 2026-08-14

#### Added
- **Rediseño de impresión de etiquetas:** Modos Flejes (Cajas) y Partidas con matriz de tallas
- Botones extra al ComplexGrid
- Exportación de programación con formato de reporte

#### Fixed
- Imports en Configuración
- Catálogo de componentes del Sandbox

### 2026-08-13

#### Added
- **Impresora virtual SIAC:** Opción de simulación en pantalla desde Configuración
- **Notificaciones flotantes (toasts):** Tarjetas animadas con tipos info/success/warning/error
- **Toolbar superior de navegación:** Reemplaza sidebar colapsable
- **Botón "Programar" por fila** en programación de pedidos
- **Historial de campos:** Campo de texto con histórico de capturas y autocompletado
- **Date Picker:** Selector de fecha con calendario emergente
- **Etiquetas y preview** de impresión
- **Empaquetado PyInstaller (onedir):** Datos en `%APPDATA%\SIAC`

#### Changed
- Aplica tema clásico Windows Forms en todo el sistema
- Ajusta tamaños de ventana y matrices de tallas para mostrar contenido completo
- Captura de tallas integrada en "Agregar Línea" de pedidos

### 2026-08-12

#### Added
- **Migración RD-1:** Unifica puntos y tallas en catálogo único `tallas_catalogo`
- **Precio por talla** en órdenes de compra
- Puntos 15-21 agregados al catálogo
- Selectores de proveedor por razón social/nombre comercial
- Filas más altas en detalle de OC
- **Preview de impresión como componente aprobado**
- **AGENTS.md:** Documenta reglas del proyecto (RD-1..RD-7) y protege opencode.json
- **CI/CD:** GitHub Actions escucha `productivo1` y `main`

### 2026-08-10

#### Added
- **Programación semanal** con etiquetas, programar pedido y navegación
- **Workflow CI** (`siaci.yml`) con flake8 y pytest
- **pytest.ini** con pythonpath para encontrar el paquete `src`
- **Pruebas unitarias** de NotificacionesFlotantes

#### Fixed
- Segfault de PySide6 al cerrar pytest (teardown Qt de sesión)
- Segfault en notificaciones: timer propio por tarjeta, detener animaciones antes de borrar
- `E999` en `complex_grid` (`_reporte_html`)
- Limpieza defensiva: detener timers/animaciones al cerrar o destruir

#### Removed
- Workflow `python-app.yml` obsoleto (duplicado, sin deps Qt)

### 2026-08-09

#### Added
- **Catálogo de componentes propios:** `src/components/__init__.py` con `registrar_componente()`, `listar_componentes()`, `obtener_componente()`
- **Componente aprobado: MatrizTallasDialog** — Matriz de tallas por bloques con navegación Enter/Tab
- **Componente aprobado: ComplexGrid** — Tabla de datos con búsqueda, filtros, agrupación, vistas y exportación
- **Componente aprobado: OdooListView** — Vista de listado con alternador tabla/lista/iconos
- **Sandbox:** Área de pruebas de controles (solo admin)
- **Iconos SVG embebidos** (`src/utils/icons.py`)
- **Estilos QSS globales** (`src/utils/styles.qss`)
- **Notificaciones flotantes** (prototipo en Sandbox)
- **Importador de directorio** con colores en consola

### 2026-08-06

#### Added
- **Módulo Clientes y Pedidos:** Catálogo de clientes con pedidos de cliente
- Captura por tallas en pedidos
- Importación masiva de proveedores e insumos desde `DIRECTORIO.xlsx`
- Logo jpeg en la interfaz

### 2026-08-05

#### Added
- **Facturas en órdenes de compra:** Folio manual (`FAC-...`), tipo `factura`, color verde claro `#daf2d0`
- **Nombre comercial de proveedores** en catálogo
- **Tablas estilo Excel:** Ajuste de columnas por arrastre o doble clic
- **Autenticación con bcrypt** (`src/utils/security.py`)
- **Video splash de bienvenida** en MainWindow
- **Folios de solo lectura** en campos generados
- **Imágenes en insumos y modelos**

---

## Decisiones de diseño (RD) aplicadas

| ID | Decisión | Fecha de aplicación |
|---|---|---|
| **RD-1** | Unificar puntos y tallas en `tallas_catalogo` | 2026-08-12 |
| **RD-4** | Flujo git: `productivo1` → `main`, CI escucha ambas | 2026-08-12 |
| **RD-5** | Motor BD: PostgreSQL producción, SQLite desarrollo | Vigente |
| **RD-6** | Todo componente aprobado debe incluir prueba `pytest` | Vigente |
| **RD-7** | Archivos de raíz documentados; `opencode.json` protegido | 2026-08-12 |
| **RD-9** | Identidad global por registro: columna `uuid` + RPC `subir_registro_sync` | 2026-09-05 |

---

## Componentes aprobados (fecha de registro)

| Componente | Fecha | Descripción |
|---|---|---|
| `odoo_list` | 2026-08-09 | Vista de listado con alternador tabla/lista/iconos |
| `matriz_tallas` | 2026-08-09 | Matriz de tallas por bloques con navegación Enter/Tab |
| `complexGrid` | 2026-08-09 | Tabla de datos con búsqueda, filtros y exportación |
| `preview_impresion` | 2026-08-12 | Vista previa WYSIWYG con zoom e impresión a PDF |
| `grid_hibrido` | 2026-08-17 | Wrapper de ComplexGrid con toolbar de 2 filas |
| `date_picker` | 2026-08-13 | Selector de fecha con calendario emergente |
| `campo_historico` | 2026-08-13 | Campo de texto con histórico de capturas |
| `notificacion_flotante` | 2026-08-09 | Toasts animados con tipos info/success/warning/error |
| `label_canvas` | 2026-08-14 | Lienzo interactivo de diseño de etiqueta |
| `editor_etiqueta` | 2026-08-14 | Creador/editor de etiquetas con guardado en BD |
| `matriz_preview` | 2026-08-14 | Widget flotante de vista previa de matriz al hover |

---

## Estadísticas del proyecto

| Métrica | Valor |
|---|---|
| **Commits totales** | 93+ |
| **Primera actividad** | 2026-08-04 |
| **Última actividad** | 2026-09-05 |
| **Contribuyentes** | 3 |
| **Pull requests mergeados** | 10+ |
| **Componentes aprobados** | 11 |
| **Archivos de código fuente** | 80+ |
| **Pruebas pytest** | 265 |
| **App móvil (pantallas)** | 14 |
| **Servicios móviles** | 7 |
| **Empresas multi-tenant** | 3 |
| **Tablas con empresa_id** | 25 |
| **Roles de usuario** | 3 (admin, operador, super_admin) |
| **Reglas AGENTS.md** | 30+ (D-01 a D-20, N-*, A-*, etc.) |

---

<div align="center">

**SIAC ERP** — Changelog

*Mantenido por el equipo de desarrollo*

</div>
