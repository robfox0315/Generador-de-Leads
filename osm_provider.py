"""
Proveedor de datos OpenStreetMap (Overpass API) — sin API key.

Ventajas frente a Google Maps:
    · Gratis y sin clave. Sin cuota mensual.
    · Datos abiertos (ODbL), de uso libre citando la fuente.

Limitaciones honestas:
    · Menos cobertura de teléfonos que Google Maps. En España, entre el 15 % y el
      40 % de los registros deportivos tienen teléfono, frente al ~70 % de Maps.
    · La calidad depende de la comunidad que mapea cada zona: muy buena en
      ciudades grandes, escasa en pueblos.
    · Overpass pide un uso responsable: sin paralelismo agresivo y con pausas.

Conclusión práctica: úsalo como complemento gratuito o cuando se agote la cuota
de SerpApi, no como sustituto total.
"""

from __future__ import annotations

__version__ = "4.0"

import time

import requests

OVERPASS_MIRRORS = (
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
)
USER_AGENT = "LeadForgeBot/4.0 (OpenStreetMap client)"
TIMEOUT = 90

# Categorías de LeadForge traducidas a etiquetas de OpenStreetMap
OSM_FILTERS: dict[str, list[str]] = {
    "club de futbol base": ['["sport"="soccer"]["club"="sport"]', '["sport"="soccer"]["leisure"="sports_centre"]'],
    "escuela de futbol": ['["sport"="soccer"]["leisure"="sports_centre"]'],
    "club de baloncesto": ['["sport"="basketball"]["club"="sport"]', '["sport"="basketball"]["leisure"="sports_centre"]'],
    "club de balonmano": ['["sport"="handball"]["club"="sport"]', '["sport"="handball"]["leisure"="sports_centre"]'],
    "club de padel": ['["sport"="padel"]', '["sport"="paddle_tennis"]'],
    "club de tenis": ['["sport"="tennis"]["leisure"="sports_centre"]', '["sport"="tennis"]["club"="sport"]'],
    "club de natacion": ['["sport"="swimming"]["leisure"="sports_centre"]', '["leisure"="swimming_pool"]["access"!="private"]'],
    "club de atletismo": ['["sport"="athletics"]'],
    "club de rugby": ['["sport"="rugby_union"]', '["sport"="rugby"]'],
    "club de voleibol": ['["sport"="volleyball"]'],
    "club deportivo": ['["club"="sport"]', '["leisure"="sports_centre"]'],
    "club multideporte": ['["leisure"="sports_centre"]'],
    "asociacion deportiva": ['["club"="sport"]'],
    "gimnasio": ['["leisure"="fitness_centre"]'],
    "box crossfit": ['["leisure"="fitness_centre"]["sport"="crossfit"]'],
    "estudio de pilates": ['["leisure"="fitness_centre"]["sport"="pilates"]'],
    "centro de yoga": ['["leisure"="fitness_centre"]["sport"="yoga"]'],
    "restaurante": ['["amenity"="restaurant"]'],
    "cafeteria": ['["amenity"="cafe"]'],
    "bar de tapas": ['["amenity"="bar"]', '["amenity"="pub"]'],
    "pizzeria": ['["amenity"="restaurant"]["cuisine"="pizza"]'],
    "clinica dental": ['["healthcare"="dentist"]', '["amenity"="dentist"]'],
    "centro de fisioterapia": ['["healthcare"="physiotherapist"]'],
    "clinica veterinaria": ['["amenity"="veterinary"]'],
    "peluqueria": ['["shop"="hairdresser"]'],
    "optica": ['["shop"="optician"]'],
    "academia de idiomas": ['["amenity"="language_school"]'],
    "centro de estudios": ['["amenity"="college"]', '["office"="educational_institution"]'],
    "escuela de musica": ['["amenity"="music_school"]'],
    "escuela de danza": ['["amenity"="dancing_school"]', '["leisure"="dance"]'],
    "autoescuela": ['["amenity"="driving_school"]'],
    "libreria": ['["shop"="books"]'],
    "floristeria": ['["shop"="florist"]'],
    "ferreteria": ['["shop"="hardware"]', '["shop"="doityourself"]'],
    "tienda de mascotas": ['["shop"="pet"]'],
    "tienda de deportes": ['["shop"="sports"]'],
}

DEFAULT_FILTERS = ['["club"="sport"]', '["leisure"="sports_centre"]']


class OverpassError(RuntimeError):
    pass


def filters_for(term: str) -> list[str]:
    """Traduce un término de búsqueda a filtros de OpenStreetMap."""
    key = str(term or "").strip().lower()
    if key in OSM_FILTERS:
        return OSM_FILTERS[key]
    for known, filters in OSM_FILTERS.items():          # coincidencia parcial
        if known in key or key in known:
            return filters
    return DEFAULT_FILTERS


def build_query(city: str, term: str, limit: int = 200) -> str:
    """Construye la consulta Overpass QL para una ciudad y un tipo de negocio."""
    blocks = []
    for selector in filters_for(term):
        blocks.append(f"  node(area.searchArea){selector};")
        blocks.append(f"  way(area.searchArea){selector};")
    body = "\n".join(blocks)
    safe_city = str(city).replace('"', "").replace("\\", "")
    return (
        f'[out:json][timeout:{TIMEOUT - 20}];\n'
        f'area["name"="{safe_city}"]["boundary"="administrative"]->.searchArea;\n'
        f"(\n{body}\n);\n"
        f"out center tags {int(limit)};"
    )


def _first_tag(tags: dict, *names: str) -> str:
    for name in names:
        value = tags.get(name)
        if value:
            return str(value).strip()
    return ""


def element_to_raw(element: dict) -> dict | None:
    """
    Convierte un elemento de OSM al mismo formato que devuelve SerpApi,
    para que el resto del motor no note la diferencia.
    """
    tags = element.get("tags", {}) or {}
    name = _first_tag(tags, "name", "operator", "brand")
    if not name:
        return None

    street = _first_tag(tags, "addr:street")
    number = _first_tag(tags, "addr:housenumber")
    postcode = _first_tag(tags, "addr:postcode")
    city = _first_tag(tags, "addr:city", "addr:town", "addr:village")
    parts = [p for p in (f"{street} {number}".strip(), f"{postcode} {city}".strip()) if p]
    address = ", ".join(parts)

    latitude = element.get("lat") or (element.get("center") or {}).get("lat")
    longitude = element.get("lon") or (element.get("center") or {}).get("lon")

    return {
        "title": name,
        "phone": _first_tag(tags, "phone", "contact:phone", "contact:mobile", "mobile"),
        "website": _first_tag(tags, "website", "contact:website", "url"),
        "address": address,
        "type": _first_tag(tags, "sport", "leisure", "amenity", "shop", "club"),
        "rating": "",
        "place_id": "",
        "osm_email": _first_tag(tags, "email", "contact:email"),
        "osm_id": f"{element.get('type','')}/{element.get('id','')}",
        "osm_url": (f"https://www.openstreetmap.org/{element.get('type','')}/"
                    f"{element.get('id','')}" if element.get("id") else ""),
        "latitude": latitude,
        "longitude": longitude,
    }


def search_osm(city: str, term: str, limit: int = 200,
               session: requests.Session | None = None,
               pause: float = 1.5) -> list[dict]:
    """
    Busca negocios en OpenStreetMap. No necesita API key.
    Devuelve una lista en el mismo formato que el proveedor de Google Maps.
    """
    query = build_query(city, term, limit)
    http = session or requests.Session()
    headers = {"User-Agent": USER_AGENT}
    last_error = ""

    for index, mirror in enumerate(OVERPASS_MIRRORS):
        try:
            response = http.post(mirror, data={"data": query},
                                 headers=headers, timeout=TIMEOUT)
            if response.status_code == 429:
                last_error = "Overpass está saturado (429). Espera un momento."
                time.sleep(pause * 2)
                continue
            if response.status_code != 200:
                last_error = f"{mirror.split('/')[2]} devolvió HTTP {response.status_code}"
                continue

            elements = response.json().get("elements", [])
            results = [raw for raw in (element_to_raw(e) for e in elements) if raw]
            if index or pause:
                time.sleep(pause)         # cortesía con un servicio gratuito
            return results
        except (requests.RequestException, ValueError) as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            continue

    raise OverpassError(last_error or "No se pudo contactar con ninguna réplica de Overpass.")
