"""Cola de sincronización (outbox pattern) para el sistema Offline-First.

Cada cambio local (INSERT, UPDATE, DELETE) se registra en `sync_queue`.
El SyncService envía los registros pendientes a Supabase y los marca
como 'enviado'. Si falla, se reintenta con backoff.

Compatibilidad: SQLite (desarrollo) y PostgreSQL (estación principal).
"""
import json
from datetime import datetime
from typing import Optional

from src.database.db_manager import DatabaseManager


class SyncQueueModel:
    """Encola cambios locales para replicación a Supabase."""

    def __init__(self) -> None:
        self.db = DatabaseManager()

    # ------------------------------------------------------------------
    # Encolar cambios
    # ------------------------------------------------------------------

    def encolar(self, tabla: str, registro_id: int, operacion: str,
                datos: Optional[dict] = None) -> int:
        """Registra un cambio en la cola de sincronización.

        Args:
            tabla: Nombre de la tabla local modificada.
            registro_id: ID del registro afectado.
            operacion: 'INSERT', 'UPDATE' o 'DELETE'.
            datos: Snapshot del registro (requerido para INSERT/UPDATE).

        Returns:
            ID del registro encolado.
        """
        payload = json.dumps(datos, ensure_ascii=False, default=str) if datos else None
        cursor = self.db.execute(
            "INSERT INTO sync_queue (tabla, registro_id, operacion, datos) "
            "VALUES (?, ?, ?, ?)",
            (tabla, registro_id, operacion, payload),
        )
        return cursor.lastrowid

    def encolar_insert(self, tabla: str, registro_id: int, datos: dict) -> int:
        """Atajo para encolar un INSERT."""
        return self.encolar(tabla, registro_id, 'INSERT', datos)

    def encolar_update(self, tabla: str, registro_id: int, datos: dict) -> int:
        """Atajo para encolar un UPDATE."""
        return self.encolar(tabla, registro_id, 'UPDATE', datos)

    def encolar_delete(self, tabla: str, registro_id: int,
                       datos: Optional[dict] = None) -> int:
        """Atajo para encolar un DELETE (soft delete).

        datos: opcional; si se pasa (p. ej. {"uuid": ...}) se guarda como
        snapshot para que el SyncService sepa qué registro borrar en el
        remoto cuando la identidad local (id) no sea confiable entre
        terminales.
        """
        return self.encolar(tabla, registro_id, 'DELETE', datos)

    # ------------------------------------------------------------------
    # Leer la cola
    # ------------------------------------------------------------------

    def pendientes(self, limite: int = 100) -> list[dict]:
        """Devuelve los registros pendientes de envío, ordenados por fecha."""
        return self.db.fetch_all(
            "SELECT * FROM sync_queue "
            "WHERE estatus = 'pendiente' "
            "ORDER BY created_at ASC LIMIT ?",
            (limite,),
        )

    def contar_pendientes(self) -> int:
        """Cuenta los registros pendientes."""
        row = self.db.fetch_one(
            "SELECT COUNT(*) AS n FROM sync_queue WHERE estatus = 'pendiente'"
        )
        return int(row["n"]) if row else 0

    # ------------------------------------------------------------------
    # Marcar como enviado / error
    # ------------------------------------------------------------------

    def marcar_enviado(self, sync_id: int) -> None:
        """Marca un registro como enviado exitosamente."""
        self.db.execute(
            "UPDATE sync_queue SET estatus = 'enviado', "
            "enviado_en = datetime('now') WHERE id = ?",
            (sync_id,),
        )

    def marcar_error(self, sync_id: int, error: str) -> None:
        """Marca un registro como error y incrementa el contador de intentos."""
        self.db.execute(
            "UPDATE sync_queue SET estatus = 'error', "
            "intentos = intentos + 1, ultimo_error = ? WHERE id = ?",
            (error, sync_id),
        )

    def reintento_pendientes(self, max_intentos: int = 3) -> list[dict]:
        """Devuelve registros con error que aún pueden reintentarse."""
        return self.db.fetch_all(
            "SELECT * FROM sync_queue "
            "WHERE estatus = 'error' AND intentos < ? "
            "ORDER BY created_at ASC LIMIT 50",
            (max_intentos,),
        )

    def limpiar_enviados(self, dias: int = 7) -> int:
        """Elimina registros enviados hace más de *dias* días."""
        cursor = self.db.execute(
            "DELETE FROM sync_queue "
            "WHERE estatus = 'enviado' "
            "AND enviado_en < datetime('now', ?)",
            (f"-{dias} days",),
        )
        return cursor.rowcount

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def snapshot_registro(self, tabla: str, registro_id: int) -> Optional[dict]:
        """Obtiene el estado actual de un registro para enviarlo."""
        return self.db.fetch_one(
            f"SELECT * FROM {tabla} WHERE id = ?", (registro_id,)
        )
