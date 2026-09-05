"""Hooks de sincronización para encolar cambios en sync_queue.

Uso en models:
    from src.utils.sync_hooks import sync_insert, sync_update, sync_delete

    # Después de un INSERT exitoso:
    sync_insert('insumos', nuevo_id, datos_dict)

    # Después de un UPDATE:
    sync_update('insumos', registro_id, datos_dict)

    # Después de un DELETE / soft delete:
    sync_delete('insumos', registro_id)

Antes de encolar, cada hook garantiza la identidad global del registro:
si la tabla sincronizable tiene columna `uuid` y el registro no la tiene,
se genera un uuid4 y se persiste en la fila local. Ese uuid viaja en el
payload encolado y es la clave de merge en Supabase (evita colisiones
entre terminales de la misma empresa que insertan offline).

Si sync_queue no está disponible (BD antigua o sync deshabilitado),
los hooks fallan silenciosamente para no bloquear la operación local.
"""
import uuid
from typing import Optional

_queue_instance = None


def _get_queue():
    """Obtiene la instancia de SyncQueueModel (lazy)."""
    global _queue_instance
    if _queue_instance is None:
        try:
            from src.models.sync_queue_model import SyncQueueModel
            _queue_instance = SyncQueueModel()
        except Exception:
            return None
    return _queue_instance


def _asegurar_uuid(tabla: str, registro_id: int) -> Optional[str]:
    """Garantiza el uuid del registro local y lo devuelve.

    Si la tabla no tiene columna `uuid` (BD antigua o tabla no preparada),
    devuelve None y la operación continúa sin uuid (compatibilidad).
    """
    try:
        from src.database.db_manager import DatabaseManager
        db = DatabaseManager()
        fila = db.fetch_one(
            f"SELECT uuid FROM {tabla} WHERE id = ?", (registro_id,))
        if fila is None:
            return None
        if fila.get('uuid'):
            return fila['uuid']
        nuevo = str(uuid.uuid4())
        db.execute(
            f"UPDATE {tabla} SET uuid = ? WHERE id = ?", (nuevo, registro_id))
        return nuevo
    except Exception:
        return None


def _con_uuid(tabla: str, registro_id: int, datos: Optional[dict]) -> dict:
    """Devuelve los datos con la identidad global asegurada."""
    payload = dict(datos or {})
    if 'uuid' not in payload:
        valor = _asegurar_uuid(tabla, registro_id)
        if valor:
            payload['uuid'] = valor
    return payload


def sync_insert(tabla: str, registro_id: int, datos: dict) -> None:
    """Encola un INSERT para sincronización."""
    q = _get_queue()
    if q is None:
        return
    try:
        payload = _con_uuid(tabla, registro_id, datos)
        q.encolar_insert(tabla, registro_id, payload)
    except Exception:
        pass  # No bloquear la operación local
    sync_trigger()


def sync_update(tabla: str, registro_id: int, datos: dict) -> None:
    """Encola un UPDATE para sincronización."""
    q = _get_queue()
    if q is None:
        return
    try:
        payload = _con_uuid(tabla, registro_id, datos)
        q.encolar_update(tabla, registro_id, payload)
    except Exception:
        pass
    sync_trigger()


def sync_delete(tabla: str, registro_id: int) -> None:
    """Encola un DELETE (soft delete) para sincronización."""
    q = _get_queue()
    if q is None:
        return
    try:
        # El DELETE remoto se hace por uuid cuando el registro lo tiene.
        valor = _asegurar_uuid(tabla, registro_id)
        payload = {'uuid': valor} if valor else None
        q.encolar_delete(tabla, registro_id, payload)
    except Exception:
        pass
    sync_trigger()


def sync_trigger():
    """Trigger sincronización inmediata si hay red (fire-and-forget)."""
    try:
        from src.utils.sync_service import SyncService
        svc = SyncService()
        if svc.conectado and svc.hay_red():
            import threading
            threading.Thread(
                target=svc.sincronizar_si_hay_red,
                daemon=True
            ).start()
    except Exception:
        pass