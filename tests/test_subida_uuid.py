"""Pruebas del camino RPC de subida por uuid (fase 2, RD-9).

Cubre:
  1. SupabaseService.llamar_rpc: forma el POST /rest/v1/rpc/<nombre> con la
     autenticacion correcta y mapea respuesta/error (incluido HTTP 404).
  2. SupabaseService.subir_registro_por_uuid: delega en subir_registro_sync
     con p_tabla/p_datos.
  3. SyncService._enviar_registro: con bandera activa usa el RPC con el
     snapshot vivo (uuid garantizado); cae al REST historico si el RPC no
     esta desplegado (404); lanza RuntimeError ante otros fallos del RPC; y
     sin bandera conserva el camino REST.

No tocan BD real ni red: urllib.request.urlopen se sustituye por un fake.
"""
import json

import pytest

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")


# ----------------------------------------------------------------------
# Fakes de red
# ----------------------------------------------------------------------

class _RespuestaFake:
    def __init__(self, cuerpo: str = ''):
        self._cuerpo = cuerpo

    def read(self):
        return self._cuerpo.encode()


class _ErrorHttpFake(Exception):
    def __init__(self, codigo: int, cuerpo: str = ''):
        super().__init__(codigo)
        self.code = codigo
        self._cuerpo = cuerpo

    def read(self):
        return self._cuerpo.encode()


class _UrlopenFake:
    """Registra la ultima peticion y devuelve lo configurado."""

    def __init__(self):
        self.peticiones = []
        self.resultado = _RespuestaFake('')
        self.error = None

    def __call__(self, req, timeout=15):
        self.peticiones.append(req)
        if self.error is not None:
            raise self.error
        return self.resultado


def _servicio_supabase() -> object:
    """SupabaseService real (sin __init__) ya 'configurado'."""
    from src.utils.supabase_service import SupabaseService
    svc = object.__new__(SupabaseService)
    svc._initialized = True
    svc.url = 'https://prueba.supabase.co'
    svc.anon_key = 'anon-fake'
    svc.empresa_id = 'emp-1'
    svc._token = 'token-sesion'
    svc._usuario_id = 'user-1'
    svc._conectado = True
    return svc


# ----------------------------------------------------------------------
# 1 y 2. SupabaseService.llamar_rpc / subir_registro_por_uuid
# ----------------------------------------------------------------------

class TestLlamarRpc:
    def test_forma_post_correcto(self, monkeypatch, tmp_path):
        import configparser
        urlopen = _UrlopenFake()
        urlopen.resultado = _RespuestaFake(
            json.dumps({"ok": True, "accion": "actualizado", "id": 7}))
        monkeypatch.setattr(
            "src.utils.supabase_service.urllib.request.urlopen", urlopen)
        # Sin service_role en config: usa el token de sesion.
        monkeypatch.setattr(
            "src.utils.supabase_service.urllib.request.urlopen", urlopen)
        svc = _servicio_supabase()
        monkeypatch.setattr(svc, "_leer_config",
                            lambda: configparser.ConfigParser())

        res = svc.llamar_rpc("subir_registro_sync",
                             {"p_tabla": "insumos_movil",
                              "p_datos": {"id": 1}})

        assert res == {"ok": True, "respuesta": {
            "ok": True, "accion": "actualizado", "id": 7}}
        req = urlopen.peticiones[0]
        assert req.full_url == (
            "https://prueba.supabase.co/rest/v1/rpc/subir_registro_sync")
        assert req.method == "POST"
        assert req.headers["Authorization"] == "Bearer token-sesion"
        assert json.loads(req.data.decode()) == {
            "p_tabla": "insumos_movil", "p_datos": {"id": 1}}

    def test_error_404_se_reporta(self, monkeypatch):
        import configparser
        urlopen = _UrlopenFake()
        urlopen.error = _ErrorHttpFake(404, "funcion inexistente")
        monkeypatch.setattr(
            "src.utils.supabase_service.urllib.request.urlopen", urlopen)
        svc = _servicio_supabase()
        monkeypatch.setattr(svc, "_leer_config",
                            lambda: configparser.ConfigParser())

        res = svc.llamar_rpc("subir_registro_sync", {"p_tabla": "x"})

        assert res["ok"] is False
        assert "404" in res["error"]

    def test_subir_registro_por_uuid_mapea_respuesta(self, monkeypatch):
        import configparser
        urlopen = _UrlopenFake()
        urlopen.resultado = _RespuestaFake(
            json.dumps({"ok": True, "accion": "reubicado", "id": -1}))
        monkeypatch.setattr(
            "src.utils.supabase_service.urllib.request.urlopen", urlopen)
        svc = _servicio_supabase()
        monkeypatch.setattr(svc, "_leer_config",
                            lambda: configparser.ConfigParser())

        res = svc.subir_registro_por_uuid(
            "insumos_movil",
            {"id": 1, "uuid": "U-1", "empresa_id": "emp-1"})

        assert res == {"ok": True, "accion": "reubicado", "id": -1}

    def test_subir_por_uuid_habilitado_lee_config(self, monkeypatch,
                                                 tmp_path):
        import configparser

        cfg = tmp_path / "config.ini"
        cfg.write_text("[sync]\nsubir_por_uuid = 1\n", encoding="utf-8")

        def _leer():
            parser = configparser.ConfigParser()
            parser.read(str(cfg))
            return parser

        svc = _servicio_supabase()
        monkeypatch.setattr(svc, "_leer_config", _leer)
        assert svc.subir_por_uuid_habilitado() is True

        cfg.write_text("[sync]\nsubir_por_uuid = 0\n", encoding="utf-8")
        assert svc.subir_por_uuid_habilitado() is False

        cfg.write_text("[otra]\nx = 1\n", encoding="utf-8")
        assert svc.subir_por_uuid_habilitado() is False


# ----------------------------------------------------------------------
# 3. SyncService._enviar_registro (enrutamiento)
# ----------------------------------------------------------------------

class _SupabaseRegistrador:
    """Fake de SupabaseService que registra las llamadas de subida."""

    def __init__(self, habilitado: bool, rpc_ok=True, rpc_error=""):
        self.habilitado = habilitado
        self.rpc_ok = rpc_ok
        self.rpc_error = rpc_error
        self.empresa_id = "emp-1"
        self.llamadas = []

    def subir_por_uuid_habilitado(self):
        return self.habilitado

    def subir_registro_por_uuid(self, tabla, datos):
        self.llamadas.append(("rpc", tabla, dict(datos)))
        if self.rpc_ok:
            return {"ok": True, "accion": "actualizado", "id": datos.get("id")}
        return {"ok": False, "error": self.rpc_error}

    def sincronizar_tabla(self, tabla, datos):
        self.llamadas.append(("rest", tabla, [dict(d) for d in datos]))
        return {"ok": True, "registros": len(datos)}


class _ColaFake:
    def __init__(self, snapshot):
        self.snapshot = snapshot

    def snapshot_registro(self, tabla, registro_id):
        return self.snapshot


def _sync_service(supabase_fake, snapshot) -> object:
    from src.utils.sync_service import SyncService
    svc = object.__new__(SyncService)
    svc._initialized = True
    svc.supabase = supabase_fake
    svc.queue = _ColaFake(snapshot)
    return svc


class TestEnviarRegistro:
    SNAPSHOT = {
        "id": 3, "uuid": "U-3", "codigo": "INS-3", "nombre": "PIEL",
        "activo": 1, "created_at": "2026-01-01 00:00:00",
        "empresa_id": "emp-1",
    }

    def test_con_bandera_usa_rpc_con_snapshot_vivo(self):
        supabase = _SupabaseRegistrador(habilitado=True)
        svc = _sync_service(supabase, dict(self.SNAPSHOT))

        svc._enviar_registro("insumos", "insumos_movil", 3,
                             {"codigo": "PARCIAL"}, "UPDATE")

        assert len(supabase.llamadas) == 1
        tipo, tabla, datos = supabase.llamadas[0]
        assert tipo == "rpc" and tabla == "insumos_movil"
        # Prioriza el snapshot vivo (uuid presente) sobre el payload parcial.
        assert datos["uuid"] == "U-3"
        assert datos["codigo"] == "INS-3"
        # Los sellos locales no viajan al remoto.
        assert "created_at" not in datos

    def test_sin_snapshot_cae_al_payload_encolado(self):
        supabase = _SupabaseRegistrador(habilitado=True)
        svc = _sync_service(supabase, None)

        svc._enviar_registro("insumos", "insumos_movil", 3,
                             {"uuid": "U-3", "codigo": "INS-3"}, "UPDATE")

        assert supabase.llamadas[0][0] == "rpc"
        assert supabase.llamadas[0][2]["uuid"] == "U-3"

    def test_404_del_rpc_cae_al_rest_historico(self):
        supabase = _SupabaseRegistrador(
            habilitado=True, rpc_ok=False, rpc_error="HTTP 404: no existe")
        svc = _sync_service(supabase, dict(self.SNAPSHOT))

        svc._enviar_registro("insumos", "insumos_movil", 3,
                             {"codigo": "X"}, "UPDATE")

        assert len(supabase.llamadas) == 2
        assert supabase.llamadas[0][0] == "rpc"
        assert supabase.llamadas[1][0] == "rest"

    def test_error_real_del_rpc_lanza_runtimeerror(self):
        supabase = _SupabaseRegistrador(
            habilitado=True, rpc_ok=False, rpc_error="HTTP 400: falta uuid")
        svc = _sync_service(supabase, dict(self.SNAPSHOT))

        with pytest.raises(RuntimeError):
            svc._enviar_registro("insumos", "insumos_movil", 3,
                                 {"codigo": "X"}, "UPDATE")

    def test_sin_bandera_conserva_rest_historico(self):
        supabase = _SupabaseRegistrador(habilitado=False)
        svc = _sync_service(supabase, dict(self.SNAPSHOT))

        svc._enviar_registro("insumos", "insumos_movil", 3,
                             {"uuid": "U-3", "codigo": "INS-3"}, "UPDATE")

        assert len(supabase.llamadas) == 1
        assert supabase.llamadas[0][0] == "rest"
