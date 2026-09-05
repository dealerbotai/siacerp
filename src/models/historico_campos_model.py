from datetime import datetime, timedelta

from src.database.db_manager import DatabaseManager


# Última marca emitida en este proceso: garantiza que `registrar` produzca
# marcas estrictamente crecientes aunque varias capturas caigan en el mismo
# tic del reloj (datetime.now() tiene resolucion de microsegundos o menor),
# de modo que el orden "del más reciente al más antiguo" sea determinista
# (sin depender del desempate por id de la consulta).
_ultima_marca: str = ""


def _marca_uso() -> str:
    """Marca de tiempo de uso, estrictamente creciente dentro del proceso."""
    global _ultima_marca
    ahora = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
    if _ultima_marca and ahora <= _ultima_marca:
        base = datetime.strptime(_ultima_marca, "%Y-%m-%d %H:%M:%S.%f")
        ahora = (base + timedelta(microseconds=1)
                 ).strftime("%Y-%m-%d %H:%M:%S.%f")
    _ultima_marca = ahora
    return ahora


class HistoricoCamposModel:
    """Histórico de capturas por campo de texto.

    Guarda los valores capturados en cada campo (identificado por su clave,
    normalmente la etiqueta o el placeholder) para que el campo vuelva a
    ofrecerlos como selector/autocompletado en capturas posteriores.
    """

    def __init__(self) -> None:
        self.db = DatabaseManager()

    def registrar(self, campo: str, valor: str) -> None:
        """Registra un valor capturado en un campo (o refresca su fecha)."""
        valor = (valor or "").strip()
        if not campo or not valor or len(valor) > 200:
            return
        ahora = _marca_uso()
        self.db.execute(
            "INSERT INTO historico_campos (campo, valor, updated_at) "
            "VALUES (?, ?, ?) "
            "ON CONFLICT(campo, valor) "
            "DO UPDATE SET updated_at = excluded.updated_at",
            (campo, valor, ahora),
        )

    def listar_por_campo(self, campo: str, limite: int = 50) -> list[dict]:
        """Devuelve los valores históricos de un campo, del más reciente al más antiguo."""
        return self.db.fetch_all(
            "SELECT valor FROM historico_campos WHERE campo = ? "
            "ORDER BY updated_at DESC, id DESC LIMIT ?",
            (campo, limite),
        )

    def borrar(self, campo: str, valor: str | None = None) -> None:
        """Borra el histórico de un campo, o solo un valor concreto."""
        if valor is None:
            self.db.execute("DELETE FROM historico_campos WHERE campo = ?", (campo,))
        else:
            self.db.execute(
                "DELETE FROM historico_campos WHERE campo = ? AND valor = ?",
                (campo, valor),
            )