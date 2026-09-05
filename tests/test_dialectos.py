"""Pruebas del módulo de dialectos SQL (SQLite vs PostgreSQL).

Verifica que cada dialecto exponga los placeholders, tipos, expresiones
de fecha e introspección correctos para su motor.
"""
from src.database.dialectos import (
    DialectoPostgres,
    DialectoSqlite,
    obtener_dialecto,
)


class TestDialectoSqlite:
    def setup_method(self):
        self.d = DialectoSqlite()

    def test_placeholder_y_adaptar(self):
        assert self.d.placeholder == "?"
        sql = "SELECT * FROM x WHERE id = ?"
        assert self.d.adaptar(sql) == sql

    def test_expresiones_de_tipo(self):
        assert self.d.ahora() == "datetime('now')"
        assert self.d.auto_incremento() == "INTEGER PRIMARY KEY AUTOINCREMENT"
        assert self.d.booleano() == "INTEGER"
        assert self.d.blob() == "BLOB"


class TestDialectoPostgres:
    def setup_method(self):
        self.d = DialectoPostgres()

    def test_placeholder_y_adaptar(self):
        assert self.d.placeholder == "%s"
        sql = "SELECT * FROM x WHERE id = ? AND nombre LIKE ?"
        assert self.d.adaptar(sql) == \
            "SELECT * FROM x WHERE id = %s AND nombre LIKE %s"

    def test_expresiones_de_tipo(self):
        assert self.d.ahora() == "NOW()"
        assert self.d.auto_incremento() == "SERIAL PRIMARY KEY"
        assert self.d.booleano() == "BOOLEAN"
        assert self.d.blob() == "BYTEA"


class TestIntrospeccion:
    """Verifica la introspección contra una BD SQLite real."""

    def test_tabla_existe_y_columnas_sqlite(self, tmp_path):
        import sqlite3
        conn = sqlite3.connect(str(tmp_path / "introspeccion.db"))
        conn.execute("CREATE TABLE prueba (id INTEGER PRIMARY KEY, nombre TEXT)")
        d = DialectoSqlite()
        cursor = conn.cursor()
        assert d.tabla_existe(cursor, "prueba") is True
        assert d.tabla_existe(cursor, "inexistente") is False
        assert d.obtener_columnas(cursor, "prueba") == ["id", "nombre"]
        conn.close()


class TestRespaldo:
    """Métodos usados por respaldo_bd_utils: FK, insert-or-ignore, secuencias."""

    def test_insertar_o_ignorar_sqlite(self):
        d = DialectoSqlite()
        sql = d.sql_insertar_o_ignorar("insumos", ["id", "nombre"],
                                       con_conflicto_id=True)
        assert sql == "INSERT OR IGNORE INTO insumos (id, nombre) VALUES (?, ?)"

    def test_insertar_o_ignorar_postgres(self):
        d = DialectoPostgres()
        sql = d.sql_insertar_o_ignorar("insumos", ["id", "nombre"],
                                       con_conflicto_id=True)
        assert sql == ("INSERT INTO insumos (id, nombre) "
                       "VALUES (%s, %s) ON CONFLICT (id) DO NOTHING")
        # Sin conflicto_id: INSERT simple.
        sql2 = d.sql_insertar_o_ignorar("insumos", ["id"],
                                        con_conflicto_id=False)
        assert sql2 == "INSERT INTO insumos (id) VALUES (%s)"

    def test_fk_sqlite_real(self, tmp_path):
        import sqlite3
        conn = sqlite3.connect(str(tmp_path / "fk.db"))
        conn.execute("CREATE TABLE a (id INTEGER PRIMARY KEY)")
        conn.execute("CREATE TABLE b (id INTEGER PRIMARY KEY, "
                     "a_id INTEGER REFERENCES a(id))")
        cursor = conn.cursor()
        d = DialectoSqlite()
        d.desactivar_fk(cursor)
        # Con FK desactivadas se puede insertar un hijo huérfano.
        cursor.execute("INSERT INTO b (id, a_id) VALUES (1, 999)")
        conn.commit()
        assert d.contar_violaciones_fk(cursor) == 1
        d.restaurar_fk(cursor)
        conn.close()

    def test_reajustar_secuencia_sqlite_es_no_op(self, tmp_path):
        import sqlite3
        conn = sqlite3.connect(str(tmp_path / "seq.db"))
        conn.execute("CREATE TABLE a (id INTEGER PRIMARY KEY AUTOINCREMENT)")
        cursor = conn.cursor()
        # SQLite no lanza y no necesita ajustar nada.
        assert DialectoSqlite().reajustar_secuencia(cursor, "a") is None
        conn.close()


class TestObtenerDialecto:
    def test_selecciona_por_motor(self, monkeypatch):
        monkeypatch.setattr(
            "src.database.dialectos._instancia", None)
        assert isinstance(obtener_dialecto("sqlite"), DialectoSqlite)
        monkeypatch.setattr(
            "src.database.dialectos._instancia", None)
        assert isinstance(obtener_dialecto("postgresql"), DialectoPostgres)
        monkeypatch.setattr(
            "src.database.dialectos._instancia", None)
        # Motor desconocido cae a SQLite como seguro por defecto
        assert isinstance(obtener_dialecto("oracle"), DialectoSqlite)

    def test_singleton_por_motor(self, monkeypatch):
        monkeypatch.setattr(
            "src.database.dialectos._instancia", None)
        assert obtener_dialecto("sqlite") is obtener_dialecto("sqlite")
        monkeypatch.setattr(
            "src.database.dialectos._instancia", None)