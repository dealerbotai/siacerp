"""Exportación e importación de conjuntos de datos de la base de datos.

Permite respaldos parciales por "conjuntos" (grupos lógicos de tablas) y su
restauración posterior. El archivo generado es JSON portable entre motores
(SQLite y PostgreSQL, decisión RD-5) con las imágenes (BLOB) codificadas en
base64.

Estructura del archivo:
    {
      "aplicacion": "SIAC ERP",
      "version_archivo": 1,
      "generado": "2026-08-24T12:00:00",
      "motor": "sqlite",
      "conjuntos": {"clientes": ["clientes", "pedidos_cliente", ...]},
      "datos": {"clientes": {"columnas": [...], "filas": [[...], ...]}}
    }

Modos de importación:
    - reemplazar=True: vacía las tablas de los conjuntos seleccionados y
      carga lo del archivo (restauración).
    - reemplazar=False: agrega solo los registros que falten (por clave
      primaria o única), sin tocar los existentes.

Nombres de tabla y columna se validan contra el esquema real antes de usar
cualquier identificador en SQL (regla D-04).
"""
import base64
import json
import re
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from src.database.db_manager import DatabaseManager

_VERSION_ARCHIVO = 1
_APLICACION = "SIAC ERP"
_TAG_BLOB = "__blob__"
_EXPRESION_IDENTIFICADOR = re.compile(r"^[a-z_][a-z0-9_]*$")

# Conjuntos lógicos: tablas en orden de dependencia (padres primero).
CONJUNTOS = [
    {"clave": "catalogos", "nombre": "Catálogos",
     "tablas": ["unidades_medida", "estaciones_produccion",
                "tallas_catalogo", "colores_catalogo"]},
    {"clave": "proveedores", "nombre": "Proveedores",
     "tablas": ["proveedores"]},
    {"clave": "insumos", "nombre": "Insumos y Variantes",
     "tablas": ["insumos", "variantes", "proveedor_insumos"]},
    {"clave": "modelos", "nombre": "Modelos y Fichas Técnicas",
     "tablas": ["modelos", "lista_materiales", "fichas_tecnicas",
                "ficha_tecnica_fotos"]},
    {"clave": "clientes", "nombre": "Clientes y Pedidos",
     "tablas": ["clientes", "pedidos_cliente", "detalle_pedido_cliente",
                "detalle_pedido_cliente_puntos"]},
    {"clave": "ordenes_compra", "nombre": "Órdenes de Compra",
     "tablas": ["ordenes_compra", "detalle_orden_compra",
                "detalle_orden_compra_puntos"]},
    {"clave": "produccion", "nombre": "Producción",
     "tablas": ["ordenes_produccion", "matriz_tallas_op",
                "seguimiento_produccion", "incidencias_produccion",
                "inventario_pt"]},
    {"clave": "programacion", "nombre": "Programación Semanal",
     "tablas": ["programacion_semana", "programacion_lineas",
                "programacion_linea_tallas"]},
    {"clave": "inventario_movimientos", "nombre": "Movimientos de Inventario",
     "tablas": ["movimiento_inventario", "movimientos_inventario",
                "detalle_movimiento_inventario"]},
    {"clave": "usuarios", "nombre": "Usuarios y Permisos",
     "tablas": ["usuarios", "permisos", "usuario_permisos"]},
    {"clave": "sistema", "nombre": "Sistema y Configuración",
     "tablas": ["configuracion_empresa", "configuracion_sistema",
                "etiqueta_config", "historico_campos",
                "impresiones_historico", "logs_sistema"]},
]

_TABLAS_VALIDAS = {t for c in CONJUNTOS for t in c["tablas"]}
_ORDEN_CONJUNTOS = [c["clave"] for c in CONJUNTOS]


def listar_conjuntos() -> list[dict]:
    """Devuelve los conjuntos con la cantidad de filas actuales por conjunto."""
    db = DatabaseManager()
    resultado = []
    for c in CONJUNTOS:
        filas = 0
        for tabla in c["tablas"]:
            fila = db.fetch_one(f"SELECT COUNT(*) AS n FROM {tabla}")
            filas += int(fila["n"] if fila else 0)
        resultado.append({"clave": c["clave"], "nombre": c["nombre"],
                          "tablas": c["tablas"], "filas": filas})
    return resultado


# ------------------------------------------------------------- conversión
def _valor_a_json(valor):
    if isinstance(valor, (bytes, bytearray, memoryview)):
        return {_TAG_BLOB: base64.b64encode(bytes(valor)).decode("ascii")}
    if isinstance(valor, datetime):
        return valor.isoformat(sep=" ")
    if isinstance(valor, date):
        return valor.isoformat()
    if isinstance(valor, Decimal):
        return float(valor)
    return valor


def _json_a_valor(valor):
    if isinstance(valor, dict) and _TAG_BLOB in valor:
        return base64.b64decode(valor[_TAG_BLOB])
    return valor


# ---------------------------------------------------------------- export
def _columnas_tabla(db: DatabaseManager, tabla: str) -> list[str]:
    """Columnas de la tabla en orden de definición (vía dialecto activo)."""
    conn = db.connect()
    cursor = conn.cursor()
    return db.dialecto.obtener_columnas(cursor, tabla)


def exportar_conjuntos(claves: list[str], ruta: str) -> dict:
    """Exporta los conjuntos indicados a un archivo JSON.

    Regresa un resumen {"archivo", "tablas": {tabla: filas}, "filas": total}.
    """
    seleccion = set(claves)
    conjuntos = [c for c in CONJUNTOS if c["clave"] in seleccion]
    if not conjuntos:
        raise ValueError("Seleccione al menos un conjunto para exportar.")
    db = DatabaseManager()
    datos: dict = {}
    conteo: dict[str, int] = {}
    for c in conjuntos:
        for tabla in c["tablas"]:
            filas = db.fetch_all(f"SELECT * FROM {tabla}")
            columnas = list(filas[0].keys()) if filas else _columnas_tabla(
                db, tabla)
            datos[tabla] = {
                "columnas": columnas,
                "filas": [[_valor_a_json(f[col]) for col in columnas]
                          for f in filas],
            }
            conteo[tabla] = len(filas)
    documento = {
        "aplicacion": _APLICACION,
        "version_archivo": _VERSION_ARCHIVO,
        "generado": datetime.now().isoformat(timespec="seconds"),
        "motor": db.engine,
        "conjuntos": {c["clave"]: c["tablas"] for c in conjuntos},
        "datos": datos,
    }
    Path(ruta).write_text(
        json.dumps(documento, ensure_ascii=False), encoding="utf-8")
    return {"archivo": str(ruta), "tablas": conteo,
            "filas": sum(conteo.values())}


# ------------------------------------------------------------- importación
def _leer_documento(ruta: str) -> dict:
    try:
        doc = json.loads(Path(ruta).read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ValueError(f"El archivo no es un JSON válido: {e}") from e
    if not isinstance(doc, dict) or doc.get("aplicacion") != _APLICACION \
            or not isinstance(doc.get("datos"), dict):
        raise ValueError(
            "El archivo no es un respaldo de datos válido de SIAC ERP.")
    return doc


def inspeccionar_archivo(ruta: str) -> dict:
    """Lee un archivo de respaldo y describe su contenido sin importar nada."""
    doc = _leer_documento(ruta)
    conjuntos = {}
    for clave, tablas in (doc.get("conjuntos") or {}).items():
        filas = sum(len((doc["datos"].get(t) or {}).get("filas", []))
                    for t in tablas)
        conjuntos[clave] = {"tablas": tablas, "filas": filas}
    return {"archivo": str(ruta), "generado": doc.get("generado", ""),
            "motor": doc.get("motor", ""), "conjuntos": conjuntos}


def _columnas_seguras(db: DatabaseManager, tabla: str,
                      columnas_archivo: list) -> list[str]:
    """Filtra las columnas del archivo: existentes en la tabla y con nombre
    de identificador válido (protección contra contenido no confiable)."""
    validas = set(_columnas_tabla(db, tabla))
    seguras = []
    for col in columnas_archivo:
        if (isinstance(col, str) and col in validas
                and _EXPRESION_IDENTIFICADOR.match(col)):
            seguras.append(col)
    return seguras


def _desactivar_fk(cursor, dialecto) -> None:
    """Desactiva las FK de la sesión (delegado al dialecto)."""
    try:
        dialecto.desactivar_fk(cursor)
    except Exception as e:
        print(f"Respaldo: no se pudieron desactivar las FK ({e})")


def _restaurar_fk(cursor, dialecto) -> None:
    """Reactiva las FK de la sesión (delegado al dialecto)."""
    try:
        dialecto.restaurar_fk(cursor)
    except Exception:
        pass


def importar_conjuntos(ruta: str, claves: list[str],
                       reemplazar: bool) -> dict:
    """Importa los conjuntos indicados desde un archivo de respaldo.

    Con *reemplazar* vacía primero las tablas de los conjuntos; sin él,
    agrega solo los registros faltantes. Regresa un resumen con contadores
    y la lista de errores por tabla.
    """
    doc = _leer_documento(ruta)
    datos = doc["datos"]
    conjuntos_archivo = doc.get("conjuntos") or {}
    seleccion = set(claves)
    ordenadas = [c for c in _ORDEN_CONJUNTOS if c in seleccion
                 and c in conjuntos_archivo]
    ordenadas += [c for c in sorted(conjuntos_archivo)
                  if c in seleccion and c not in _ORDEN_CONJUNTOS]
    if not ordenadas:
        raise ValueError(
            "El archivo no contiene ninguno de los conjuntos seleccionados.")

    resumen: dict = {"importadas": 0, "omitidas": 0, "fk_violaciones": 0,
                     "errores": [], "tablas": {}}

    def _error(mensaje: str) -> None:
        if len(resumen["errores"]) < 10:
            resumen["errores"].append(mensaje)

    # Tablas en orden de dependencia; las que no estén en el esquema real
    # se reportan y se omiten (lista fija válida, regla D-04).
    tablas: list[str] = []
    for clave in ordenadas:
        for tabla in conjuntos_archivo[clave]:
            if not isinstance(tabla, str) or tabla in tablas:
                continue
            if tabla in _TABLAS_VALIDAS:
                tablas.append(tabla)
            else:
                _error(f"{tabla}: tabla no reconocida en el esquema, "
                       "se omitió.")

    db = DatabaseManager()
    conn = db.connect()
    cursor = conn.cursor()

    try:
        conn.commit()  # cierra cualquier transacción pendiente (PRAGMA)
        _desactivar_fk(cursor, db.dialecto)

        if reemplazar:
            for tabla in reversed(tablas):
                try:
                    cursor.execute(f"DELETE FROM {tabla}")
                except Exception as e:
                    _error(f"{tabla}: no se pudo vaciar ({e})")

        for tabla in tablas:
            info = datos.get(tabla) or {}
            columnas = _columnas_seguras(
                db, tabla, info.get("columnas") or [])
            filas = info.get("filas") or []
            if not columnas:
                if filas:
                    _error(f"{tabla}: columnas no reconocidas, se omitió.")
                continue
            lista_cols = ", ".join(columnas)
            sql = db.dialecto.sql_insertar_o_ignorar(
                tabla, columnas, con_conflicto_id=not reemplazar)
            insertadas = omitidas = 0
            for fila in filas:
                valores = [_json_a_valor(v) for v in fila[:len(columnas)]]
                try:
                    cursor.execute(sql, valores)
                    if (cursor.rowcount or 0) > 0:
                        insertadas += 1
                    else:
                        omitidas += 1
                except Exception as e:
                    omitidas += 1
                    _error(f"{tabla}: {e}")
            resumen["tablas"][tabla] = {"insertadas": insertadas,
                                        "omitidas": omitidas}
            resumen["importadas"] += insertadas
            resumen["omitidas"] += omitidas

        if db.engine == "postgresql":
            for tabla in tablas:
                try:
                    db.dialecto.reajustar_secuencia(cursor, tabla)
                except Exception:
                    pass  # tablas sin secuencia (catálogos fijos, etc.)

        if db.engine == "sqlite":
            try:
                resumen["fk_violaciones"] = \
                    db.dialecto.contar_violaciones_fk(cursor)
            except Exception:
                pass

        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        _restaurar_fk(cursor, db.dialecto)
    return resumen
