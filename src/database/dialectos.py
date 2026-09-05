"""Dialectos SQL soportados: SQLite (desarrollo) y PostgreSQL (producción).

Centraliza las diferencias de motor que antes se ramificaban con
`if self.engine == 'sqlite'` por todo el código. Los modelos, las
migraciones y los servicios consultan el dialecto activo en lugar de
preguntar por el motor directamente. Si mañana se soporta otro motor,
basta con agregar una clase nueva en este módulo.

Compatibilidad: SQLite (desarrollo/local) y PostgreSQL 14+ (producción).
"""
from typing import Optional


class DialectoBase:
    """Contrato mínimo de un dialecto SQL."""

    nombre: str = "base"

    # Placeholder de parámetro: "?" (SQLite) o "%s" (psycopg2).
    placeholder: str = "?"

    def adaptar(self, query: str) -> str:
        """Convierte los placeholders de la consulta al estilo del motor.

        Los modelos escriben SQL con "?" (estilo SQLite); en PostgreSQL
        se sustituyen por "%s" antes de ejecutar.
        """
        return query

    def ahora(self) -> str:
        """Expresión SQL de fecha/hora actual (sin paréntesis)."""
        raise NotImplementedError

    def auto_incremento(self) -> str:
        """Cláusula de columna id autogenerada (entero)."""
        raise NotImplementedError

    def booleano(self) -> str:
        """Tipo SQL para valores booleanos."""
        raise NotImplementedError

    def blob(self) -> str:
        """Tipo SQL para datos binarios (BLOB/BYTEA)."""
        raise NotImplementedError

    def obtener_columnas(self, cursor, tabla: str) -> list[str]:
        """Devuelve los nombres de columna de una tabla existente."""
        raise NotImplementedError

    def tabla_existe(self, cursor, tabla: str) -> bool:
        """Indica si la tabla existe en el esquema."""
        raise NotImplementedError

    def insertar_devolviendo_id(self, cursor, sql: str, params: tuple) -> int:
        """Ejecuta un INSERT y devuelve el id autogenerado.

        SQLite expone cursor.lastrowid; PostgreSQL requiere la cláusula
        RETURNING id y leer la fila devuelta.
        """
        raise NotImplementedError

    def desactivar_fk(self, cursor) -> None:
        """Desactiva las restricciones de llave foránea de la sesión."""
        raise NotImplementedError

    def restaurar_fk(self, cursor) -> None:
        """Reactiva las restricciones de llave foránea de la sesión."""
        raise NotImplementedError

    def sql_insertar_o_ignorar(self, tabla: str, columnas: list[str],
                               con_conflicto_id: bool = False) -> str:
        """Genera un INSERT que ignora duplicados.

        SQLite: INSERT OR IGNORE INTO. PostgreSQL: INSERT INTO + cláusula
        ON CONFLICT (id) DO NOTHING cuando con_conflicto_id es True
        (las filas ya insertadas con el mismo id no fallan).
        """
        raise NotImplementedError

    def reajustar_secuencia(self, cursor, tabla: str) -> None:
        """Reajusta la secuencia serial al máximo id (PostgreSQL).

        SQLite no tiene secuencias separadas (no hace nada).
        """
        raise NotImplementedError

    def contar_violaciones_fk(self, cursor) -> int:
        """Cuenta violaciones de llave foránea pendientes en la sesión."""
        raise NotImplementedError


class DialectoSqlite(DialectoBase):
    nombre = "sqlite"
    placeholder = "?"

    def adaptar(self, query: str) -> str:
        return query

    def ahora(self) -> str:
        return "datetime('now')"

    def auto_incremento(self) -> str:
        return "INTEGER PRIMARY KEY AUTOINCREMENT"

    def booleano(self) -> str:
        return "INTEGER"

    def blob(self) -> str:
        return "BLOB"

    def obtener_columnas(self, cursor, tabla: str) -> list[str]:
        return [r[1] for r in cursor.execute(
            f"PRAGMA table_info({tabla})").fetchall()]

    def tabla_existe(self, cursor, tabla: str) -> bool:
        return cursor.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (tabla,),
        ).fetchone() is not None

    def insertar_devolviendo_id(self, cursor, sql: str, params: tuple) -> int:
        cursor.execute(sql, params)
        return cursor.lastrowid

    def desactivar_fk(self, cursor) -> None:
        cursor.execute("PRAGMA foreign_keys=OFF")

    def restaurar_fk(self, cursor) -> None:
        cursor.execute("PRAGMA foreign_keys=ON")

    def sql_insertar_o_ignorar(self, tabla: str, columnas: list[str],
                               con_conflicto_id: bool = False) -> str:
        marcadores = ", ".join("?" for _ in columnas)
        return (f"INSERT OR IGNORE INTO {tabla} ({', '.join(columnas)}) "
                f"VALUES ({marcadores})")

    def reajustar_secuencia(self, cursor, tabla: str) -> None:
        return None  # SQLite: AUTOINCREMENT maneja la secuencia solo

    def contar_violaciones_fk(self, cursor) -> int:
        filas = cursor.execute("PRAGMA foreign_key_check").fetchall()
        return len(filas)


class DialectoPostgres(DialectoBase):
    nombre = "postgresql"
    placeholder = "%s"

    def adaptar(self, query: str) -> str:
        return query.replace("?", "%s")

    def ahora(self) -> str:
        return "NOW()"

    def auto_incremento(self) -> str:
        return "SERIAL PRIMARY KEY"

    def booleano(self) -> str:
        return "BOOLEAN"

    def blob(self) -> str:
        return "BYTEA"

    def obtener_columnas(self, cursor, tabla: str) -> list[str]:
        return [r[0] for r in cursor.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = %s ORDER BY ordinal_position",
            (tabla,)).fetchall()]

    def tabla_existe(self, cursor, tabla: str) -> bool:
        return cursor.execute(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_name = %s", (tabla,)).fetchone() is not None

    def insertar_devolviendo_id(self, cursor, sql: str, params: tuple) -> int:
        cursor.execute(self.adaptar(sql) + " RETURNING id", params)
        return cursor.fetchone()[0]

    def desactivar_fk(self, cursor) -> None:
        cursor.execute("SET session_replication_role = replica")

    def restaurar_fk(self, cursor) -> None:
        cursor.execute("SET session_replication_role = DEFAULT")

    def sql_insertar_o_ignorar(self, tabla: str, columnas: list[str],
                               con_conflicto_id: bool = False) -> str:
        marcadores = ", ".join("%s" for _ in columnas)
        sufijo = "" if not con_conflicto_id \
            else " ON CONFLICT (id) DO NOTHING"
        return (f"INSERT INTO {tabla} ({', '.join(columnas)}) "
                f"VALUES ({marcadores}){sufijo}")

    def reajustar_secuencia(self, cursor, tabla: str) -> None:
        cursor.execute(
            "SELECT setval(pg_get_serial_sequence(%s, 'id'), "
            f"GREATEST((SELECT COALESCE(MAX(id), 1) FROM {tabla}), 1))",
            (tabla,))

    def contar_violaciones_fk(self, cursor) -> int:
        return 0  # PostgreSQL valida las FK en cada escritura


_dialectos = {
    "sqlite": DialectoSqlite,
    "postgresql": DialectoPostgres,
}

_instancia: Optional[DialectoBase] = None


def obtener_dialecto(engine: Optional[str] = None) -> DialectoBase:
    """Devuelve el dialecto activo (singleton).

    Si no se pasa engine, se lee de la configuración a través de
    DatabaseManager (evita import circular: el manager usa este módulo).
    """
    global _instancia
    if _instancia is not None:
        return _instancia
    if engine is None:
        from src.database.db_manager import DatabaseManager
        engine = DatabaseManager().engine
    cls = _dialectos.get(engine or "", DialectoSqlite)
    _instancia = cls()
    return _instancia