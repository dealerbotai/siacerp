import configparser
import json
import urllib.request
from pathlib import Path
from typing import Any, Optional


class SupabaseService:
    """Servicio de conexion a Supabase para el escritorio SIAC ERP.

    Permite:
    - Autenticar usuarios via Supabase Auth
    - Leer/escribir datos en Supabase
    - Sincronizar datos locales con Supabase
    - Validar licenciamiento por empresa
    """

    _instance: Optional['SupabaseService'] = None

    def __new__(cls) -> 'SupabaseService':
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        if hasattr(self, '_initialized'):
            return
        self._initialized = True
        self.url: str = ''
        self.anon_key: str = ''
        self.empresa_id: str = ''
        self._token: str = ''
        self._usuario_id: str = ''
        self._conectado = False
        self._cargar_config()

    def _cargar_config(self) -> None:
        """Carga configuracion de Supabase desde config.ini."""
        config = configparser.ConfigParser()
        ruta = Path(__file__).resolve().parent.parent.parent / 'config.ini'
        if not ruta.exists():
            return
        config.read(str(ruta))
        if config.has_section('supabase'):
            self.url = config.get('supabase', 'url', fallback='')
            self.anon_key = config.get('supabase', 'anon_key', fallback='')
            self.empresa_id = config.get('supabase', 'empresa_id', fallback='')

    @property
    def configurado(self) -> bool:
        return bool(self.url and self.anon_key and self.empresa_id)

    @property
    def autenticado(self) -> bool:
        return bool(self._token and self._usuario_id)

    def login(self, email: str, password: str) -> dict:
        """Inicia sesion con email/password via Supabase Auth.

        Returns:
            {'ok': True, 'usuario': {...}} o {'ok': False, 'error': '...'}
        """
        if not self.configurado:
            return {'ok': False, 'error': 'Supabase no configurado'}

        try:
            req = urllib.request.Request(
                f'{self.url}/auth/v1/token?grant_type=password',
                data=json.dumps({
                    'email': email,
                    'password': password
                }).encode(),
                headers={
                    'apikey': self.anon_key,
                    'Content-Type': 'application/json'
                }
            )
            resp = urllib.request.urlopen(req, timeout=10)
            data = json.loads(resp.read().decode())

            self._token = data['access_token']
            self._usuario_id = data['user']['id']

            # Obtener perfil con empresa_id
            perfil = self._api_call(
                f'/rest/v1/perfiles_usuario?select=*&id=eq.{self._usuario_id}'
            )
            if perfil and len(perfil) > 0:
                p = perfil[0]
                if not p.get('activo', True):
                    return {'ok': False, 'error': 'Usuario desactivado'}

                # Verificar que la empresa del usuario coincida con la configurada
                # Super_admin puede no tener empresa_id (acceso total)
                if p.get('rol') != 'super_admin':
                    if p.get('empresa_id') and p['empresa_id'] != self.empresa_id:
                        return {
                            'ok': False,
                            'error': 'Este usuario no pertenece a esta empresa'
                        }

                self._conectado = True
                return {
                    'ok': True,
                    'usuario': {
                        'id': p['id'],
                        'username': p['username'],
                        'nombre_completo': p['nombre_completo'],
                        'rol': p['rol'],
                        'empresa_id': p['empresa_id']
                    }
                }
            else:
                return {'ok': False, 'error': 'Perfil no encontrado'}

        except urllib.error.HTTPError as e:
            body = e.read().decode()
            if 'Invalid login' in body or 'invalid_grant' in body:
                return {'ok': False, 'error': 'Credenciales incorrectas'}
            return {'ok': False, 'error': f'Error de conexion: {e.code}'}
        except Exception as e:
            return {'ok': False, 'error': str(e)}

    def logout(self) -> None:
        """Cierra sesion."""
        self._token = ''
        self._usuario_id = ''
        self._conectado = False

    def _api_call(self, endpoint: str, method: str = 'GET',
                  data: dict = None) -> Any:
        """Realiza una llamada a la API de Supabase."""
        url = f'{self.url}{endpoint}'
        headers = {
            'apikey': self.anon_key,
            'Content-Type': 'application/json'
        }
        if self._token:
            headers['Authorization'] = f'Bearer {self._token}'

        # Para PATCH/POST, pedir que retorne los datos actualizados
        if method in ('PATCH', 'POST'):
            headers['Prefer'] = 'return=representation'

        body = json.dumps(data).encode() if data else None
        req = urllib.request.Request(url, data=body, headers=headers, method=method)
        resp = urllib.request.urlopen(req, timeout=15)
        respuesta = resp.read().decode()
        if not respuesta.strip():
            return []
        return json.loads(respuesta)

    def service_call(self, endpoint: str, method: str = 'GET',
                     data: dict = None) -> Any:
        """Realiza una llamada usando la service_role key (bypass RLS)."""
        config = configparser.ConfigParser()
        ruta = Path(__file__).resolve().parent.parent.parent / 'config.ini'
        config.read(str(ruta))
        service_key = config.get('supabase', 'service_role_key', fallback='')

        if not service_key:
            # Fallback a anon key
            return self._api_call(endpoint, method, data)

        url = f'{self.url}{endpoint}'
        headers = {
            'apikey': self.anon_key,
            'Authorization': f'Bearer {service_key}',
            'Content-Type': 'application/json'
        }
        # Para PATCH/POST, pedir que retorne los datos actualizados
        if method in ('PATCH', 'POST'):
            headers['Prefer'] = 'return=representation'

        body = json.dumps(data).encode() if data else None
        req = urllib.request.Request(url, data=body, headers=headers, method=method)
        resp = urllib.request.urlopen(req, timeout=15)
        respuesta = resp.read().decode()
        if not respuesta.strip():
            return []
        return json.loads(respuesta)

    def verificar_licencia(self) -> dict:
        """Verifica que la empresa tenga licencia activa en Supabase.

        Returns:
            {'ok': True, 'empresa': {...}} o {'ok': False, 'error': '...'}
        """
        if not self.configurado:
            return {'ok': False, 'error': 'Supabase no configurado'}

        try:
            empresas = self.service_call(
                f'/rest/v1/empresas?select=*&id=eq.{self.empresa_id}'
            )
            if empresas and len(empresas) > 0:
                emp = empresas[0]
                if emp.get('activo', True):
                    return {'ok': True, 'empresa': emp}
                else:
                    return {'ok': False, 'error': 'Empresa desactivada'}
            else:
                return {'ok': False, 'error': 'Empresa no encontrada'}
        except Exception as e:
            return {'ok': False, 'error': str(e)}

    def listar_usuarios_empresa(self) -> list[dict]:
        """Lista los usuarios de la empresa actual."""
        if not self.configurado:
            return []
        try:
            return self.service_call(
                f'/rest/v1/perfiles_usuario?select=id,username,nombre_completo,rol,activo&empresa_id=eq.{self.empresa_id}'
            )
        except Exception:
            return []

    def sincronizar_tabla(self, tabla: str, datos: list[dict]) -> dict:
        """Sincroniza datos de una tabla local a Supabase.

        Usa service_role_key (bypass RLS) si esta disponible,
        o el token de sesion del usuario autenticado.

        Args:
            tabla: Nombre de la tabla en Supabase (con sufijo _movil si aplica)
            datos: Lista de registros a sincronizar

        Returns:
            {'ok': True, 'registros': N} o {'ok': False, 'error': '...'}
        """
        if not self.configurado:
            return {'ok': False, 'error': 'Supabase no configurado'}

        try:
            # Agregar empresa_id a cada registro
            for registro in datos:
                registro['empresa_id'] = self.empresa_id

            # Usar service_role si hay, si no token de sesion
            config = configparser.ConfigParser()
            ruta = Path(__file__).resolve().parent.parent.parent / 'config.ini'
            config.read(str(ruta))
            service_key = config.get('supabase', 'service_role_key', fallback='')

            if service_key:
                auth_token = service_key
            elif self._token:
                auth_token = self._token
            else:
                return {'ok': False, 'error': 'No autenticado (ni service_role ni sesion)'}

            # Upsert en Supabase
            req = urllib.request.Request(
                f'{self.url}/rest/v1/{tabla}',
                data=json.dumps(datos).encode(),
                headers={
                    'apikey': self.anon_key,
                    'Authorization': f'Bearer {auth_token}',
                    'Content-Type': 'application/json',
                    'Prefer': 'resolution=merge-duplicates'
                },
                method='POST'
            )
            urllib.request.urlopen(req, timeout=30)
            return {'ok': True, 'registros': len(datos)}

        except urllib.error.HTTPError as e:
            body = e.read().decode()
            return {'ok': False, 'error': f'HTTP {e.code}: {body[:200]}'}
        except Exception as e:
            return {'ok': False, 'error': str(e)}

    # ------------------------------------------------------------------
    # RPC (fase 2 RD-9): subida por uuid
    # ------------------------------------------------------------------

    def _leer_config(self) -> configparser.ConfigParser:
        """Lee config.ini (raiz del proyecto / junto al .exe)."""
        config = configparser.ConfigParser()
        ruta = Path(__file__).resolve().parent.parent.parent / 'config.ini'
        config.read(str(ruta))
        return config

    def subir_por_uuid_habilitado(self) -> bool:
        """Indica si la subida usa el RPC por uuid (config [sync]).

        La bandera se enciende SOLO cuando la funcion remota
        `subir_registro_sync` (006_subir_por_uuid.sql) ya esta desplegada.
        Por defecto apagada: el camino REST historico sigue siendo el
        predeterminado.
        """
        valor = self._leer_config().get('sync', 'subir_por_uuid',
                                        fallback='0')
        return valor.strip().lower() in ('1', 'true', 'si', 'yes')

    def _token_servicio(self) -> str:
        """Token para escrituras: service_role si existe, si no el de sesion."""
        service_key = self._leer_config().get(
            'supabase', 'service_role_key', fallback='')
        return service_key or self._token

    def llamar_rpc(self, nombre: str, parametros: dict) -> dict:
        """Invoca una funcion RPC de Supabase (PostgREST /rpc/<nombre>).

        Returns:
            {'ok': True, 'respuesta': <json>} o
            {'ok': False, 'error': '...'}
        """
        if not self.configurado:
            return {'ok': False, 'error': 'Supabase no configurado'}
        try:
            auth_token = self._token_servicio()
            if not auth_token:
                return {'ok': False,
                        'error': 'No autenticado (ni service_role ni sesion)'}
            req = urllib.request.Request(
                f'{self.url}/rest/v1/rpc/{nombre}',
                data=json.dumps(parametros).encode(),
                headers={
                    'apikey': self.anon_key,
                    'Authorization': f'Bearer {auth_token}',
                    'Content-Type': 'application/json',
                    'Prefer': 'return=representation',
                },
                method='POST',
            )
            resp = urllib.request.urlopen(req, timeout=30)
            texto = resp.read().decode()
            if not texto.strip():
                return {'ok': True, 'respuesta': None}
            return {'ok': True, 'respuesta': json.loads(texto)}
        except urllib.error.HTTPError as e:
            cuerpo = e.read().decode()
            return {'ok': False, 'error': f'HTTP {e.code}: {cuerpo[:200]}'}
        except Exception as e:
            return {'ok': False, 'error': str(e)}

    def subir_registro_por_uuid(self, tabla: str, datos: dict) -> dict:
        """Sube UN registro por identidad uuid via `subir_registro_sync`.

        La funcion remota decide: actualizar por uuid, insertar, adoptar
        legados, converger o reubicar en id negativo (ver 006).

        Returns:
            {'ok': True, 'accion': ..., 'id': ...} o {'ok': False, 'error'}
        """
        resultado = self.llamar_rpc('subir_registro_sync', {
            'p_tabla': tabla,
            'p_datos': datos,
        })
        if not resultado.get('ok'):
            return resultado
        respuesta = resultado.get('respuesta') or {}
        return {'ok': True, **respuesta}

    def obtener_tabla(self, tabla: str, filtros: str = '') -> list[dict]:
        """Obtiene datos de una tabla en Supabase.

        Args:
            tabla: Nombre de la tabla en Supabase
            filtros: Filtros adicionales (ej: '&estatus=eq.pendiente')

        Returns:
            Lista de registros
        """
        if not self.configurado or not self.autenticado:
            return []

        try:
            endpoint = f'/rest/v1/{tabla}?empresa_id=eq.{self.empresa_id}{filtros}'
            return self._api_call(endpoint)
        except Exception:
            return []
