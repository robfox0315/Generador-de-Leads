"""
LeadForge — Motor de generación de leads verificados (v2, auditado).

Principio de diseño innegociable:
    Ningún dato de contacto se inventa. Todo teléfono, email o nombre procede
    de una fuente real (ficha de Google Maps vía SerpApi o la propia web del
    negocio). Si un dato no existe, el campo queda vacío.

Correcciones de la auditoría v2:
    · Protección SSRF (bloquea IPs privadas y esquemas no HTTP).
    · Respeta robots.txt y aplica pausa de cortesía por dominio.
    · Enriquecimiento web concurrente (mucho más rápido).
    · Caché en disco de respuestas de SerpApi (no se paga dos veces lo mismo).
    · Reintentos con backoff exponencial.
    · Un fallo de consulta no aborta la ejecución completa.
    · Deduplicación por nombre y por teléfono.
    · Tope de presupuesto de búsquedas.
    · Validación de email y detección de cuentas genéricas.
    · Etiquetado honesto del móvil donde no se puede distinguir.
    · Logging estructurado.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import logging
import os
import re
import socket
import tempfile
import threading
import time
import unicodedata
import urllib.robotparser as robotparser
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from typing import Callable, Iterable
from urllib.parse import quote, urljoin, urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# BeautifulSoup solo hace falta para el enriquecimiento web. Si no está instalado,
# la app sigue funcionando: se buscan leads igual y se avisa de la limitación.
try:
    from bs4 import BeautifulSoup
    HTML_PARSER_AVAILABLE = True
except ImportError:  # pragma: no cover
    BeautifulSoup = None  # type: ignore[assignment]
    HTML_PARSER_AVAILABLE = False
    logging.getLogger("leadforge").warning(
        "beautifulsoup4 no está instalado: el enriquecimiento web queda desactivado. "
        "Instálalo con: pip install beautifulsoup4"
    )

logger = logging.getLogger("leadforge")
if not logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(_handler)
logger.setLevel(logging.INFO)

SERPAPI_ENDPOINT = "https://serpapi.com/search.json"
SERPAPI_KEY_LENGTH = 64
REQUEST_TIMEOUT = 10
USER_AGENT = "LeadForgeBot/2.0"
CACHE_TTL_SECONDS = 60 * 60 * 24 * 3
CACHE_DIR = os.path.join(tempfile.gettempdir(), "leadforge_cache")
POLITE_DELAY = 1.0

_domain_lock = threading.Lock()
_domain_last_hit: dict[str, float] = {}
_robots_cache: dict[str, robotparser.RobotFileParser | None] = {}


def build_session(total_retries: int = 3) -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=total_retries,
        backoff_factor=0.6,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET"]),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=20, pool_maxsize=20)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update({"User-Agent": USER_AGENT})
    return session


SESSION = build_session()


# ---------------------------------------------------------------------------
# Países
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Country:
    code: str
    name: str
    dial: str
    national_len: int
    mobile_prefixes: tuple[str, ...]
    mobile_certain: bool = True


COUNTRIES: dict[str, Country] = {
    "es": Country("es", "España", "34", 9, ("6", "7")),
    "mx": Country("mx", "México", "52", 10, (), mobile_certain=False),
    "co": Country("co", "Colombia", "57", 10, ("3",)),
    "ar": Country("ar", "Argentina", "54", 10, ("9", "1")),
    "cl": Country("cl", "Chile", "56", 9, ("9",)),
    "pe": Country("pe", "Perú", "51", 9, ("9",)),
}

ES_PROVINCES = {
    "01": "Álava", "02": "Albacete", "03": "Alicante", "04": "Almería", "05": "Ávila",
    "06": "Badajoz", "07": "Baleares", "08": "Barcelona", "09": "Burgos", "10": "Cáceres",
    "11": "Cádiz", "12": "Castellón", "13": "Ciudad Real", "14": "Córdoba", "15": "A Coruña",
    "16": "Cuenca", "17": "Girona", "18": "Granada", "19": "Guadalajara", "20": "Gipuzkoa",
    "21": "Huelva", "22": "Huesca", "23": "Jaén", "24": "León", "25": "Lleida",
    "26": "La Rioja", "27": "Lugo", "28": "Madrid", "29": "Málaga", "30": "Murcia",
    "31": "Navarra", "32": "Ourense", "33": "Asturias", "34": "Palencia", "35": "Las Palmas",
    "36": "Pontevedra", "37": "Salamanca", "38": "Sta. Cruz de Tenerife", "39": "Cantabria",
    "40": "Segovia", "41": "Sevilla", "42": "Soria", "43": "Tarragona", "44": "Teruel",
    "45": "Toledo", "46": "Valencia", "47": "Valladolid", "48": "Bizkaia", "49": "Zamora",
    "50": "Zaragoza", "51": "Ceuta", "52": "Melilla",
}

EXCLUDE_KEYWORDS = (
    "parque deportivo", "instalacion", "instalaciones", "polideportiv", "piscina municipal",
    "gimnasio", "agility", "sin nombre", "ayuntamiento", "pabell", "ciudad deportiva",
    "centro deportivo", "clinica", "fisio", "tienda", "renta de cancha",
    "material deportivo", "nutricion",
)

SPORT_RULES = (
    (("padel",), "Pádel"),
    (("balonmano", "handbol", "handball"), "Balonmano"),
    (("baloncesto", "basket", "basquet"), "Baloncesto"),
    (("futsal", "futbol sala", "fut 7", "futbol 7"), "Fútbol Sala"),
    (("voley", "voleibol", "volley"), "Voleibol"),
    (("natacion", "swim"), "Natación"),
    (("rugby",), "Rugby"),
    (("tenis de mesa",), "Tenis de mesa"),
    (("tenis",), "Tenis"),
    (("atletismo",), "Atletismo"),
    (("judo", "karate", "taekwondo", "artes marciales"), "Artes marciales"),
    (("hipica", "equitacion"), "Hípica"),
    (("patinaje",), "Patinaje"),
    (("esqui", "ski"), "Esquí"),
    (("futbol", "soccer", " cf", " cd ", " ud ", " sd "), "Fútbol"),
)


def _strip_accents(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", str(text or ""))
                   if not unicodedata.combining(c))


def normalize_key(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", _strip_accents(text).lower())


def classify_sport(*sources: str) -> str:
    blob = _strip_accents(" ".join(str(s or "") for s in sources)).lower()
    for needles, label in SPORT_RULES:
        if any(n in blob for n in needles):
            return label
    return "Multideporte"


def is_target_business(name: str, category: str = "") -> bool:
    blob = _strip_accents(f"{name} {category}").lower()
    return not any(k in blob for k in EXCLUDE_KEYWORDS)


# ---------------------------------------------------------------------------
# Teléfonos
# ---------------------------------------------------------------------------

@dataclass
class Phone:
    raw: str = ""
    e164: str = ""
    national: str = ""
    kind: str = ""

    @property
    def is_mobile(self) -> bool:
        return self.kind.startswith("Móvil")

    @property
    def display(self) -> str:
        return f"+{self.e164}" if self.e164 else ""


def parse_phone(raw: str, country: Country) -> Phone:
    digits = re.sub(r"\D", "", str(raw or ""))
    if not digits:
        return Phone()

    if digits.startswith("00"):
        digits = digits[2:]
    if digits.startswith(country.dial) and len(digits) > country.national_len:
        digits = digits[len(country.dial):]
    if country.code == "mx" and len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]

    if len(digits) != country.national_len:
        return Phone(raw=raw)

    if not country.mobile_certain:
        kind = "Móvil (probable)"
    elif digits[0] in country.mobile_prefixes:
        kind = "Móvil"
    else:
        kind = "Fijo"

    return Phone(raw=raw, e164=country.dial + digits, national=digits, kind=kind)


def province_from_address(address: str, country: Country) -> str:
    if country.code != "es":
        return ""
    match = re.search(r"\b(\d{2})\d{3}\b", str(address or ""))
    return ES_PROVINCES.get(match.group(1), "") if match else ""


def city_from_address(address: str) -> str:
    match = re.search(r"\d{4,5}\s+([^,]+)", str(address or ""))
    if match:
        return match.group(1).strip()
    parts = [p.strip() for p in str(address or "").split(",") if p.strip()]
    return parts[-2] if len(parts) >= 2 else ""


# ---------------------------------------------------------------------------
# Seguridad de red y cortesía
# ---------------------------------------------------------------------------

def is_safe_url(url: str) -> bool:
    """Rechaza esquemas no HTTP y destinos en redes privadas o locales (anti-SSRF)."""
    try:
        parsed = urlparse(str(url or ""))
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            return False
        for info in socket.getaddrinfo(parsed.hostname, None):
            ip = ipaddress.ip_address(info[4][0])
            if (ip.is_private or ip.is_loopback or ip.is_link_local
                    or ip.is_reserved or ip.is_multicast):
                return False
        return True
    except (ValueError, socket.gaierror, UnicodeError, IndexError):
        return False


def robots_allows(url: str) -> bool:
    """Comprueba robots.txt del dominio (cacheado). Ante la duda, permite."""
    try:
        parsed = urlparse(url)
        root = f"{parsed.scheme}://{parsed.netloc}"
        if root not in _robots_cache:
            parser = robotparser.RobotFileParser()
            parser.set_url(urljoin(root, "/robots.txt"))
            try:
                parser.read()
                _robots_cache[root] = parser
            except Exception:  # noqa: BLE001
                _robots_cache[root] = None
        parser = _robots_cache[root]
        return True if parser is None else parser.can_fetch(USER_AGENT, url)
    except Exception:  # noqa: BLE001
        return True


def _polite_wait(domain: str) -> None:
    with _domain_lock:
        last = _domain_last_hit.get(domain, 0.0)
        wait = POLITE_DELAY - (time.time() - last)
        if wait > 0:
            time.sleep(wait)
        _domain_last_hit[domain] = time.time()


# ---------------------------------------------------------------------------
# Caché en disco
# ---------------------------------------------------------------------------

def _cache_path(key: str) -> str:
    os.makedirs(CACHE_DIR, exist_ok=True)
    digest = hashlib.sha256(key.encode()).hexdigest()[:32]
    return os.path.join(CACHE_DIR, f"{digest}.json")


def cache_get(key: str) -> dict | None:
    path = _cache_path(key)
    try:
        if os.path.exists(path) and time.time() - os.path.getmtime(path) < CACHE_TTL_SECONDS:
            with open(path, encoding="utf-8") as handle:
                return json.load(handle)
    except (OSError, json.JSONDecodeError):
        pass
    return None


def cache_set(key: str, payload: dict) -> None:
    try:
        with open(_cache_path(key), "w", encoding="utf-8") as handle:
            json.dump(payload, handle)
    except OSError:
        pass


def clear_cache() -> int:
    removed = 0
    if os.path.isdir(CACHE_DIR):
        for name in os.listdir(CACHE_DIR):
            try:
                os.remove(os.path.join(CACHE_DIR, name))
                removed += 1
            except OSError:
                pass
    return removed


# ---------------------------------------------------------------------------
# Email
# ---------------------------------------------------------------------------

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
JUNK_EMAIL_PARTS = ("example.", "sentry.", "wixpress", "@2x", ".png", ".jpg", ".jpeg",
                    ".gif", ".svg", ".webp", "domain.com", "yourname", "u003e", "@sentry")
ROLE_ACCOUNTS = ("info", "contacto", "hola", "admin", "administracion", "secretaria",
                 "club", "oficina", "correo", "mail", "soporte")


def is_valid_email(value: str) -> bool:
    value = str(value or "").strip().lower()
    if not EMAIL_RE.fullmatch(value) or len(value) > 254:
        return False
    if any(part in value for part in JUNK_EMAIL_PARTS):
        return False
    local, _, domain = value.partition("@")
    return bool(local) and domain.count(".") >= 1 and ".." not in value


def is_role_account(value: str) -> bool:
    local = str(value or "").split("@")[0].lower()
    return any(local.startswith(role) for role in ROLE_ACCOUNTS)


def clean_emails(candidates: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for raw in candidates:
        mail = str(raw or "").strip().strip(".,;:()<>\"'").lower()
        if not is_valid_email(mail) or mail in seen:
            continue
        seen.add(mail)
        result.append(mail)
    result.sort(key=lambda m: (not is_role_account(m), len(m)))
    return result[:3]


# ---------------------------------------------------------------------------
# Enriquecimiento web
# ---------------------------------------------------------------------------

CONTACT_PATHS = ("", "contacto", "contact", "quienes-somos", "sobre-nosotros",
                 "el-club", "club", "nosotros", "junta-directiva", "contacta")

ROLE_RE = re.compile(
    r"(presidente|presidenta|director[ao]?(?:\s+deportiv[ao])?|gerente|coordinador[ao]?|"
    r"secretari[ao]|responsable)\s*[:\-–]?\s*(?:D\.|Dña\.|Sr\.|Sra\.)?\s*"
    r"([A-ZÁÉÍÓÚÑ][a-záéíóúñ]+(?:\s+[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+){1,3})"
)


@dataclass
class WebContact:
    emails: list[str] = field(default_factory=list)
    contact_name: str = ""
    contact_role: str = ""
    source_url: str = ""
    error: str = ""


def scrape_website_contact(website: str, max_pages: int = 3,
                           timeout: int = REQUEST_TIMEOUT) -> WebContact:
    """Extrae email y responsable de la web real. Vacío si no están publicados."""
    result = WebContact()
    if not HTML_PARSER_AVAILABLE:
        result.error = "beautifulsoup4 no instalado"
        return result
    if not website or not is_safe_url(website):
        result.error = "url no válida o no permitida"
        return result

    base = str(website).rstrip("/")
    domain = urlparse(base).netloc
    visited = 0

    for path in CONTACT_PATHS:
        if visited >= max_pages:
            break
        url = base if not path else urljoin(base + "/", path)
        if not robots_allows(url):
            continue
        try:
            _polite_wait(domain)
            response = SESSION.get(url, timeout=timeout, allow_redirects=True)
            if response.status_code != 200:
                continue
            if "text/html" not in response.headers.get("Content-Type", ""):
                continue
            visited += 1

            soup = BeautifulSoup(response.text, "html.parser")
            for tag in soup(["script", "style", "noscript"]):
                tag.decompose()

            mailtos = [
                a["href"].split("mailto:", 1)[1].split("?")[0]
                for a in soup.select('a[href^="mailto:"]')
                if "mailto:" in a.get("href", "")
            ]
            text = soup.get_text(" ", strip=True)[:200_000]
            found = clean_emails(mailtos + EMAIL_RE.findall(text))
            if found and not result.emails:
                result.emails = found
                result.source_url = url

            if not result.contact_name:
                match = ROLE_RE.search(text)
                if match:
                    result.contact_role = match.group(1).strip().title()
                    result.contact_name = match.group(2).strip()
                    result.source_url = result.source_url or url

            if result.emails and result.contact_name:
                break
        except requests.RequestException as exc:
            result.error = type(exc).__name__
            continue

    return result


# ---------------------------------------------------------------------------
# Lead
# ---------------------------------------------------------------------------

@dataclass
class Lead:
    name: str = ""
    sport: str = ""
    country: str = ""
    city: str = ""
    province: str = ""
    address: str = ""
    phone_display: str = ""
    phone_e164: str = ""
    phone_kind: str = ""
    whatsapp_url: str = ""
    website: str = ""
    domain: str = ""
    email: str = ""
    email_type: str = ""
    email_source: str = ""
    contact_name: str = ""
    contact_role: str = ""
    rating: str = ""
    reviews: str = ""
    maps_url: str = ""
    query: str = ""
    message: str = ""
    size_hint: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


def domain_of(website: str) -> str:
    if not website or "http" not in str(website):
        return ""
    host = urlparse(str(website)).netloc.lower().replace("www.", "")
    social = ("facebook", "instagram", "google", "twitter", "youtube", "tiktok", "linktr")
    return "" if any(s in host for s in social) else host


# ---------------------------------------------------------------------------
# SerpApi
# ---------------------------------------------------------------------------

class SerpApiError(RuntimeError):
    pass


def validate_api_key(api_key: str) -> tuple[bool, str]:
    key = (api_key or "").strip()
    if not key:
        return False, "Falta la API key."
    if not re.fullmatch(r"[0-9a-fA-F]+", key):
        return False, "La key contiene caracteres extraños. Cópiala de nuevo desde SerpApi."
    if len(key) != SERPAPI_KEY_LENGTH:
        return False, (f"La key tiene {len(key)} caracteres y debería tener "
                       f"{SERPAPI_KEY_LENGTH}. Suele deberse a un espacio al copiar.")
    return True, ""


def check_account(api_key: str) -> dict:
    """Consulta el estado de la cuenta de SerpApi: plan y búsquedas restantes."""
    valid, reason = validate_api_key(api_key)
    if not valid:
        return {"ok": False, "error": reason}
    try:
        response = SESSION.get("https://serpapi.com/account",
                               params={"api_key": api_key.strip()},
                               timeout=REQUEST_TIMEOUT)
        payload = response.json()
    except (requests.RequestException, ValueError) as exc:
        return {"ok": False, "error": f"No se pudo consultar la cuenta: {exc}"}

    if payload.get("error"):
        return {"ok": False, "error": payload["error"]}

    used = payload.get("this_month_usage", payload.get("searches_per_month", 0))
    total = payload.get("searches_per_month", 0)
    left = payload.get("total_searches_left", payload.get("plan_searches_left", 0))
    return {
        "ok": True,
        "plan": payload.get("plan_name", "—"),
        "used": used,
        "total": total,
        "left": left,
        "email": payload.get("account_email", ""),
    }


def enrich_from_names(
    api_key: str,
    names: list[str],
    country_code: str = "es",
    location_hint: str = "",
    enrich_web: bool = True,
    enrich_workers: int = 8,
    use_cache: bool = True,
    max_searches: int = 200,
    progress: Callable[[float, str], None] | None = None,
) -> tuple[list[Lead], dict]:
    """
    Toma una lista de NOMBRES de negocios y busca cada uno en Google Maps para
    recuperar teléfono, web, dirección y, si procede, email y responsable.
    Los nombres no encontrados se devuelven con los campos vacíos y una marca.
    """
    valid, reason = validate_api_key(api_key)
    if not valid:
        raise SerpApiError(reason)
    country = COUNTRIES[country_code]

    leads: list[Lead] = []
    stats = {"buscados": 0, "encontrados": 0, "no_encontrados": 0, "consumidas": 0,
             "consultas_fallidas": 0, "errores": [], "presupuesto_agotado": False,
             "webs_visitadas": 0}

    clean_names = [n.strip() for n in dict.fromkeys(names) if n and str(n).strip()]
    for index, name in enumerate(clean_names, start=1):
        if stats["consumidas"] >= max_searches:
            stats["presupuesto_agotado"] = True
            break

        query = f"{name} {location_hint}".strip()
        stats["buscados"] += 1
        try:
            raw_results, consumed = search_maps(api_key, query, country, 1, use_cache)
            stats["consumidas"] += consumed
        except SerpApiError as exc:
            stats["consultas_fallidas"] += 1
            stats["errores"].append(f"{name}: {exc}")
            if "api key" in str(exc).lower() or "run out" in str(exc).lower():
                raise
            continue

        if raw_results:
            lead = build_lead(raw_results[0], country, query)
            if lead:
                lead.query = name          # conserva el nombre original del archivo
                leads.append(lead)
                stats["encontrados"] += 1
        else:
            leads.append(Lead(name=name, country=country.name, query=name,
                              size_hint="No encontrado en Maps"))
            stats["no_encontrados"] += 1

        if progress:
            progress(index / len(clean_names) * 0.7,
                     f"{name} · {stats['encontrados']} encontrados")

    if enrich_web:
        targets = [l for l in leads if l.website]
        done = 0
        if targets and HTML_PARSER_AVAILABLE:
            with ThreadPoolExecutor(max_workers=max(1, enrich_workers)) as pool:
                futures = {pool.submit(scrape_website_contact, l.website): l for l in targets}
                for future in as_completed(futures):
                    lead = futures[future]
                    done += 1
                    try:
                        contact = future.result()
                    except Exception:  # noqa: BLE001
                        continue
                    if contact.emails:
                        lead.email = contact.emails[0]
                        lead.email_type = ("Genérico" if is_role_account(contact.emails[0])
                                           else "Personal")
                        lead.email_source = contact.source_url
                    lead.contact_name = contact.contact_name
                    lead.contact_role = contact.contact_role
                    if progress:
                        progress(0.7 + done / len(targets) * 0.3,
                                 f"Enriqueciendo webs · {done}/{len(targets)}")
        stats["webs_visitadas"] = len(targets)

    if progress:
        progress(1.0, f"Listo · {stats['encontrados']}/{stats['buscados']} encontrados")
    return leads, stats


def search_maps(api_key: str, query: str, country: Country, pages: int = 1,
                use_cache: bool = True) -> tuple[list[dict], int]:
    """Devuelve (resultados, búsquedas realmente consumidas)."""
    key = (api_key or "").strip()
    results: list[dict] = []
    consumed = 0

    for page in range(max(1, pages)):
        cache_key = f"{country.code}|{query}|{page}"
        if use_cache:
            cached = cache_get(cache_key)
            if cached is not None:
                batch = cached.get("local_results", [])
                results.extend(batch)
                logger.info("cache hit: %s p%s", query, page)
                if len(batch) < 20:
                    break
                continue

        params = {"engine": "google_maps", "q": query, "type": "search", "hl": "es",
                  "gl": country.code, "start": page * 20, "api_key": key}
        try:
            response = SESSION.get(SERPAPI_ENDPOINT, params=params, timeout=REQUEST_TIMEOUT)
            payload = response.json()
        except (requests.RequestException, ValueError) as exc:
            raise SerpApiError(f"Fallo de red con SerpApi: {exc}") from exc

        consumed += 1
        if payload.get("error"):
            raise SerpApiError(payload["error"])

        batch = payload.get("local_results") or []
        if not batch and payload.get("place_results"):
            batch = [payload["place_results"]]

        if use_cache:
            cache_set(cache_key, {"local_results": batch})

        results.extend(batch)
        if len(batch) < 20:
            break

    return results, consumed


def build_lead(raw: dict, country: Country, query: str) -> Lead | None:
    name = (raw.get("title") or "").strip()
    if not name:
        return None

    phone = parse_phone(raw.get("phone", ""), country)
    address = raw.get("address", "") or ""
    website = raw.get("website", "") or ""

    return Lead(
        name=name,
        sport=classify_sport(name, query, raw.get("type", "")),
        country=country.name,
        city=city_from_address(address),
        province=province_from_address(address, country),
        address=address,
        phone_display=phone.display,
        phone_e164=phone.e164,
        phone_kind=phone.kind,
        website=website,
        domain=domain_of(website),
        rating=str(raw.get("rating", "") or ""),
        reviews=str(raw.get("reviews", "") or ""),
        maps_url=("https://www.google.com/maps/place/?q=place_id:" + raw["place_id"])
        if raw.get("place_id") else "",
        query=query,
        size_hint="Sin web (redes)" if not website else "Con web",
    )


# ---------------------------------------------------------------------------
# Mensajería
# ---------------------------------------------------------------------------

PAIN_BY_SPORT = {
    "Fútbol": "las inscripciones en papel, perseguir las cuotas y avisar a las familias una a una",
    "Fútbol Sala": "las inscripciones en papel, perseguir las cuotas y avisar a las familias una a una",
    "Baloncesto": "cuadrar convocatorias, registrar estadísticas y cobrar equipo por equipo",
    "Balonmano": "los calendarios, las convocatorias y mantener informadas a las familias",
    "Pádel": "las cuotas de la escuela, las inscripciones y las ligas internas",
    "Tenis": "las cuotas de la escuela, las inscripciones y las ligas internas",
    "Natación": "las inscripciones a cursos, las reservas de calle y el control de cuotas",
    "Voleibol": "las inscripciones, las autorizaciones de menores y el cobro de cuotas",
}

DEFAULT_TEMPLATE = (
    "Hola{saludo} 👋 ¿sois del {club}?\n\n"
    "Una pregunta rápida: {dolor}, ¿lo lleváis a mano o con alguna herramienta?"
)

TEMPLATE_VARIABLES = ("club", "ciudad", "provincia", "deporte", "dolor",
                      "contacto", "saludo", "empresa", "remitente", "web")


def render_message(lead: Lead, template: str, extra: dict | None = None) -> str:
    values = {
        "club": lead.name,
        "ciudad": lead.city or "",
        "provincia": lead.province or "",
        "deporte": lead.sport or "",
        "dolor": PAIN_BY_SPORT.get(lead.sport,
                                   "la gestión de inscripciones, cuotas y comunicación"),
        "contacto": lead.contact_name or "",
        "saludo": f", {lead.contact_name.split()[0]}" if lead.contact_name else "",
        "empresa": "", "remitente": "", "web": "",
    }
    values.update(extra or {})
    try:
        return template.format(**values)
    except (KeyError, IndexError, ValueError) as exc:
        return f"[Revisa la plantilla: variable no reconocida {exc}]"


def validate_template(template: str) -> tuple[bool, str]:
    used = set(re.findall(r"\{(\w+)\}", template or ""))
    unknown = used - set(TEMPLATE_VARIABLES)
    if unknown:
        return False, "Variables no reconocidas: " + ", ".join(sorted(unknown))
    return True, ""


def whatsapp_link(phone_e164: str, message: str) -> str:
    return f"https://wa.me/{phone_e164}?text={quote(message)}" if phone_e164 else ""


# ---------------------------------------------------------------------------
# Orquestación
# ---------------------------------------------------------------------------

def generate_leads(
    api_key: str,
    cities: list[str],
    sports: list[str],
    country_code: str = "es",
    pages: int = 1,
    enrich_web: bool = True,
    enrich_limit: int = 40,
    enrich_workers: int = 8,
    template: str = DEFAULT_TEMPLATE,
    template_extra: dict | None = None,
    only_with_phone: bool = True,
    exclude_keys: set[str] | None = None,
    exclude_phones: set[str] | None = None,
    max_searches: int = 200,
    use_cache: bool = True,
    progress: Callable[[float, str], None] | None = None,
) -> tuple[list[Lead], dict]:
    """Pipeline completo. Devuelve (leads, estadísticas)."""
    valid, reason = validate_api_key(api_key)
    if not valid:
        raise SerpApiError(reason)
    if country_code not in COUNTRIES:
        raise SerpApiError(f"País no soportado: {country_code}")

    country = COUNTRIES[country_code]
    exclude_keys = exclude_keys or set()
    exclude_phones = exclude_phones or set()

    leads: list[Lead] = []
    seen_names: set[str] = set()
    seen_phones: set[str] = set()
    stats = {
        "consultas": 0, "consumidas": 0, "brutos": 0, "descartados_no_club": 0,
        "duplicados": 0, "ya_contactados": 0, "sin_telefono": 0,
        "consultas_fallidas": 0, "errores": [], "presupuesto_agotado": False,
        "webs_visitadas": 0,
    }

    unique_cities = [c.strip() for c in dict.fromkeys(cities) if c and c.strip()]
    unique_sports = [s.strip() for s in dict.fromkeys(sports) if s and s.strip()]
    combos = [(city, sport) for city in unique_cities for sport in unique_sports]
    if not combos:
        return [], stats

    for index, (city, sport) in enumerate(combos, start=1):
        if stats["consumidas"] >= max_searches:
            stats["presupuesto_agotado"] = True
            logger.warning("Presupuesto de búsquedas agotado (%s)", max_searches)
            break

        query = f"{sport} {city}"
        try:
            raw_results, consumed = search_maps(api_key, query, country, pages, use_cache)
        except SerpApiError as exc:
            stats["consultas_fallidas"] += 1
            stats["errores"].append(f"{query}: {exc}")
            logger.error("consulta fallida %s: %s", query, exc)
            if "api key" in str(exc).lower():
                raise
            continue

        stats["consultas"] += 1
        stats["consumidas"] += consumed
        stats["brutos"] += len(raw_results)

        for raw in raw_results:
            lead = build_lead(raw, country, query)
            if lead is None:
                continue
            if not is_target_business(lead.name, raw.get("type", "")):
                stats["descartados_no_club"] += 1
                continue

            name_key = normalize_key(lead.name)
            phone_key = lead.phone_e164

            if name_key in seen_names or (phone_key and phone_key in seen_phones):
                stats["duplicados"] += 1
                continue
            if name_key in exclude_keys or (phone_key and phone_key in exclude_phones):
                stats["ya_contactados"] += 1
                seen_names.add(name_key)          # evita recontar sus duplicados
                if phone_key:
                    seen_phones.add(phone_key)
                continue
            if only_with_phone and not lead.phone_e164:
                stats["sin_telefono"] += 1
                continue

            seen_names.add(name_key)
            if phone_key:
                seen_phones.add(phone_key)
            leads.append(lead)

        if progress:
            progress(index / len(combos) * 0.7, f"{query} · {len(leads)} leads")

    if enrich_web and not HTML_PARSER_AVAILABLE:
        stats["errores"].append(
            "Enriquecimiento web omitido: falta beautifulsoup4 en requirements.txt")
        enrich_web = False

    if enrich_web and leads:
        targets = [lead for lead in leads if lead.website][:enrich_limit]
        done = 0
        if targets:
            with ThreadPoolExecutor(max_workers=max(1, enrich_workers)) as pool:
                futures = {pool.submit(scrape_website_contact, lead.website): lead
                           for lead in targets}
                for future in as_completed(futures):
                    lead = futures[future]
                    done += 1
                    try:
                        contact = future.result()
                    except Exception as exc:  # noqa: BLE001
                        logger.error("enriquecimiento %s: %s", lead.website, exc)
                        continue
                    if contact.emails:
                        lead.email = contact.emails[0]
                        lead.email_type = ("Genérico" if is_role_account(contact.emails[0])
                                           else "Personal")
                        lead.email_source = contact.source_url
                    lead.contact_name = contact.contact_name
                    lead.contact_role = contact.contact_role
                    if progress:
                        progress(0.7 + done / len(targets) * 0.3,
                                 f"Enriqueciendo webs · {done}/{len(targets)}")
        stats["webs_visitadas"] = len(targets)

    for lead in leads:
        lead.message = render_message(lead, template, template_extra)
        lead.whatsapp_url = (whatsapp_link(lead.phone_e164, lead.message)
                             if lead.phone_kind.startswith("Móvil") else "")

    if progress:
        progress(1.0, f"Listo · {len(leads)} leads")

    return leads, stats
