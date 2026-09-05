from typing import Optional
from src.database.base_repositorio import BaseRepositorio
from src.database.db_manager import DatabaseManager
from src.utils.empresa_context import donde_empresa, parametros_empresa
from src.utils.sync_hooks import sync_insert, sync_update, sync_delete


class InsumoModel(BaseRepositorio):
    """Insumos: CRUD con sync curado (payload sin imagen BLOB).

    Hereda la infraestructura del repositorio base (filtros multi-tenant,
    obtener, contar) y conserva sus consultas especializadas (búsquedas,
    stock, categorías) y sus writes con sync hooks y updated_at explícitos.
    """

    tabla = "insumos"
    sincronizable = True
    con_soft_delete = True
    usa_empresa = True
    orden_por_defecto = "nombre"

    _COLUMNAS = ("id", "codigo", "nombre", "categoria", "unidad_medida",
                 "stock_actual", "stock_minimo", "activo", "created_at", "updated_at")

    def listar(self, solo_activos: bool = True) -> list[dict]:
        where, params = self._filtros(solo_activos)
        query = (f"SELECT {', '.join(self._COLUMNAS)} FROM insumos{where}"
                 f" ORDER BY nombre")
        return self.db.fetch_all(query, tuple(params))

    def buscar(self, termino: str) -> list[dict]:
        q = "%" + termino + "%"
        where_emp = donde_empresa()
        params: list = [q, q, q] + parametros_empresa()
        return self.db.fetch_all(
            f"SELECT {', '.join(self._COLUMNAS)} FROM insumos"
            f" WHERE activo = 1 AND (codigo LIKE ? OR nombre LIKE ?"
            f" OR categoria LIKE ?){where_emp} ORDER BY nombre",
            tuple(params),
        )

    def listar_categorias(self, excluir_id: Optional[int] = None) -> list[str]:
        query = "SELECT DISTINCT categoria FROM insumos WHERE activo = 1 AND categoria IS NOT NULL AND TRIM(categoria) != ''"
        params: tuple = ()
        if excluir_id is not None:
            query += " AND id != ?"
            params = (excluir_id,)
        query += " ORDER BY categoria"
        rows = self.db.fetch_all(query, params)
        return [r["categoria"] for r in rows]

    def buscar_por_nombre(self, nombre: str, excluir_id: Optional[int] = None) -> list[dict]:
        q = "%" + nombre + "%"
        query = (
            f"SELECT {', '.join(self._COLUMNAS)} FROM insumos "
            "WHERE activo = 1 AND nombre LIKE ?"
        )
        params: list = [q]
        if excluir_id is not None:
            query += " AND id != ?"
            params.append(excluir_id)
        query += " ORDER BY CASE WHEN nombre = ? THEN 0 ELSE 1 END, nombre LIMIT 10"
        params.append(nombre)
        return self.db.fetch_all(query, tuple(params))

    def obtener(self, insumo_id: int) -> Optional[dict]:
        return self.db.fetch_one("SELECT * FROM insumos WHERE id = ?", (insumo_id,))

    def obtener_imagen(self, insumo_id: int) -> Optional[bytes]:
        row = self.db.fetch_one("SELECT imagen FROM insumos WHERE id = ?", (insumo_id,))
        return row["imagen"] if row else None

    def existe_codigo(self, codigo: str) -> bool:
        row = self.db.fetch_one("SELECT id FROM insumos WHERE codigo = ?", (codigo,))
        return row is not None

    def crear(self, codigo: str, nombre: str, categoria: str, unidad: str = "pieza",
              stock_minimo: float = 0, imagen: Optional[bytes] = None) -> int:
        cursor = self.db.execute(
            "INSERT INTO insumos (codigo, nombre, categoria, unidad_medida, stock_minimo, imagen) VALUES (?, ?, ?, ?, ?, ?)",
            (codigo, nombre, categoria, unidad, stock_minimo, imagen),
        )
        sync_insert('insumos', cursor.lastrowid, {
            'codigo': codigo, 'nombre': nombre, 'categoria': categoria,
            'unidad_medida': unidad, 'stock_minimo': stock_minimo,
        })
        return cursor.lastrowid

    def actualizar(self, insumo_id: int, codigo: str, nombre: str, categoria: str,
                    unidad: str, stock_minimo: float, imagen: Optional[bytes] = None) -> None:
        self.db.execute(
            "UPDATE insumos SET codigo=?, nombre=?, categoria=?, unidad_medida=?, stock_minimo=?, imagen=?, updated_at=datetime('now') WHERE id=?",
            (codigo, nombre, categoria, unidad, stock_minimo, imagen, insumo_id),
        )
        sync_update('insumos', insumo_id, {
            'codigo': codigo, 'nombre': nombre, 'categoria': categoria,
            'unidad_medida': unidad, 'stock_minimo': stock_minimo,
        })

    def desactivar(self, insumo_id: int) -> None:
        self.db.execute("UPDATE insumos SET activo=0, is_deleted=1, updated_at=datetime('now') WHERE id=?", (insumo_id,))
        sync_delete('insumos', insumo_id)

    def actualizar_stock(self, insumo_id: int, cantidad: float) -> None:
        self.db.execute(
            "UPDATE insumos SET stock_actual = stock_actual + ?, updated_at = datetime('now') WHERE id = ?",
            (cantidad, insumo_id),
        )

    def stock_bajo(self) -> list[dict]:
        return self.db.fetch_all(
            "SELECT * FROM insumos WHERE activo = 1 AND stock_actual <= stock_minimo ORDER BY (stock_minimo - stock_actual) DESC"
        )

    def listar_de_proveedor(self, proveedor_id: int) -> list[dict]:
        return self.db.fetch_all(
            """SELECT i.* FROM proveedor_insumos pi
               JOIN insumos i ON i.id = pi.insumo_id
               WHERE pi.proveedor_id = ? AND pi.activo = 1 AND i.activo = 1
               ORDER BY i.nombre""",
            (proveedor_id,),
        )

    def listar_sin_proveedor(self) -> list[dict]:
        return self.db.fetch_all(
            """SELECT * FROM insumos WHERE activo = 1
               AND NOT EXISTS (SELECT 1 FROM proveedor_insumos pi WHERE pi.insumo_id = insumos.id)
               ORDER BY nombre"""
        )


class ListaMaterialesModel:
    def __init__(self) -> None:
        self.db = DatabaseManager()

    def obtener_por_modelo(self, modelo_id: int) -> list[dict]:
        return self.db.fetch_all(
            """SELECT lm.*, i.nombre as insumo_nombre, i.unidad_medida
               FROM lista_materiales lm
               JOIN insumos i ON i.id = lm.insumo_id
               WHERE lm.modelo_id = ?""",
            (modelo_id,),
        )

    def costos_insumos(self, insumo_ids: list[int]) -> dict[int, float]:
        """Costo unitario por insumo.

        Toma el último precio de compra registrado (detalle_orden_compra);
        si el insumo no tiene compras, usa el menor precio activo de
        proveedor. Devuelve {insumo_id: costo} (0 si no hay referencia).
        """
        if not insumo_ids:
            return {}
        marcadores = ", ".join("?" for _ in insumo_ids)
        filas = self.db.fetch_all(
            f"""SELECT i.id AS insumo_id,
                   (SELECT doc.precio_unitario FROM detalle_orden_compra doc
                    WHERE doc.insumo_id = i.id
                    ORDER BY doc.id DESC LIMIT 1) AS ultimo_costo,
                   (SELECT MIN(pi.precio) FROM proveedor_insumos pi
                    WHERE pi.insumo_id = i.id AND pi.activo = 1
                      AND pi.precio > 0) AS precio_proveedor
            FROM insumos i WHERE i.id IN ({marcadores})""",
            tuple(insumo_ids))
        return {
            f["insumo_id"]: float(f["ultimo_costo"] or 0)
            or float(f["precio_proveedor"] or 0)
            for f in filas
        }

    def agregar(self, modelo_id: int, insumo_id: int,
                cantidad: float = 0, unidad: str = "pieza") -> bool:
        """Inserta un insumo en la BOM del modelo si no existía.

        Devuelve True si insertó, False si ya existía.
        """
        existente = self.db.fetch_one(
            "SELECT id FROM lista_materiales "
            "WHERE modelo_id = ? AND insumo_id = ?",
            (modelo_id, insumo_id))
        if existente:
            return False
        insumo = self.db.fetch_one(
            "SELECT unidad_medida FROM insumos WHERE id = ?",
            (insumo_id,))
        if insumo:
            unidad = insumo["unidad_medida"]
        self.db.execute(
            "INSERT INTO lista_materiales "
            "(modelo_id, insumo_id, cantidad_por_par, unidad) "
            "VALUES (?, ?, ?, ?)",
            (modelo_id, insumo_id, cantidad, unidad))
        return True


class MovimientoInventarioModel:
    def __init__(self) -> None:
        self.db = DatabaseManager()

    def listar(self, insumo_id: Optional[int] = None) -> list[dict]:
        base = """
            SELECT m.*, i.nombre as insumo_nombre,
                   COALESCE(mg.folio, oc.folio, op.folio, m.observaciones) AS folio,
                   COALESCE(oc.folio, op.folio, m.observaciones) AS referencia_folio
            FROM movimiento_inventario m
            JOIN insumos i ON i.id = m.insumo_id
            LEFT JOIN movimientos_inventario mg
              ON m.referencia_tipo = 'movimiento' AND mg.id = m.referencia_id
            LEFT JOIN ordenes_compra oc
              ON m.referencia_tipo = 'orden_compra' AND oc.id = m.referencia_id
            LEFT JOIN ordenes_produccion op
              ON m.referencia_tipo = 'orden_produccion' AND op.id = m.referencia_id
        """
        if insumo_id:
            return self.db.fetch_all(
                base + " WHERE m.insumo_id = ? ORDER BY m.created_at DESC",
                (insumo_id,),
            )
        return self.db.fetch_all(base + " ORDER BY m.created_at DESC LIMIT 500")

    def listar_kardex(self, insumo_id: int) -> list[dict]:
        """Movimientos del insumo en orden cronológico (para kardex)."""
        base = """
            SELECT m.*, i.nombre as insumo_nombre,
                   COALESCE(oc.folio, op.folio, m.observaciones) AS referencia_folio
            FROM movimiento_inventario m
            JOIN insumos i ON i.id = m.insumo_id
            LEFT JOIN ordenes_compra oc
              ON m.referencia_tipo = 'orden_compra' AND oc.id = m.referencia_id
            LEFT JOIN ordenes_produccion op
              ON m.referencia_tipo = 'orden_produccion' AND op.id = m.referencia_id
        """
        return self.db.fetch_all(
            base + " WHERE m.insumo_id = ? ORDER BY m.created_at ASC, m.id ASC",
            (insumo_id,),
        )

    def registrar(self, insumo_id: int, tipo: str, cantidad: float,
                  ref_tipo: Optional[str] = None, ref_id: Optional[int] = None,
                  obs: str = "") -> int:
        cursor = self.db.execute(
            "INSERT INTO movimiento_inventario (insumo_id, tipo_movimiento, cantidad, referencia_tipo, referencia_id, observaciones) VALUES (?, ?, ?, ?, ?, ?)",
            (insumo_id, tipo, cantidad, ref_tipo, ref_id, obs),
        )
        return cursor.lastrowid
