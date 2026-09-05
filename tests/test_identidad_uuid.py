"""Pruebas de la identidad global por registro (columna uuid, RD-9).

Cubre tres piezas de la fase 1 local:
  1. _migrar_uuids: agrega la columna uuid + indice unico y hace backfill
     uuid4 sobre filas existentes (idempotente).
  2. sync_hooks: _asegurar_uuid genera/persiste el uuid y los hooks encolan
     payloads con uuid.
  3. SyncService._upsert_local: resuelve la identidad por uuid (colision de
     ids entre terminales de la misma empresa) y conserva compatibilidad
     con filas legadas sin uuid.

Todas corren contra BD sqlite temporales; no tocan la BD real ni Supabase.
"""
import sqlite3
import uuid as lib_uuid

import pytest

from src.database.dialectos import DialectoSqlite
from src.database.db_manager import DatabaseManager

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")


def _crear_conexion(path, con_uuid=True, con_dos_filas=False):
    """Crea una BD sqlite temporal con la tabla insumos (con/sin uuid)."""
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    col_uuid = ", uuid TEXT" if con_uuid else ""
    cur = conn.cursor()
    cur.execute(
        "CREATE TABLE insumos (id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "codigo TEXT NOT NULL, nombre TEXT NOT NULL, "
        "activo INTEGER NOT NULL DEFAULT 1" + col_uuid + ")")
    cur.execute("INSERT INTO insumos (codigo, nombre) VALUES (?, ?)",
                ("INS-1", "PIEL"))
    if con_dos_filas:
        cur.execute("INSERT INTO insumos (codigo, nombre) VALUES (?, ?)",
                    ("INS-2", "SUELA"))
    conn.commit()
    return conn


class _ManagerMigracion:
    """DatabaseManager real (sin __init__) enganchado a una BD temporal."""

    def __init__(self, conn):
        db = object.__new__(DatabaseManager)
        db._initialized = True
        db.engine = "sqlite"
        db.dialecto = DialectoSqlite()
        db.connection = None
        db.connect = lambda: conn
        self.db = db


class _BD:
    """Mini capa de datos (mismos metodos que DatabaseManager)."""

    def __init__(self, conn):
        self.engine = "sqlite"
        self.dialecto = DialectoSqlite()
        self.conn = conn

    def connect(self):
        return self.conn

    def execute(self, query, params=()):
        c = self.conn.cursor()
        c.execute(query, params)
        self.conn.commit()
        return c

    def fetch_one(self, query, params=()):
        c = self.conn.cursor()
        c.execute(query, params)
        row = c.fetchone()
        return dict(row) if row else None

    def fetch_all(self, query, params=()):
        c = self.conn.cursor()
        c.execute(query, params)
        return [dict(r) for r in c.fetchall()]


def _uuid_valido(valor):
    try:
        return str(lib_uuid.UUID(str(valor))) == str(valor).lower()
    except (ValueError, AttributeError):
        return False


# ----------------------------------------------------------------------
# 1. Migración _migrar_uuids + backfill
# ----------------------------------------------------------------------

class TestMigracionUuids:
    def test_agrega_columna_y_backfill(self, tmp_path):
        conn = _crear_conexion(str(tmp_path / "mig.db"), con_uuid=False)
        db = _ManagerMigracion(conn).db

        db._migrar_uuids()

        # Columna presente y fila existente con uuid v4.
        fila = conn.execute(
            "SELECT uuid FROM insumos WHERE codigo = 'INS-1'").fetchone()
        assert fila is not None and _uuid_valido(fila["uuid"])
        # Indice unico creado.
        idx = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'index' "
            "AND name = 'idx_insumos_uuid'").fetchone()
        assert idx is not None
        conn.close()

    def test_idempotente_no_sobrescribe_uuids(self, tmp_path):
        conn = _crear_conexion(str(tmp_path / "mig2.db"), con_uuid=False)
        db = _ManagerMigracion(conn).db

        db._migrar_uuids()
        antes = conn.execute(
            "SELECT uuid FROM insumos WHERE codigo = 'INS-1'").fetchone()["uuid"]

        db._migrar_uuids()  # segunda ejecucion

        despues = conn.execute(
            "SELECT uuid FROM insumos WHERE codigo = 'INS-1'").fetchone()["uuid"]
        assert antes == despues
        # Todas las filas tienen uuid.
        nulos = conn.execute(
            "SELECT COUNT(*) AS n FROM insumos "
            "WHERE uuid IS NULL OR uuid = ''").fetchone()["n"]
        assert nulos == 0
        conn.close()

    def test_backfill_sobre_varias_filas(self, tmp_path):
        conn = _crear_conexion(str(tmp_path / "mig3.db"),
                               con_uuid=False, con_dos_filas=True)
        db = _ManagerMigracion(conn).db

        db._migrar_uuids()

        uuids = [r["uuid"] for r in conn.execute(
            "SELECT uuid FROM insumos ORDER BY id").fetchall()]
        assert len(uuids) == 2
        assert len(set(uuids)) == 2  # distintos entre si
        conn.close()

    def test_tablas_inexistentes_no_rompen(self, tmp_path):
        """El catalogo incluye tablas que aun no existen localmente."""
        conn = _crear_conexion(str(tmp_path / "mig4.db"), con_uuid=False)
        db = _ManagerMigracion(conn).db

        db._migrar_uuids()  # no debe lanzar

        assert conn.execute(
            "SELECT COUNT(*) AS n FROM insumos WHERE uuid IS NOT NULL"
        ).fetchone()["n"] == 1
        conn.close()


# ----------------------------------------------------------------------
# 2. sync_hooks: garantia de uuid al encolar
# ----------------------------------------------------------------------

class _ColaFalsa:
    """Reemplaza SyncQueueModel en las pruebas: registra lo encolado."""

    def __init__(self):
        self.llamadas = []

    def encolar_insert(self, tabla, registro_id, datos):
        self.llamadas.append(("INSERT", tabla, registro_id, dict(datos)))

    def encolar_update(self, tabla, registro_id, datos):
        self.llamadas.append(("UPDATE", tabla, registro_id, dict(datos)))

    def encolar_delete(self, tabla, registro_id, datos):
        self.llamadas.append(("DELETE", tabla, registro_id,
                              dict(datos) if datos else None))


@pytest.fixture
def entorno_hooks(tmp_path, monkeypatch):
    """BD temporal + DatabaseManager parcheado + cola falsa."""
    import src.utils.sync_hooks as hooks

    conn = _crear_conexion(str(tmp_path / "hooks.db"), con_uuid=True)
    bd = _BD(conn)
    cola = _ColaFalsa()

    monkeypatch.setattr("src.database.db_manager.DatabaseManager",
                        lambda: bd)
    monkeypatch.setattr(hooks, "_get_queue", lambda: cola)
    monkeypatch.setattr(hooks, "sync_trigger", lambda: None)

    return {"bd": bd, "cola": cola, "conn": conn, "hooks": hooks}


class TestHooksUuid:
    def test_asegurar_uuid_genera_y_persiste(self, entorno_hooks):
        import src.utils.sync_hooks as hooks
        bd = entorno_hooks["bd"]

        valor = hooks._asegurar_uuid("insumos", 1)

        assert _uuid_valido(valor)
        fila = bd.fetch_one("SELECT uuid FROM insumos WHERE id = 1")
        assert fila["uuid"] == valor

    def test_asegurar_uuid_no_sobrescribe(self, entorno_hooks):
        import src.utils.sync_hooks as hooks
        bd = entorno_hooks["bd"]
        bd.execute("UPDATE insumos SET uuid = 'fijo-1234' WHERE id = 1")

        valor = hooks._asegurar_uuid("insumos", 1)

        assert valor == "fijo-1234"

    def test_asegurar_uuid_tabla_sin_columna_devuelve_none(self, entorno_hooks,
                                                           tmp_path,
                                                           monkeypatch):
        import sqlite3
        import src.utils.sync_hooks as hooks
        # Tabla sin columna uuid (legado) -> compatibilidad: None.
        conn = sqlite3.connect(str(tmp_path / "legacy.db"))
        conn.execute("CREATE TABLE tallas (id INTEGER PRIMARY KEY, talla TEXT)")
        conn.commit()
        bd_legacy = _BD(conn)
        monkeypatch.setattr("src.database.db_manager.DatabaseManager",
                            lambda: bd_legacy)

        assert hooks._asegurar_uuid("tallas", 1) is None
        conn.close()

    def test_con_uuid_agrega_uuid_al_payload(self, entorno_hooks):
        import src.utils.sync_hooks as hooks

        payload = hooks._con_uuid("insumos", 1, {"codigo": "INS-1"})

        assert "uuid" in payload
        assert _uuid_valido(payload["uuid"])

    def test_con_uuid_respeta_uuid_existente(self, entorno_hooks):
        import src.utils.sync_hooks as hooks

        payload = hooks._con_uuid("insumos", 1,
                                  {"codigo": "INS-1", "uuid": "ya-existe"})

        assert payload["uuid"] == "ya-existe"

    def test_sync_insert_encola_con_uuid(self, entorno_hooks):
        import src.utils.sync_hooks as hooks
        bd = entorno_hooks["bd"]
        cola = entorno_hooks["cola"]

        hooks.sync_insert("insumos", 1, {"codigo": "INS-1", "nombre": "PIEL"})

        assert len(cola.llamadas) == 1
        _, tabla, rid, payload = cola.llamadas[0]
        assert tabla == "insumos" and rid == 1
        assert payload["codigo"] == "INS-1"
        assert payload["uuid"] == bd.fetch_one(
            "SELECT uuid FROM insumos WHERE id = 1")["uuid"]

    def test_sync_delete_encola_uuid(self, entorno_hooks):
        import src.utils.sync_hooks as hooks
        bd = entorno_hooks["bd"]
        cola = entorno_hooks["cola"]
        bd.execute("UPDATE insumos SET uuid = 'para-borrar' WHERE id = 1")

        hooks.sync_delete("insumos", 1)

        assert len(cola.llamadas) == 1
        op, _, rid, payload = cola.llamadas[0]
        assert op == "DELETE" and rid == 1
        assert payload == {"uuid": "para-borrar"}


# ----------------------------------------------------------------------
# 3. SyncService._upsert_local: identidad por uuid
# ----------------------------------------------------------------------

class _SyncConBD:
    """SyncService real (sin __init__) con .db enganchado a la BD temporal."""

    def __init__(self, bd):
        from src.utils.sync_service import SyncService
        svc = object.__new__(SyncService)
        svc._initialized = True
        svc.db = bd
        self.svc = svc


def _crear_bd_con_uuid(path, con_fila_legada=False):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute(
        "CREATE TABLE insumos (id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "codigo TEXT NOT NULL, nombre TEXT NOT NULL, "
        "activo INTEGER NOT NULL DEFAULT 1, "
        "uuid TEXT, empresa_id TEXT NOT NULL DEFAULT 'emp-1', "
        "is_deleted INTEGER NOT NULL DEFAULT 0)")
    conn.commit()
    return conn


def _tabla_insumos_completa():
    return ["id", "codigo", "nombre", "activo", "uuid",
            "empresa_id", "is_deleted"]


class TestUpsertLocal:
    def test_inserta_fila_nueva_con_id_y_uuid(self, tmp_path):
        conn = _crear_bd_con_uuid(str(tmp_path / "up1.db"))
        svc = _SyncConBD(_BD(conn)).svc

        svc._upsert_local("insumos", {
            "id": 42, "uuid": "U-42", "codigo": "INS-42", "nombre": "NUEVA",
            "activo": True, "is_deleted": False,
        })

        fila = conn.execute(
            "SELECT * FROM insumos WHERE uuid = 'U-42'").fetchone()
        assert fila is not None
        assert fila["id"] == 42
        assert fila["codigo"] == "INS-42"
        conn.close()

    def test_mismo_uuid_distinto_id_actualiza_sin_duplicar(self, tmp_path):
        """Colision entre terminales: remoto trae id distinto, mismo uuid."""
        conn = _crear_bd_con_uuid(str(tmp_path / "up2.db"))
        cur = conn.cursor()
        cur.execute("INSERT INTO insumos (id, codigo, nombre, uuid) "
                    "VALUES (1, 'INS-1', 'LOCAL', 'U-1')")
        conn.commit()
        svc = _SyncConBD(_BD(conn)).svc

        svc._upsert_local("insumos", {
            "id": 99, "uuid": "U-1", "codigo": "INS-1",
            "nombre": "REMOTO ACTUALIZADO", "activo": True,
        })

        filas = conn.execute("SELECT * FROM insumos").fetchall()
        assert len(filas) == 1            # no se duplica
        assert filas[0]["id"] == 1        # conserva el id local
        assert filas[0]["nombre"] == "REMOTO ACTUALIZADO"
        assert filas[0]["uuid"] == "U-1"
        conn.close()

    def test_id_ocupado_por_otro_uuid_no_pisa(self, tmp_path):
        """Dos filas logicas distintas con el mismo id: la segunda se
        inserta con id nuevo y conserva su uuid."""
        conn = _crear_bd_con_uuid(str(tmp_path / "up3.db"))
        cur = conn.cursor()
        cur.execute("INSERT INTO insumos (id, codigo, nombre, uuid) "
                    "VALUES (1, 'INS-1', 'TERMINAL A', 'U-A')")
        conn.commit()
        svc = _SyncConBD(_BD(conn)).svc

        svc._upsert_local("insumos", {
            "id": 1, "uuid": "U-B", "codigo": "INS-2",
            "nombre": "TERMINAL B", "activo": True,
        })

        filas = conn.execute(
            "SELECT * FROM insumos ORDER BY id").fetchall()
        assert len(filas) == 2
        # La fila original no fue pisada.
        assert filas[0]["nombre"] == "TERMINAL A"
        assert filas[0]["uuid"] == "U-A"
        # La nueva fila existe con id distinto y su uuid intacto.
        assert filas[1]["uuid"] == "U-B"
        assert filas[1]["id"] != 1
        conn.close()

    def test_fila_legada_sin_uuid_adopta_uuid_remoto(self, tmp_path):
        """Registros creados antes de RD-9: al bajar con uuid, la fila
        local lo adopta (match por id) sin duplicarse."""
        conn = _crear_bd_con_uuid(str(tmp_path / "up4.db"))
        cur = conn.cursor()
        cur.execute("INSERT INTO insumos (id, codigo, nombre, uuid) "
                    "VALUES (5, 'INS-5', 'LEGADO', NULL)")
        conn.commit()
        svc = _SyncConBD(_BD(conn)).svc

        svc._upsert_local("insumos", {
            "id": 5, "uuid": "U-5", "codigo": "INS-5",
            "nombre": "LEGADO REMOTO", "activo": True,
        })

        filas = conn.execute("SELECT * FROM insumos").fetchall()
        assert len(filas) == 1
        assert filas[0]["uuid"] == "U-5"
        assert filas[0]["nombre"] == "LEGADO REMOTO"
        conn.close()

    def test_registro_sin_uuid_se_resuelve_por_id(self, tmp_path):
        """Compatibilidad: un remoto sin uuid (otra terminal sin RD-9)
        actualiza por id, como hacia el sync legado."""
        conn = _crear_bd_con_uuid(str(tmp_path / "up5.db"))
        cur = conn.cursor()
        cur.execute("INSERT INTO insumos (id, codigo, nombre, uuid) "
                    "VALUES (7, 'INS-7', 'VIEJO', NULL)")
        conn.commit()
        svc = _SyncConBD(_BD(conn)).svc

        svc._upsert_local("insumos", {
            "id": 7, "codigo": "INS-7", "nombre": "ACTUALIZADO POR ID",
        })

        filas = conn.execute("SELECT * FROM insumos").fetchall()
        assert len(filas) == 1
        assert filas[0]["nombre"] == "ACTUALIZADO POR ID"
        conn.close()
