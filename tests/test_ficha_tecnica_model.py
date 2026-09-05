import sqlite3

import pytest

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")


class _BDTemporal:
    """Mini DatabaseManager sobre una BD sqlite temporal (mismos métodos).

    Esquema equivalente al real de _migrar_fichas_tecnicas: fichas_tecnicas
    con modelo_id como PK y columnas de caracteristica, mas la tabla de
    fotos ficha_tecnica_fotos.
    """

    def __init__(self, path: str) -> None:
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        cur = self.conn.cursor()
        cur.execute(
            "CREATE TABLE modelos (id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "codigo TEXT NOT NULL UNIQUE, nombre TEXT NOT NULL, "
            "descripcion TEXT, imagen BLOB, activo INTEGER NOT NULL DEFAULT 1, "
            "created_at TEXT DEFAULT (datetime('now')), "
            "updated_at TEXT DEFAULT (datetime('now')))")
        cur.execute(
            "CREATE TABLE fichas_tecnicas ("
            "modelo_id INTEGER PRIMARY KEY REFERENCES modelos(id), "
            "proyecto TEXT NOT NULL DEFAULT '', "
            "etapa TEXT NOT NULL DEFAULT 'MUESTRA', "
            "id_diseno TEXT NOT NULL DEFAULT '', "
            "ref_cliente TEXT NOT NULL DEFAULT '', "
            "color_nombre TEXT NOT NULL DEFAULT '', "
            "cintilla TEXT DEFAULT '', "
            "piel_corte_1 TEXT DEFAULT '', "
            "forro TEXT DEFAULT '', "
            "suela TEXT DEFAULT '', "
            "tacon TEXT DEFAULT '', "
            "comentarios TEXT DEFAULT '', "
            "realizo TEXT DEFAULT '', "
            "recibio TEXT DEFAULT '', "
            "created_at TEXT NOT NULL DEFAULT (datetime('now')), "
            "updated_at TEXT NOT NULL DEFAULT (datetime('now')))")
        cur.execute(
            "CREATE TABLE ficha_tecnica_fotos ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "modelo_id INTEGER NOT NULL REFERENCES modelos(id) "
            "ON DELETE CASCADE, "
            "tipo_foto TEXT NOT NULL CHECK(tipo_foto IN "
            "('producto','tubo','chinela','talon','suela')), "
            "imagen BLOB, "
            "UNIQUE(modelo_id, tipo_foto))")
        self.conn.commit()

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
    from src.models import ficha_tecnica_model as mod_modelo
    bd = _BDTemporal(str(tmp_path / "ficha_tec_test.db"))
    monkeypatch.setattr(mod_modelo, "DatabaseManager", lambda: bd)
    return bd


def _crear_modelo(bd, codigo: str = "GBC-01", nombre: str = "BOTIN CHIMU") -> int:
    bd.execute("INSERT INTO modelos (codigo, nombre) VALUES (?, ?)",
               (codigo, nombre))
    return bd.fetch_one(
        "SELECT id FROM modelos WHERE codigo = ?", (codigo,))["id"]


class TestFichaTecnicaModel:
    def test_guardar_y_obtener_completa(self, bd):
        from src.models.ficha_tecnica_model import FichaTecnicaModel
        modelo_id = _crear_modelo(bd)
        f = FichaTecnicaModel()

        # Insertar ficha nueva con campos de encabezado y caracteristica.
        f.guardar(modelo_id, {
            "proyecto": "P-2026", "etapa": "MUESTRA", "color_nombre": "CAFE",
            "cintilla": "GAMUZA", "piel_corte_1": "PIEL VACA",
            "forro": "CERDO", "suela": "TR", "tacon": "3/4",
            "comentarios": "BORDADO LOGO", "realizo": "MF",
        })

        ficha = f.obtener(modelo_id)
        assert ficha is not None
        assert ficha["modelo_id"] == modelo_id
        assert ficha["proyecto"] == "P-2026"
        assert ficha["color_nombre"] == "CAFE"
        assert ficha["cintilla"] == "GAMUZA"
        assert ficha["piel_corte_1"] == "PIEL VACA"
        assert ficha["forro"] == "CERDO"
        assert ficha["suela"] == "TR"
        assert ficha["tacon"] == "3/4"
        assert ficha["comentarios"] == "BORDADO LOGO"
        assert ficha["realizo"] == "MF"

    def test_guardar_actualiza_en_lugar_de_duplicar(self, bd):
        from src.models.ficha_tecnica_model import FichaTecnicaModel
        modelo_id = _crear_modelo(bd)
        f = FichaTecnicaModel()

        f.guardar(modelo_id, {"proyecto": "P-1", "cintilla": "GAMUZA"})
        f.guardar(modelo_id, {"cintilla": "BECERRINA", "etapa": "CORTE"})

        ficha = f.obtener(modelo_id)
        assert ficha["cintilla"] == "BECERRINA"
        assert ficha["proyecto"] == "P-1"       # el resto no se pisa
        assert ficha["etapa"] == "CORTE"
        # modelo_id es PK: una sola fila por modelo.
        n = bd.fetch_one("SELECT COUNT(*) AS n FROM fichas_tecnicas")["n"]
        assert n == 1

    def test_guardar_ignora_columnas_desconocidas(self, bd):
        from src.models.ficha_tecnica_model import FichaTecnicaModel
        modelo_id = _crear_modelo(bd)
        FichaTecnicaModel().guardar(modelo_id, {
            "cintilla": "OK", "columna_inexistente": "X",
        })
        ficha = FichaTecnicaModel().obtener(modelo_id)
        assert ficha["cintilla"] == "OK"
        assert "columna_inexistente" not in ficha

    def test_obtener_por_modelo_sin_ficha_devuelve_none(self, bd):
        from src.models.ficha_tecnica_model import FichaTecnicaModel
        modelo_id = _crear_modelo(bd)
        assert FichaTecnicaModel().obtener(modelo_id) is None
        assert FichaTecnicaModel().obtener(999) is None

    def test_fotos_guardar_obtener_y_borrar(self, bd):
        from src.models.ficha_tecnica_model import FichaTecnicaModel
        modelo_id = _crear_modelo(bd)
        f = FichaTecnicaModel()

        imagen = b"\x89PNG\r\n\x1a\n"
        f.guardar_foto(modelo_id, "producto", imagen)
        assert f.obtener_foto(modelo_id, "producto") == imagen
        assert f.obtener_foto(modelo_id, "tubo") is None

        # Reemplazo del mismo tipo (UNIQUE modelo_id, tipo_foto).
        otra = b"\xff\xd8\xff\xe0"
        f.guardar_foto(modelo_id, "producto", otra)
        assert f.obtener_foto(modelo_id, "producto") == otra

        # dict de todas las fotos.
        f.guardar_foto(modelo_id, "suela", imagen)
        fotos = f.obtener_fotos(modelo_id)
        assert fotos["producto"] == otra
        assert fotos["suela"] == imagen

        # imagen None borra la foto.
        f.guardar_foto(modelo_id, "producto", None)
        assert f.obtener_foto(modelo_id, "producto") is None
        assert f.obtener_fotos(modelo_id) == {"suela": imagen}

    def test_valores_historicos(self, bd):
        from src.models.ficha_tecnica_model import FichaTecnicaModel
        m1 = _crear_modelo(bd, "GBC-01", "A")
        m2 = _crear_modelo(bd, "GBC-02", "B")
        _crear_modelo(bd, "GBC-03", "C")
        f = FichaTecnicaModel()
        f.guardar(m1, {"cintilla": "GAMUZA"})
        f.guardar(m2, {"cintilla": "BECERRINA"})   # la tercera queda vacia

        assert f.valores_historicos("cintilla") == ["BECERRINA", "GAMUZA"]
        # Columna no perteneciente a la ficha: sin historico.
        assert f.valores_historicos("columna_inventada") == []

    def test_eliminar_no_existe_en_api_actual(self, bd):
        """El borrado de la ficha es responsabilidad del borrado del modelo.

        La API actual no expone eliminar_por_modelo (rediseno de la ficha);
        se verifica que la ficha se puede guardar y releer sin error.
        """
        from src.models.ficha_tecnica_model import FichaTecnicaModel
        modelo_id = _crear_modelo(bd)
        f = FichaTecnicaModel()
        f.guardar(modelo_id, {"suela": "PU"})
        assert f.obtener(modelo_id)["suela"] == "PU"
