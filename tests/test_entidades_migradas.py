"""Pruebas de ProveedorModel e InsumoModel migrados a BaseRepositorio.

Sigue el patrón del proyecto: un _BDTemporal sobre BD sqlite temporal con
monkeypatch, y verifica que la API pública de los modelos no cambió tras
la migración al repositorio base.
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
            "CREATE TABLE insumos (id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "codigo TEXT NOT NULL UNIQUE, nombre TEXT NOT NULL, "
            "categoria TEXT NOT NULL, unidad_medida TEXT NOT NULL DEFAULT 'pieza', "
            "stock_actual REAL NOT NULL DEFAULT 0, stock_minimo REAL NOT NULL DEFAULT 0, "
            "imagen BLOB, activo INTEGER NOT NULL DEFAULT 1, "
            "created_at TEXT DEFAULT (datetime('now')), "
            "updated_at TEXT DEFAULT (datetime('now')), "
            "empresa_id TEXT NOT NULL DEFAULT 'emp-1', "
            "is_deleted INTEGER NOT NULL DEFAULT 0)")
        cur.execute(
            "CREATE TABLE proveedores (id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "rfc TEXT NOT NULL UNIQUE, nombre TEXT NOT NULL, "
            "nombre_comercial TEXT, telefono TEXT, email TEXT, direccion TEXT, "
            "activo INTEGER NOT NULL DEFAULT 1, "
            "created_at TEXT DEFAULT (datetime('now')), "
            "empresa_id TEXT NOT NULL DEFAULT 'emp-1', "
            "is_deleted INTEGER NOT NULL DEFAULT 0)")
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
    from src.models import inventario_model as mod_inv
    bd = _BDTemporal(str(tmp_path / "entidades_test.db"))
    # Los hooks de sync no deben tocar la BD real durante las pruebas.
    for nombre in ("sync_insert", "sync_update", "sync_delete"):
        monkeypatch.setattr(mod_base, nombre, lambda *a, **k: None)
    # BaseRepositorio.__init__ construye DatabaseManager() desde base_repositorio.
    monkeypatch.setattr(mod_base, "DatabaseManager", lambda: bd)
    # InsumoModel también construye su propia referencia en inventario_model.
    monkeypatch.setattr(mod_inv, "DatabaseManager", lambda: bd)
    return bd


class TestProveedorModel:
    def test_crud_publico_igual_al_anterior(self, bd):
        from src.models.orden_compra_model import ProveedorModel
        m = ProveedorModel()
        prov_id = m.crear("RFC1", "PIELES DEL NORTE",
                          telefono="555", email="a@b.c",
                          direccion="CALLE 1", nombre_comercial="PIELES")
        assert prov_id > 0
        fila = m.obtener(prov_id)
        assert fila["nombre"] == "PIELES DEL NORTE"
        assert fila["nombre_comercial"] == "PIELES"

        m.actualizar(prov_id, "RFC1", "PIELES SA", "555", "a@b.c",
                     "CALLE 2", "PIELES SA")
        assert m.obtener(prov_id)["nombre"] == "PIELES SA"
        assert m.obtener(prov_id)["direccion"] == "CALLE 2"

        m.desactivar(prov_id)
        assert m.obtener(prov_id)["activo"] == 0
        assert m.listar() == []           # oculto de activos
        assert m.listar(solo_activos=False) != []

    def test_listar_ordena_por_nombre(self, bd):
        from src.models.orden_compra_model import ProveedorModel
        m = ProveedorModel()
        m.crear("RFC-B", "BETA")
        m.crear("RFC-A", "ALFA")
        assert [p["nombre"] for p in m.listar()] == ["ALFA", "BETA"]

    def test_buscar_por_rfc_nombre_o_comercial(self, bd):
        from src.models.orden_compra_model import ProveedorModel
        m = ProveedorModel()
        m.crear("RFC1", "SULTANA", nombre_comercial="SUELAS SULTANA")
        m.crear("RFC2", "GORETTI")
        assert len(m.buscar("SULTANA")) == 1
        assert len(m.buscar("GORETTI")) == 1
        assert len(m.buscar("SUELAS")) == 1
        assert m.buscar("INEXISTENTE") == []


class TestInsumoModel:
    def test_crud_y_listar_con_proyeccion(self, bd):
        from src.models.inventario_model import InsumoModel
        m = InsumoModel()
        ins_id = m.crear("INS-001", "PIEL CARA", "PIEL")
        assert ins_id > 0
        m.crear("INS-002", "SUELA", "SUELA")

        filas = m.listar()
        assert [f["nombre"] for f in filas] == ["PIEL CARA", "SUELA"]
        # La proyección no arrastra el BLOB de imagen.
        assert "imagen" not in filas[0]

        m.actualizar(ins_id, "INS-001", "PIEL VACA", "PIEL", "pieza", 5.0)
        assert m.obtener(ins_id)["nombre"] == "PIEL VACA"

    def test_desactivar_oculta_y_marca_soft_delete(self, bd):
        from src.models.inventario_model import InsumoModel
        m = InsumoModel()
        ins_id = m.crear("INS-003", "FORRO", "FORRO")
        m.desactivar(ins_id)
        fila = m.obtener(ins_id)
        assert fila["activo"] == 0
        assert fila["is_deleted"] == 1
        assert m.listar() == []

    def test_buscar_por_codigo_nombre_categoria(self, bd):
        from src.models.inventario_model import InsumoModel
        m = InsumoModel()
        m.crear("PL-01", "PLANTILLA", "ACCESORIO")
        assert len(m.buscar("PL-01")) == 1
        assert len(m.buscar("PLANTILLA")) == 1
        assert len(m.buscar("ACCESORIO")) == 1

    def test_existe_codigo_y_stock_bajo(self, bd):
        from src.models.inventario_model import InsumoModel
        m = InsumoModel()
        m.crear("INS-004", "HILO", "HILO", stock_minimo=10)
        assert m.existe_codigo("INS-004") is True
        assert m.existe_codigo("NO-EXISTE") is False
        # stock_actual=0 <= stock_minimo=10 → aparece en stock_bajo.
        assert len(m.stock_bajo()) == 1

    def test_actualizar_stock_acumula(self, bd):
        from src.models.inventario_model import InsumoModel
        m = InsumoModel()
        ins_id = m.crear("INS-005", "CIERRE", "ACCESORIO")
        m.actualizar_stock(ins_id, 25.0)
        m.actualizar_stock(ins_id, -5.0)
        assert m.obtener(ins_id)["stock_actual"] == 20.0