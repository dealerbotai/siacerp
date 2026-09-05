"""Repositorio base: CRUD genérico con sync hooks y multi-tenant.

Cubre el patrón dominante de los modelos simples (catálogos y entidades
con CRUD directo): listar, obtener, crear, actualizar, desactivar,
eliminar (soft delete) y contar. Cada modelo hereda y solo declara su
tabla, sus columnas y su orden por defecto; las consultas con JOIN o
agregaciones se siguen escribiendo explícitas en el modelo concreto.

Los writes disparan los hooks de sincronización (sync_insert / sync_update
/ sync_delete) cuando la subclase es sincronizable, y el filtrado
multi-tenant (empresa_id) se aplica cuando la tabla lo requiere.
"""
from typing import Optional

from src.database.db_manager import DatabaseManager
from src.utils.empresa_context import obtener_empresa_id
from src.utils.sync_hooks import sync_insert, sync_update, sync_delete


class BaseRepositorio:
    # -- Configuración por subclase ----------------------------------
    tabla: str = ""
    sincronizable: bool = True      # False para catálogos que no se suben
    con_soft_delete: bool = True    # tabla con columna is_deleted
    usa_empresa: bool = True        # tabla con columna empresa_id
    orden_por_defecto: str = "id"

    def __init__(self) -> None:
        self.db = DatabaseManager()

    # -- Construcción de consultas -------------------------------------

    def _filtros(self, solo_activos: bool) -> tuple[str, list]:
        """Construye el WHERE (activo, is_deleted, empresa_id) y parámetros."""
        condiciones: list[str] = []
        params: list = []
        if solo_activos:
            condiciones.append("activo = 1")
        if self.con_soft_delete:
            condiciones.append("is_deleted = 0")
        if self.usa_empresa:
            emp = obtener_empresa_id()
            if emp:
                condiciones.append("empresa_id = ?")
                params.append(emp)
        if not condiciones:
            return "", []
        return " WHERE " + " AND ".join(condiciones), params

    # -- Consultas ------------------------------------------------------

    def listar(self, solo_activos: bool = True,
               orden: Optional[str] = None) -> list[dict]:
        where, params = self._filtros(solo_activos)
        orden_sql = orden or self.orden_por_defecto
        return self.db.fetch_all(
            f"SELECT * FROM {self.tabla}{where} ORDER BY {orden_sql}",
            tuple(params),
        )

    def obtener(self, registro_id: int) -> Optional[dict]:
        return self.db.fetch_one(
            f"SELECT * FROM {self.tabla} WHERE id = ?", (registro_id,))

    def contar(self, solo_activos: bool = True) -> int:
        where, params = self._filtros(solo_activos)
        fila = self.db.fetch_one(
            f"SELECT COUNT(*) AS n FROM {self.tabla}{where}",
            tuple(params),
        )
        return int(fila["n"]) if fila else 0

    # -- Escritura --------------------------------------------------------

    def crear(self, datos: dict) -> int:
        columnas = list(datos.keys())
        marcadores = ", ".join("?" for _ in columnas)
        sql = (f"INSERT INTO {self.tabla} ({', '.join(columnas)}) "
               f"VALUES ({marcadores})")
        conn = self.db.connect()
        cursor = conn.cursor()
        nuevo_id = self.db.dialecto.insertar_devolviendo_id(
            cursor, sql, tuple(datos.values()))
        conn.commit()
        if self.sincronizable:
            sync_insert(self.tabla, nuevo_id, datos)
        return nuevo_id

    def actualizar(self, registro_id: int, datos: dict) -> None:
        asignaciones = ", ".join(f"{c} = ?" for c in datos)
        self.db.execute(
            f"UPDATE {self.tabla} SET {asignaciones} WHERE id = ?",
            tuple(datos.values()) + (registro_id,),
        )
        if self.sincronizable:
            sync_update(self.tabla, registro_id, datos)

    def desactivar(self, registro_id: int) -> None:
        self.db.execute(
            f"UPDATE {self.tabla} SET activo = 0 WHERE id = ?",
            (registro_id,),
        )

    def eliminar(self, registro_id: int) -> None:
        """Soft delete cuando la tabla lo soporta; DELETE duro si no."""
        if self.con_soft_delete:
            self.db.execute(
                f"UPDATE {self.tabla} SET is_deleted = 1 WHERE id = ?",
                (registro_id,),
            )
        else:
            self.db.execute(
                f"DELETE FROM {self.tabla} WHERE id = ?", (registro_id,))
        if self.sincronizable:
            sync_delete(self.tabla, registro_id)