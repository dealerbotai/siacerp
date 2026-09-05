from src.database.base_repositorio import BaseRepositorio


class TallasModel(BaseRepositorio):
    """Catálogo unificado de tallas/puntos (RD-1).

    Un solo catálogo configurable, sin campo `orden`: el orden se deriva del
    valor numérico. La generación en serie crea la "corrida" de tallas
    (de X a Y, en pasos de medio punto).
    """

    tabla = "tallas_catalogo"
    sincronizable = False           # no se sube a Supabase (TABLAS_BAJAR)
    con_soft_delete = False         # no tiene columna is_deleted
    usa_empresa = False             # catálogo compartido, sin empresa_id
    orden_por_defecto = "CAST(talla AS REAL), talla"

    def crear(self, talla: str) -> int:
        return super().crear({"talla": talla})

    def actualizar(self, talla_id: int, talla: str) -> None:
        super().actualizar(talla_id, {"talla": talla})

    def activar(self, talla_id: int) -> None:
        self.db.execute(
            "UPDATE tallas_catalogo SET activo=1 WHERE id=?", (talla_id,)
        )

    def vaciar(self) -> int:
        cursor = self.db.execute("DELETE FROM tallas_catalogo")
        return cursor.rowcount

    def generar(self, desde: float, hasta: float) -> int:
        if desde > hasta:
            desde, hasta = hasta, desde
        existentes = {r["talla"] for r in
                      self.db.fetch_all("SELECT talla FROM tallas_catalogo")}
        creados = 0
        for i in range(int(desde * 2), int(hasta * 2) + 1):
            valor = i / 2
            talla = self._formatear_talla(valor)
            if talla not in existentes:
                self.db.execute(
                    "INSERT INTO tallas_catalogo (talla) VALUES (?)",
                    (talla,),
                )
                creados += 1
            else:
                self.db.execute(
                    "UPDATE tallas_catalogo SET activo=1 WHERE talla=?",
                    (talla,),
                )
        return creados

    @staticmethod
    def _formatear_talla(valor: float) -> str:
        entero = int(valor)
        if valor == entero:
            return f"{entero:02d}"
        return f"{entero:02d}.5"


class ColoresModel(BaseRepositorio):
    """Catálogo de colores."""

    tabla = "colores_catalogo"
    sincronizable = False
    con_soft_delete = False
    usa_empresa = False
    orden_por_defecto = "orden, nombre"

    def crear(self, nombre: str, codigo: str, orden: int) -> int:
        return super().crear({"nombre": nombre, "codigo": codigo, "orden": orden})

    def actualizar(self, color_id: int, nombre: str, codigo: str, orden: int) -> None:
        super().actualizar(color_id, {
            "nombre": nombre, "codigo": codigo, "orden": orden})