"""Pruebas de la capa de adaptación de placeholders en DatabaseManager.

Verifica que las consultas escritas con placeholders '?' (estilo SQLite)
se conviertan a '%s' (estilo psycopg2) cuando el motor activo es
PostgreSQL, y que los métodos execute/fetch_one/fetch_all la apliquen.
"""
from src.database.db_manager import DatabaseManager


def _manager_con(engine: str) -> DatabaseManager:
    """Instancia un DatabaseManager sin leer config.ini ni abrir conexión."""
    db = object.__new__(DatabaseManager)
    db._initialized = True
    db.engine = engine
    db.connection = None
    return db


class TestAdaptar:
    def test_sqlite_no_modifica_la_consulta(self):
        db = _manager_con("sqlite")
        sql = "SELECT * FROM insumos WHERE id = ? AND nombre LIKE ?"
        assert db._adaptar(sql) == sql

    def test_postgresql_convierte_interrogaciones(self):
        db = _manager_con("postgresql")
        sql = "SELECT * FROM insumos WHERE id = ? AND nombre LIKE ?"
        assert db._adaptar(sql) == \
            "SELECT * FROM insumos WHERE id = %s AND nombre LIKE %s"

    def test_postgresql_convierte_insert_y_update(self):
        db = _manager_con("postgresql")
        assert db._adaptar("INSERT INTO x (a, b) VALUES (?, ?)") == \
            "INSERT INTO x (a, b) VALUES (%s, %s)"
        assert db._adaptar("UPDATE x SET a = ? WHERE id = ?") == \
            "UPDATE x SET a = %s WHERE id = %s"

    def test_postgresql_convierte_funciones_con_parametro(self):
        db = _manager_con("postgresql")
        sql = "DELETE FROM sync_queue WHERE enviado_en < datetime('now', ?)"
        assert db._adaptar(sql) == \
            "DELETE FROM sync_queue WHERE enviado_en < datetime('now', %s)"

    def test_postgresql_sin_parametros_no_rompe(self):
        db = _manager_con("postgresql")
        sql = "SELECT COUNT(*) AS n FROM sync_queue"
        assert db._adaptar(sql) == sql


class _CursorFake:
    """Cursor que registra la última consulta ejecutada."""

    def __init__(self) -> None:
        self.ultima_query = None
        self.params = None

    def execute(self, query, params=()):
        self.ultima_query = query
        self.params = params
        return self

    def fetchone(self):
        return None


class _ConexionFake:
    def __init__(self) -> None:
        self.cursor_ = _CursorFake()

    def cursor(self):
        return self.cursor_

    def commit(self):
        pass

    def close(self):
        pass


class TestAplicacionEnExecute:
    def test_execute_aplica_adaptacion_en_postgresql(self, monkeypatch):
        db = _manager_con("postgresql")
        conn = _ConexionFake()
        monkeypatch.setattr(db, "connect", lambda: conn)

        db.execute("SELECT * FROM x WHERE id = ?", (1,))

        assert conn.cursor_.ultima_query == "SELECT * FROM x WHERE id = %s"
        assert conn.cursor_.params == (1,)

    def test_execute_no_aplica_en_sqlite(self, monkeypatch):
        db = _manager_con("sqlite")
        conn = _ConexionFake()
        monkeypatch.setattr(db, "connect", lambda: conn)

        sql = "SELECT * FROM x WHERE id = ?"
        db.execute(sql, (1,))

        assert conn.cursor_.ultima_query == sql
        assert conn.cursor_.params == (1,)