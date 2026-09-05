"""Pruebas de BaseRepositorio y de los catálogos migrados (RD-1/step 3).

Sigue el patrón del proyecto: un _BDTemporal (mini DatabaseManager sobre
una BD sqlite temporal) que se inyecta con monkeypatch, y verifica que la
API pública de los modelos no cambió tras la migración al repositorio base.
"""
import sqlite3

import pytest

from src.database.dialectos import DialectoSqlite

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")


class _BDTemporal:
    """Mini DatabaseManager sobre una BD sqlite temporal (mismos métodos)."""

    def __init__(self, path: str) -> None:
        self.engine = "sqlite"
        self.dialecto = DialectoSqlite()
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        cur = self.conn.cursor()
        cur.execute(
            "CREATE TABLE tallas_catalogo (id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "talla TEXT NOT NULL UNIQUE, activo INTEGER NOT NULL DEFAULT 1)")
        cur.execute(
            "CREATE TABLE colores_catalogo (id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "nombre TEXT NOT NULL, codigo TEXT, orden INTEGER NOT NULL DEFAULT 0, "
            "activo INTEGER NOT NULL DEFAULT 1)")
        cur.execute(
            "CREATE TABLE unidades_medida (id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "nombre TEXT NOT NULL, abreviatura TEXT NOT NULL, "
            "activo INTEGER NOT NULL DEFAULT 1)")
        self.conn.commit()

    def connect(self):
        return self.conn

    def execute(self, query: str, params: tuple = ()):
        c = self.conn.cursor()
        c.execute(query, params)
        self.conn.commit()
        return c

    def fetch_one(self, query: str, params: tuple = ()):
        c = self.conn.cursor()
        c.execute(query, params)
        row = c.fetchone()
        return dict(row) if row else None

    def fetch_all(self, query: str, params: tuple = ()):
        c = self.conn.cursor()
        c.execute(query, params)
        return [dict(r) for r in c.fetchall()]


@pytest.fixture
def bd(tmp_path, monkeypatch):
    from src.database import base_repositorio as mod_base
    bd = _BDTemporal(str(tmp_path / "catalogos_test.db"))
    monkeypatch.setattr(mod_base, "DatabaseManager", lambda: bd)
    return bd


class TestBaseRepositorio:
    def test_crear_devuelve_id_y_lista_por_orden(self, bd):
        from src.models.catalogos_model import TallasModel
        m = TallasModel()
        id_b = m.crear("02")
        id_a = m.crear("01")
        assert id_a > 0 and id_b > 0
        tallas = [t["talla"] for t in m.listar()]
        # Orden numérico derivado del valor, sin campo orden.
        assert tallas == ["01", "02"]

    def test_actualizar_modifica_el_registro(self, bd):
        from src.models.catalogos_model import TallasModel
        m = TallasModel()
        talla_id = m.crear("05")
        m.actualizar(talla_id, "05.5")
        fila = m.obtener(talla_id)
        assert fila["talla"] == "05.5"

    def test_desactivar_oculta_de_listar_solo_activos(self, bd):
        from src.models.catalogos_model import ColoresModel
        m = ColoresModel()
        color_id = m.crear("NEGRO", "NEG", 1)
        m.desactivar(color_id)
        assert m.obtener(color_id) is not None          # sigue en BD
        assert m.listar() == []                          # oculto de activos
        assert m.listar(solo_activos=False) != []        # visible con todo

    def test_eliminar_sin_soft_delete_borra_registro(self, bd):
        from src.models.catalogos_model import TallasModel
        m = TallasModel()
        talla_id = m.crear("07")
        m.eliminar(talla_id)
        assert m.obtener(talla_id) is None

    def test_contar(self, bd):
        from src.models.catalogos_model import TallasModel
        m = TallasModel()
        m.crear("08")
        m.crear("09")
        assert m.contar() == 2


class TestTallasModel:
    def test_generar_corrida_y_reintento_idempotente(self, bd):
        from src.models.catalogos_model import TallasModel
        m = TallasModel()
        creados = m.generar(10.0, 12.0)
        assert creados == 5  # 10, 10.5, 11, 11.5, 12
        tallas = {t["talla"] for t in m.listar(solo_activos=False)}
        assert tallas == {"10", "10.5", "11", "11.5", "12"}

        # Reintento: no duplica, solo reactiva.
        creados2 = m.generar(10.0, 12.0)
        assert creados2 == 0
        assert m.listar(solo_activos=False) and m.contar() == 5

    def test_generar_invierte_rango_descendente(self, bd):
        from src.models.catalogos_model import TallasModel
        m = TallasModel()
        m.generar(12.0, 10.0)
        assert m.contar() == 5

    def test_vaciar(self, bd):
        from src.models.catalogos_model import TallasModel
        m = TallasModel()
        m.generar(10.0, 11.0)
        assert m.vaciar() == 3
        assert m.contar() == 0

    def test_formatear_talla(self):
        from src.models.catalogos_model import TallasModel
        assert TallasModel._formatear_talla(10.0) == "10"
        assert TallasModel._formatear_talla(10.5) == "10.5"


class TestColoresModel:
    def test_orden_por_orden_y_nombre(self, bd):
        from src.models.catalogos_model import ColoresModel
        m = ColoresModel()
        m.crear("ROJO", "ROJ", 2)
        m.crear("AZUL", "AZL", 1)
        m.crear("AMARILLO", "AMA", 1)
        nombres = [c["nombre"] for c in m.listar()]
        assert nombres == ["AMARILLO", "AZUL", "ROJO"]

    def test_actualizar(self, bd):
        from src.models.catalogos_model import ColoresModel
        m = ColoresModel()
        color_id = m.crear("BLANCO", "BLA", 3)
        m.actualizar(color_id, "BLANCO HUESO", "BHO", 4)
        fila = m.obtener(color_id)
        assert fila["nombre"] == "BLANCO HUESO"
        assert fila["codigo"] == "BHO"
        assert fila["orden"] == 4


class TestUnidadesMedidaModel:
    def test_crud_publico_igual_al_anterior(self, bd):
        from src.models.orden_compra_model import UnidadesMedidaModel
        m = UnidadesMedidaModel()
        unidad_id = m.crear("PAR", "PAR")
        assert unidad_id > 0
        m.actualizar(unidad_id, "PARES", "PRS")
        assert m.obtener(unidad_id)["nombre"] == "PARES"
        assert m.listar()[0]["abreviatura"] == "PRS"
        m.desactivar(unidad_id)
        assert m.listar() == []

    def test_orden_por_nombre(self, bd):
        from src.models.orden_compra_model import UnidadesMedidaModel
        m = UnidadesMedidaModel()
        m.crear("CAJA", "CJ")
        m.crear("BOLSA", "BL")
        assert [u["nombre"] for u in m.listar()] == ["BOLSA", "CAJA"]