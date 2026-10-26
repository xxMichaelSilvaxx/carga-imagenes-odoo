"""Odoo client over the JSON-2 API of Odoo 19, authenticated with an API key (bearer token).

Works with a standard Odoo (no custom module): the protection is whatever the key's user
is allowed to do, so the key must belong to a dedicated user with product rights only.
"""
import http.cookiejar
import re
import threading
import time
from urllib.parse import urlsplit

import requests

from common import fold

RETRY_STATUS = {429, 502, 503, 504}
RETRY_DELAYS = (3, 10, 30)
CONNECT_TIMEOUT = 20
API_KEY_HELP = ("En Odoo, entre con el usuario de carga de imágenes, abra Mi perfil > Seguridad de la cuenta > "
                "Nueva clave API, copie la clave y péguela aquí.")


class OdooError(Exception):
    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


def normalize_url(text):
    text = (text or "").strip().rstrip("/")
    if not text:
        raise OdooError("Ingrese la URL de Odoo, por ejemplo https://miempresa.odoo.com")
    if "://" not in text:
        text = "https://" + text
    parts = urlsplit(text)
    if parts.scheme.lower() not in ("http", "https") or not parts.hostname:
        raise OdooError(f"La URL no es válida: {text}. Use el formato https://miempresa.odoo.com")
    return f"{parts.scheme.lower()}://{parts.netloc.lower()}"


def is_local(url):
    return urlsplit(url).hostname in ("localhost", "127.0.0.1", "::1")


class OdooClient:
    def __init__(self, url, database, login, api_key, timeout=180):
        self.url = normalize_url(url)
        self.database = (database or "").strip()
        self.login = (login or "").strip()
        self.api_key = (api_key or "").strip()
        self.timeout = timeout
        self.version = ""
        self.major = 0
        self.info = {}
        self.service = ProductImageService(self)
        self._local = threading.local()

    def _session(self):
        session = getattr(self._local, "session", None)
        if session is None:
            session = requests.Session()
            # Stateless calls: a session cookie would clash with the X-Odoo-Database header
            session.cookies.set_policy(http.cookiejar.DefaultCookiePolicy(allowed_domains=[]))
            session.headers["User-Agent"] = "CargaImagenesOdoo/2.0"
            self._local.session = session
        return session

    def _send(self, method, path, retry=True, **kwargs):
        timeout = (CONNECT_TIMEOUT, self.timeout if retry else CONNECT_TIMEOUT * 2)
        delays = RETRY_DELAYS if retry else ()
        response, failure = None, None
        for attempt in range(len(delays) + 1):
            if attempt:
                time.sleep(delays[attempt - 1])
            try:
                response = self._session().request(method, self.url + path, timeout=timeout, **kwargs)
                failure = None
            except requests.exceptions.SSLError as error:
                raise OdooError(
                    f"No se pudo verificar el certificado de seguridad (HTTPS) de {self.url}. "
                    "Revise que la URL sea la correcta y que la fecha y hora del equipo estén bien."
                ) from error
            except requests.Timeout:
                response, failure = None, OdooError(f"El servidor {self.url} no respondió a tiempo.")
                continue
            except requests.ConnectionError:
                response, failure = None, OdooError(
                    f"No se pudo conectar con {self.url}. Revise la URL y la conexión a internet.")
                continue
            if response.status_code not in RETRY_STATUS:
                return response
        if failure:
            raise failure
        if response.status_code == 429:
            raise OdooError("El servidor está limitando las solicitudes (demasiadas a la vez). "
                            "Baje las subidas simultáneas y reintente.", 429)
        raise OdooError(f"El servidor no está disponible en este momento (HTTP {response.status_code}). "
                        "Reintente en unos minutos.", response.status_code)

    def _error(self, data, status):
        name = str(data.get("name") or "")
        message = str(data.get("message") or "").strip()
        if status == 401:
            return OdooError("La clave API no es válida, fue revocada o ya venció. " + API_KEY_HELP, status)
        # Odoo answers plain HTML (no JSON body) when it cannot pick or open the database
        if status == 404 and not data and not self.database:
            return OdooError("El servidor tiene varias bases de datos: escriba el nombre de la base.", status)
        if status in (404, 500) and not data and self.database:
            return OdooError(f"No existe la base de datos '{self.database}' en el servidor. Revise el nombre.", status)
        if name.endswith("AccessError") or status == 403:
            return OdooError(f"El usuario de la clave API no tiene permiso para esta operación. Detalle: {message}", status)
        if status == 413:
            return OdooError("El archivo es demasiado grande para el servidor.", status)
        return OdooError(message or f"Error del servidor (HTTP {status}).", status)

    def check_server(self):
        if self.url.startswith("http://") and not is_local(self.url):
            raise OdooError("Por seguridad solo se permiten direcciones https://. Odoo.sh siempre usa https.")
        response = self._send("GET", "/web/version", retry=False, allow_redirects=True)
        final = normalize_url(response.url)
        if self.url.startswith("https://") and final.startswith("http://"):
            raise OdooError("El servidor redirige a una conexión sin cifrar (http). Por seguridad no se continúa.")
        self.url = final
        try:
            info = response.json() if response.status_code == 200 else None
        except ValueError:
            info = None
        if not isinstance(info, dict) or "version" not in info:
            raise OdooError(f"La dirección {self.url} no corresponde a un servidor Odoo.")
        self.version = str(info["version"])
        found = re.search(r"\d+", str((info.get("version_info") or [self.version])[0]))
        self.major = int(found.group()) if found else 0
        if self.major < 19:
            raise OdooError(f"El servidor tiene Odoo {self.version}; el aplicativo requiere Odoo 19 o superior.")

    def rpc(self, model, method, ids=None, context=None, retry=True, **kwargs):
        headers = {"Authorization": f"bearer {self.api_key}"}
        if self.database:
            headers["X-Odoo-Database"] = self.database
        body = dict(kwargs)
        if ids is not None:
            body["ids"] = list(ids)
        if context:
            body["context"] = context
        response = self._send("POST", f"/json/2/{model}/{method}", retry=retry, json=body, headers=headers)
        try:
            data = response.json()
        except ValueError:
            data = None
        if response.status_code == 200:
            return data
        raise self._error(data if isinstance(data, dict) else {}, response.status_code)

    def call(self, method, **kwargs):
        return getattr(self.service, method)(**kwargs)

    def connect(self):
        if not self.api_key:
            raise OdooError("Ingrese la clave API. " + API_KEY_HELP)
        self.check_server()
        self.info = self.call("get_session_info")
        if self.login and fold(self.info["login"]) != fold(self.login):
            raise OdooError(f"La clave API pertenece al usuario '{self.info['login']}', no a '{self.login}'.")
        self.database = self.info.get("database") or self.database
        return self.describe()

    def describe(self):
        security = "HTTPS cifrado" if self.url.startswith("https://") else "SIN cifrar (equipo local)"
        return (f"{self.info.get('name')} ({self.info.get('login')}) | Odoo {self.version} | "
                f"base {self.database or 'única'} | {security}")

    def warnings(self):
        if self.info.get("is_admin"):
            return ["La clave API es de un ADMINISTRADOR: si se filtra, permite cambiar cualquier dato de Odoo. "
                    "Use un usuario dedicado que solo tenga el permiso Productos: Crear."]
        return []


class ProductImageService:
    """Catalog reading and image writing with standard Odoo methods (no custom module needed)."""

    PAGE_SIZE = 5000
    MAX_PER_CALL = 100

    def __init__(self, client):
        self.client = client
        self.context = {}

    def get_session_info(self):
        rpc = self.client.rpc
        # Record rules show a regular user only its own keys; only administrators see other users' keys
        keys = rpc("res.users.apikeys", "search_read", domain=[], fields=["user_id"])
        owners = {row["user_id"][0] for row in keys}
        if len(owners) == 1:
            owner_id = owners.pop()
        else:
            if not self.client.login:
                raise OdooError("Escriba el usuario (correo) dueño de la clave API.")
            found = rpc("res.users", "search", domain=[("login", "=ilike", self.client.login)])
            if not found or found[0] not in owners:
                raise OdooError(f"La clave API no pertenece al usuario '{self.client.login}'.")
            owner_id = found[0]
        user = rpc("res.users", "read", ids=[owner_id], fields=["login", "name", "company_ids"])[0]
        self.context = {"allowed_company_ids": user["company_ids"]}
        if not rpc("product.template", "has_access", ids=[], operation="write", context=self.context):
            raise OdooError(f"El usuario '{user['login']}' no tiene permiso para modificar productos en Odoo. "
                            "Asígnele el permiso Productos: Crear.")
        return {
            "login": user["login"],
            "name": user["name"],
            "database": self.client.database,
            "is_admin": rpc("res.users", "has_group", ids=[owner_id], group_ext_id="base.group_system"),
            "max_image_mb": 20,
            "max_products_per_image": self.MAX_PER_CALL,
            "page_size": self.PAGE_SIZE,
        }

    def _templates_with_image(self, template_ids):
        return self.client.rpc("product.template", "search",
                               domain=[("id", "in", template_ids), ("image_1920", "!=", False)],
                               context=dict(self.context, active_test=False))

    def get_catalog(self, offset=0):
        rpc = self.client.rpc
        variants = rpc("product.product", "search_read", domain=[("default_code", "!=", False)],
                       fields=["default_code", "product_tmpl_id"], offset=offset, limit=self.PAGE_SIZE,
                       order="id", context=self.context)
        template_ids = sorted({row["product_tmpl_id"][0] for row in variants})
        names = {row["id"]: row["name"] for row in
                 rpc("product.template", "read", ids=template_ids, fields=["name"], context=self.context)}
        with_image = set(self._templates_with_image(template_ids))
        return [[row["default_code"], row["product_tmpl_id"][0], names.get(row["product_tmpl_id"][0], ""),
                 row["product_tmpl_id"][0] in with_image] for row in variants]

    def set_image(self, template_ids, image):
        rpc = self.client.rpc
        found = rpc("product.template", "search", domain=[("id", "in", template_ids)], context=self.context)
        missing = set(template_ids) - set(found)
        if missing:
            raise OdooError(f"Estos productos no existen o no están permitidos: {sorted(missing)}")
        replaced = self._templates_with_image(found)
        rpc("product.template", "write", ids=found, vals={"image_1920": image}, context=self.context)
        return {"replaced": replaced, "added": [tid for tid in found if tid not in replaced]}
