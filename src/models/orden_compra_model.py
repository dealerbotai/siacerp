from typing import Optional
from src.database.base_repositorio import BaseRepositorio
from src.database.db_manager import DatabaseManager
from src.utils.empresa_context import donde_empresa, parametros_empresa
from src.utils.sync_hooks import sync_insert, sync_update, sync_delete


def _subtotal_detalle_oc(d: dict) -> float:
    """Subtotal del renglón: Σ(pares × precio) por talla si hay precios por talla;
    si no, cantidad × precio_unitario."""
    con_precio = [t for t in (d.get("tallas") or [])
                  if float(t.get("precio", 0) or 0) > 0]
    if con_precio:
        return sum(float(t.get("pares", 0) or 0) * float(t.get("precio", 0) or 0)
                   for t in con_precio)
    return float(d.get("cantidad", 0) or 0) * float(d.get("precio_unitario", 0) or 0)


class ProveedorModel(BaseRepositorio):
    """Proveedores: CRUD heredado + búsqueda explícita con LIKE multi-tenant."""

    tabla = "proveedores"
    sincronizable = True            # en TABLAS_SUBIR del SyncService
    con_soft_delete = True
    usa_empresa = True
    orden_por_defecto = "nombre"

    def crear(self, rfc: str, nombre: str, telefono: str = "", email: str = "",
              direccion: str = "", nombre_comercial: str = "") -> int:
        return super().crear({
            "rfc": rfc, "nombre": nombre, "nombre_comercial": nombre_comercial,
            "telefono": telefono, "email": email, "direccion": direccion,
        })

    def actualizar(self, proveedor_id: int, rfc: str, nombre: str, telefono: str,
                   email: str, direccion: str, nombre_comercial: str = "") -> None:
        super().actualizar(proveedor_id, {
            "rfc": rfc, "nombre": nombre, "nombre_comercial": nombre_comercial,
            "telefono": telefono, "email": email, "direccion": direccion,
        })

    def buscar(self, termino: str) -> list[dict]:
        q = "%" + termino + "%"
        where_emp = donde_empresa()
        params: list = [q, q, q] + parametros_empresa()
        return self.db.fetch_all(
            "SELECT * FROM proveedores WHERE activo=1 AND "
            "(rfc LIKE ? OR nombre LIKE ? OR nombre_comercial LIKE ?)"
            + where_emp + " ORDER BY nombre",
            tuple(params),
        )


class ProveedorInsumosModel:
    def __init__(self) -> None:
        self.db = DatabaseManager()

    def listar(self, proveedor_id: int) -> list[dict]:
        return self.db.fetch_all(
            """SELECT pi.*, i.nombre as insumo_nombre, i.codigo as insumo_codigo
               FROM proveedor_insumos pi
               JOIN insumos i ON i.id = pi.insumo_id
               WHERE pi.proveedor_id = ? AND pi.activo = 1
               ORDER BY pi.created_at DESC""",
            (proveedor_id,),
        )

    def listar_por_insumo(self, insumo_id: int) -> list[dict]:
        return self.db.fetch_all(
            """SELECT pi.*, p.nombre as proveedor_nombre
               FROM proveedor_insumos pi
               JOIN proveedores p ON p.id = pi.proveedor_id
               WHERE pi.insumo_id = ? AND pi.activo = 1 AND p.activo = 1
               ORDER BY pi.precio ASC""",
            (insumo_id,),
        )

    def guardar(self, proveedor_id: int, items: list[dict]) -> None:
        self.db.execute("DELETE FROM proveedor_insumos WHERE proveedor_id = ?", (proveedor_id,))
        for it in items:
            self.db.execute(
                "INSERT INTO proveedor_insumos (proveedor_id, insumo_id, color, unidad_medida, precio, comentario) VALUES (?, ?, ?, ?, ?, ?)",
                (proveedor_id, it["insumo_id"], it.get("color", ""),
                 it.get("unidad", "pieza"), it.get("precio", 0), it.get("comentario", "")),
            )


class UnidadesMedidaModel(BaseRepositorio):
    """Catálogo de unidades de medida."""

    tabla = "unidades_medida"
    sincronizable = False
    con_soft_delete = False
    usa_empresa = False
    orden_por_defecto = "nombre"

    def crear(self, nombre: str, abreviatura: str) -> int:
        return super().crear({"nombre": nombre, "abreviatura": abreviatura})

    def actualizar(self, unidad_id: int, nombre: str, abreviatura: str) -> None:
        super().actualizar(unidad_id, {"nombre": nombre, "abreviatura": abreviatura})


class OrdenCompraModel:
    def __init__(self) -> None:
        self.db = DatabaseManager()

    def _con_proveedores(self, ordenes: list[dict]) -> list[dict]:
        if not ordenes:
            return ordenes
        ids = ",".join(str(o["id"]) for o in ordenes)
        rows = self.db.fetch_all(
            f"""SELECT d.orden_compra_id, p.nombre
                FROM detalle_orden_compra d
                JOIN proveedores p ON p.id = d.proveedor_id
                WHERE d.orden_compra_id IN ({ids})
                GROUP BY d.orden_compra_id, p.id"""
        )
        por_oc: dict[int, list[str]] = {}
        for r in rows:
            por_oc.setdefault(r["orden_compra_id"], []).append(r["nombre"])
        for o in ordenes:
            provs = por_oc.get(o["id"], [])
            if o.get("proveedor_nombre") and o["proveedor_nombre"] not in provs:
                provs.append(o["proveedor_nombre"])
            o["proveedores"] = ", ".join(provs) if provs else "Compra a inventario"
        return ordenes

    def listar(self) -> list[dict]:
        where_emp = donde_empresa('oc')
        params = parametros_empresa()
        ordenes = self.db.fetch_all(
            f"""SELECT oc.*, p.nombre as proveedor_nombre, p.telefono as proveedor_telefono,
                      p.email as proveedor_email, p.rfc as proveedor_rfc,
                      p.direccion as proveedor_direccion
               FROM ordenes_compra oc
               LEFT JOIN proveedores p ON p.id = oc.proveedor_id
               WHERE 1=1 {where_emp}
               ORDER BY oc.created_at DESC""",
            tuple(params)
        )
        return self._con_proveedores(ordenes)

    def buscar(self, termino: str) -> list[dict]:
        q = "%" + termino + "%"
        where_emp = donde_empresa('oc')
        params: list = [q, q, q, q, q] + parametros_empresa()
        ordenes = self.db.fetch_all(
            "SELECT oc.*, p.nombre as proveedor_nombre,"
            " p.telefono as proveedor_telefono,"
            " p.email as proveedor_email, p.rfc as proveedor_rfc,"
            " p.direccion as proveedor_direccion"
            " FROM ordenes_compra oc"
            " LEFT JOIN proveedores p ON p.id = oc.proveedor_id"
            " WHERE (oc.folio LIKE ? OR EXISTS ("
            "    SELECT 1 FROM detalle_orden_compra d"
            "    JOIN proveedores dp ON dp.id = d.proveedor_id"
            "    WHERE d.orden_compra_id = oc.id"
            "      AND (dp.nombre LIKE ? OR dp.rfc LIKE ?)"
            " ) OR EXISTS ("
            "    SELECT 1 FROM detalle_orden_compra d2"
            "    JOIN insumos i ON i.id = d2.insumo_id"
            "    WHERE d2.orden_compra_id = oc.id"
            "      AND (i.nombre LIKE ? OR i.codigo LIKE ?)))"
            + where_emp +
            " ORDER BY oc.created_at DESC",
            tuple(params),
        )
        return self._con_proveedores(ordenes)

    def folio_existe(self, folio: str) -> bool:
        return self.db.fetch_one(
            "SELECT 1 FROM ordenes_compra WHERE folio = ?", (folio,)
        ) is not None

    def obtener(self, oc_id: int) -> Optional[dict]:
        return self.db.fetch_one(
            """SELECT oc.*, p.nombre as proveedor_nombre, p.telefono as proveedor_telefono,
                      p.email as proveedor_email, p.rfc as proveedor_rfc,
                      p.direccion as proveedor_direccion
               FROM ordenes_compra oc
               LEFT JOIN proveedores p ON p.id = oc.proveedor_id
               WHERE oc.id = ?""",
            (oc_id,),
        )

    def obtener_detalle(self, oc_id: int) -> list[dict]:
        detalle = self.db.fetch_all(
            """SELECT d.*, i.nombre as insumo_nombre, i.codigo as insumo_codigo, i.unidad_medida,
                      p.nombre as proveedor_nombre
               FROM detalle_orden_compra d
               JOIN insumos i ON i.id = d.insumo_id
               LEFT JOIN proveedores p ON p.id = d.proveedor_id
               WHERE d.orden_compra_id = ?
               ORDER BY d.id""",
            (oc_id,),
        )
        return self._con_tallas(detalle)

    def _con_tallas(self, detalle: list[dict]) -> list[dict]:
        if not detalle:
            return detalle
        ids = ",".join(str(d["id"]) for d in detalle)
        rows = self.db.fetch_all(
            f"""SELECT dt.detalle_id, dt.pares, dt.precio_unitario, tc.talla, tc.id as talla_id
                FROM detalle_orden_compra_puntos dt
                JOIN tallas_catalogo tc ON tc.id = dt.talla_id
                WHERE dt.detalle_id IN ({ids})
                ORDER BY CAST(tc.talla AS REAL)"""
        )
        por_detalle: dict[int, list[dict]] = {}
        for r in rows:
            por_detalle.setdefault(r["detalle_id"], []).append({
                "talla_id": r["talla_id"],
                "talla": r["talla"],
                "pares": r["pares"],
                "precio": r["precio_unitario"],
            })
        for d in detalle:
            d["tallas"] = por_detalle.get(d["id"], [])
        return detalle

    def listar_tallas(self) -> list[dict]:
        return self.db.fetch_all(
            "SELECT * FROM tallas_catalogo WHERE activo = 1 "
            "ORDER BY CAST(talla AS REAL)")


    def crear(self, folio: str, observaciones: str = "", proveedor_id: int | None = None,
              metodo_pago: str = "Transferencia bancaria", solo_remision: bool = False,
              tipo: str = "orden") -> int:
        cursor = self.db.execute(
            "INSERT INTO ordenes_compra (folio, observaciones, proveedor_id, metodo_pago, solo_remision, tipo) VALUES (?, ?, ?, ?, ?, ?)",
            (folio, observaciones, proveedor_id, metodo_pago, 1 if solo_remision else 0, tipo),
        )
        sync_insert('ordenes_compra', cursor.lastrowid, {
            'folio': folio, 'observaciones': observaciones,
            'proveedor_id': proveedor_id, 'estatus': 'pendiente', 'tipo': tipo,
        })
        return cursor.lastrowid

    def agregar_detalle(self, oc_id: int, insumo_id: int, cantidad: float,
                        precio_unitario: float, proveedor_id: int | None = None,
                        puntos: list[dict] | None = None) -> int:
        cursor = self.db.execute(
            "INSERT INTO detalle_orden_compra (orden_compra_id, insumo_id, cantidad, precio_unitario, proveedor_id) VALUES (?, ?, ?, ?, ?)",
            (oc_id, insumo_id, cantidad, precio_unitario, proveedor_id),
        )
        detalle_id = cursor.lastrowid
        for p in (puntos or []):
            if p.get("pares", 0) > 0:
                self.db.execute(
                    "INSERT OR REPLACE INTO detalle_orden_compra_puntos "
                    "(detalle_id, talla_id, pares, precio_unitario) VALUES (?, ?, ?, ?)",
                    (detalle_id, p["talla_id"], p["pares"], p.get("precio", 0) or 0),
                )
        return detalle_id

    def cancelar(self, oc_id: int) -> None:
        self.db.execute(
            "UPDATE ordenes_compra SET estatus='cancelada' WHERE id=? AND estatus='pendiente'",
            (oc_id,),
        )
        sync_update('ordenes_compra', oc_id, {'estatus': 'cancelada'})

    def recibir(self, oc_id: int) -> None:
        detalle = self.obtener_detalle(oc_id)
        for d in detalle:
            self.db.execute(
                "UPDATE insumos SET stock_actual = stock_actual + ?, updated_at = datetime('now') WHERE id = ?",
                (d["cantidad"], d["insumo_id"]),
            )
            self.db.execute(
                "INSERT INTO movimiento_inventario (insumo_id, tipo_movimiento, cantidad, referencia_tipo, referencia_id, observaciones) VALUES (?, 'entrada', ?, 'orden_compra', ?, ?)",
                (d["insumo_id"], d["cantidad"], oc_id, f"OC {d['orden_compra_id']}"),
            )
        total = sum(_subtotal_detalle_oc(d) for d in detalle)
        self.db.execute(
            "UPDATE ordenes_compra SET estatus='recibida', fecha_recibido=datetime('now'), total=? WHERE id=?",
            (total, oc_id),
        )
        sync_update('ordenes_compra', oc_id, {'estatus': 'recibida', 'total': total})
