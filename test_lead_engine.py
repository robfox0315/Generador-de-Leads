"""
Tests del motor de LeadForge. No consumen cuota de SerpApi.

Ejecutar:  python -m pytest test_lead_engine.py -v
           (o simplemente: python test_lead_engine.py)
"""

import lead_engine as engine


def check(label, condition):
    status = "PASA" if condition else "FALLA"
    print(f"  [{status}] {label}")
    return bool(condition)


# ---------------------------------------------------------------------------
# Teléfonos
# ---------------------------------------------------------------------------

def test_phones():
    es, mx, co = (engine.COUNTRIES[c] for c in ("es", "mx", "co"))
    results = [
        check("España móvil 6 se normaliza a +34…",
              engine.parse_phone("+34 614 41 56 34", es).e164 == "34614415634"),
        check("España móvil detectado como Móvil",
              engine.parse_phone("619719878", es).kind == "Móvil"),
        check("España 9 se detecta como Fijo",
              engine.parse_phone("918520416", es).kind == "Fijo"),
        check("España acepta prefijo 0034",
              engine.parse_phone("0034619719878", es).e164 == "34619719878"),
        check("Número corto se descarta",
              engine.parse_phone("6123", es).e164 == ""),
        check("Número basura se descarta",
              engine.parse_phone("no disponible", es).e164 == ""),
        check("México quita el 1 de móvil",
              engine.parse_phone("+52 1 55 2271 7561", mx).e164 == "525522717561"),
        check("México se etiqueta como probable (honestidad)",
              engine.parse_phone("5522717561", mx).kind == "Móvil (probable)"),
        check("Colombia celular por 3 es Móvil",
              engine.parse_phone("+57 310 555 4433", co).kind == "Móvil"),
        check("Colombia fijo no es móvil",
              engine.parse_phone("6013001234", co).kind == "Fijo"),
    ]
    return all(results)


# ---------------------------------------------------------------------------
# Clasificación y filtros
# ---------------------------------------------------------------------------

def test_classification():
    results = [
        check("Detecta baloncesto", engine.classify_sport("CB Granollers Baloncesto") == "Baloncesto"),
        check("Detecta pádel con tilde", engine.classify_sport("Escuela de Pádel Motril") == "Pádel"),
        check("Detecta fútbol sala antes que fútbol",
              engine.classify_sport("CD Fútbol Sala Lugo") == "Fútbol Sala"),
        check("Sin pistas devuelve Multideporte",
              engine.classify_sport("Asociación Vecinal") == "Multideporte"),
        check("Descarta gimnasios", engine.is_target_business("Gimnasio Fit") is False),
        check("Descarta polideportivo municipal",
              engine.is_target_business("Polideportivo Municipal Norte") is False),
        check("Acepta un club real", engine.is_target_business("CD Tudelano") is True),
    ]
    return all(results)


# ---------------------------------------------------------------------------
# Localización
# ---------------------------------------------------------------------------

def test_location():
    es, mx = engine.COUNTRIES["es"], engine.COUNTRIES["mx"]
    results = [
        check("CP 41010 → Sevilla",
              engine.province_from_address("Av. X, 41010 Sevilla", es) == "Sevilla"),
        check("CP 08001 → Barcelona",
              engine.province_from_address("C/ Y, 08001 Barcelona", es) == "Barcelona"),
        check("Sin CP no inventa provincia",
              engine.province_from_address("Calle sin código", es) == ""),
        check("Fuera de España no asigna provincia española",
              engine.province_from_address("Col. Roma, 06700 CDMX", mx) == ""),
        check("Extrae ciudad tras el CP",
              engine.city_from_address("Av. X, 41010 Sevilla, España") == "Sevilla"),
    ]
    return all(results)


# ---------------------------------------------------------------------------
# Seguridad
# ---------------------------------------------------------------------------

def test_security():
    results = [
        check("Bloquea localhost", engine.is_safe_url("http://localhost/admin") is False),
        check("Bloquea IP privada", engine.is_safe_url("http://192.168.1.1/") is False),
        check("Bloquea metadatos cloud", engine.is_safe_url("http://169.254.169.254/") is False),
        check("Bloquea esquema file://", engine.is_safe_url("file:///etc/passwd") is False),
        check("Bloquea cadena vacía", engine.is_safe_url("") is False),
        check("Permite dominio público", engine.is_safe_url("https://example.com") is True),
    ]
    return all(results)


# ---------------------------------------------------------------------------
# Emails
# ---------------------------------------------------------------------------

def test_emails():
    results = [
        check("Email válido pasa", engine.is_valid_email("info@club.com") is True),
        check("Descarta imagen .png", engine.is_valid_email("logo@2x.png") is False),
        check("Descarta dominio de ejemplo", engine.is_valid_email("a@example.com") is False),
        check("Descarta cadena sin arroba", engine.is_valid_email("noesunmail") is False),
        check("Reconoce cuenta genérica", engine.is_role_account("info@club.com") is True),
        check("Reconoce cuenta personal", engine.is_role_account("marc.puig@club.com") is False),
        check("Prioriza la genérica del club",
              engine.clean_emails(["marc@club.com", "info@club.com"])[0] == "info@club.com"),
        check("Elimina duplicados",
              len(engine.clean_emails(["info@club.com", "INFO@club.com"])) == 1),
    ]
    return all(results)


# ---------------------------------------------------------------------------
# API key y plantillas
# ---------------------------------------------------------------------------

def test_validation():
    good = "a" * 64
    results = [
        check("Key correcta se acepta", engine.validate_api_key(good)[0] is True),
        check("Key con espacio se acepta tras strip",
              engine.validate_api_key(" " + good + " ")[0] is True),
        check("Key de 65 se rechaza", engine.validate_api_key("a" * 65)[0] is False),
        check("Key vacía se rechaza", engine.validate_api_key("")[0] is False),
        check("Key con símbolos se rechaza", engine.validate_api_key("abc!" * 16)[0] is False),
        check("Plantilla válida pasa",
              engine.validate_template("Hola {club} de {ciudad}")[0] is True),
        check("Plantilla con variable inventada se rechaza",
              engine.validate_template("Hola {nombre_raro}")[0] is False),
    ]
    return all(results)


# ---------------------------------------------------------------------------
# Mensajes
# ---------------------------------------------------------------------------

def test_messages():
    lead = engine.Lead(name="CB Granollers", sport="Baloncesto", city="Granollers",
                       province="Barcelona", phone_e164="34619719878")
    plain = engine.render_message(lead, engine.DEFAULT_TEMPLATE)
    lead.contact_name = "Marc Puig"
    personal = engine.render_message(lead, engine.DEFAULT_TEMPLATE)
    link = engine.whatsapp_link(lead.phone_e164, personal)
    results = [
        check("Incluye el nombre del club", "CB Granollers" in plain),
        check("Usa el dolor del deporte", "convocatorias" in plain),
        check("Sin responsable no inventa saludo", "Hola 👋" in plain),
        check("Con responsable personaliza el saludo", "Hola, Marc" in personal),
        check("Genera enlace wa.me", link.startswith("https://wa.me/34619719878?text=")),
        check("Sin teléfono no genera enlace", engine.whatsapp_link("", "hola") == ""),
        check("Plantilla rota no rompe la app",
              "Revisa la plantilla" in engine.render_message(lead, "Hola {inexistente}")),
    ]
    return all(results)


# ---------------------------------------------------------------------------
# Deduplicación y caché
# ---------------------------------------------------------------------------

def test_dedup_and_cache():
    engine.cache_set("test|clave", {"local_results": [{"title": "X"}]})
    cached = engine.cache_get("test|clave")
    results = [
        check("Normaliza acentos al deduplicar",
              engine.normalize_key("Club Deportivo Ávila") == engine.normalize_key("club deportivo avila")),
        check("Ignora signos al deduplicar",
              engine.normalize_key("C.D. Tudelano") == engine.normalize_key("CD Tudelano")),
        check("La caché guarda y recupera", cached is not None and cached["local_results"][0]["title"] == "X"),
        check("Clave inexistente devuelve None", engine.cache_get("no|existe|nunca") is None),
    ]
    engine.clear_cache()
    return all(results)


# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Catálogo (selectores)
# ---------------------------------------------------------------------------

def test_catalog():
    import catalog
    es = catalog.cities_for("es")
    mx = catalog.cities_for("mx")
    terms = catalog.all_terms()
    results = [
        check("España tiene catálogo amplio de ciudades", len(es) >= 70),
        check("México tiene catálogo de ciudades", len(mx) >= 30),
        check("Madrid está en España", "Madrid" in es),
        check("CDMX está en México", "Ciudad de México" in mx),
        check("País desconocido devuelve lista vacía", catalog.cities_for("zz") == []),
        check("No hay ciudades duplicadas", len(es) == len(set(es))),
        check("Hay términos de varios sectores", len(terms) >= 40),
        check("No hay términos duplicados", len(terms) == len(set(terms))),
        check("Todos los sectores tienen términos",
              all(len(v) > 0 for v in catalog.SECTORS.values())),
    ]
    return all(results)


# ---------------------------------------------------------------------------
# Pipeline end-to-end con respuestas simuladas (no consume cuota)
# ---------------------------------------------------------------------------

class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload
    def json(self):
        return self._payload


def _fake_get(payload):
    def _inner(url, params=None, timeout=None, **kwargs):
        return _FakeResponse(payload)
    return _inner


def test_pipeline():
    from unittest.mock import patch
    sample = {"local_results": [
        {"title": "CD Tudelano", "phone": "+34 619 71 98 78",
         "address": "C/ X, 41010 Sevilla, España", "website": "https://cdtudelano.com",
         "place_id": "abc", "rating": 4.5},
        {"title": "Gimnasio Fit", "phone": "+34 600 11 22 33",
         "address": "C/ Y, 41010 Sevilla"},
        {"title": "CD Tudelano", "phone": "+34 619 71 98 78",
         "address": "C/ X, 41010 Sevilla"},
    ]}
    with patch.object(engine.SESSION, "get", side_effect=_fake_get(sample)):
        leads, stats = engine.generate_leads("a" * 64, ["Sevilla"], ["club de futbol"],
                                             use_cache=False, enrich_web=False)
    results = [
        check("Extrae los leads válidos", len(leads) == 1),
        check("Descarta el gimnasio", stats["descartados_no_club"] == 1),
        check("Detecta el duplicado", stats["duplicados"] == 1),
        check("Normaliza el teléfono", leads[0].phone_e164 == "34619719878"),
        check("Deduce la provincia", leads[0].province == "Sevilla"),
        check("Genera enlace de WhatsApp", leads[0].whatsapp_url.startswith("https://wa.me/")),
        check("Contabiliza las búsquedas", stats["consumidas"] == 1),
    ]

    # Sin cuota: no debe romper, debe reportar
    with patch.object(engine.SESSION, "get",
                      side_effect=_fake_get({"error": "Your account has run out of searches."})):
        leads2, stats2 = engine.generate_leads("a" * 64, ["Sevilla"], ["club de futbol"],
                                               use_cache=False, enrich_web=False)
    results += [
        check("Sin cuota no devuelve leads", len(leads2) == 0),
        check("Sin cuota registra el fallo", stats2["consultas_fallidas"] == 1),
        check("Sin cuota guarda el mensaje real",
              "run out" in stats2["errores"][0].lower()),
    ]

    # Exclusión de contactados previos
    with patch.object(engine.SESSION, "get", side_effect=_fake_get(sample)):
        leads3, stats3 = engine.generate_leads(
            "a" * 64, ["Sevilla"], ["club de futbol"], use_cache=False, enrich_web=False,
            exclude_keys={engine.normalize_key("CD Tudelano")})
    results.append(check("Excluye los ya contactados",
                         len(leads3) == 0 and stats3["ya_contactados"] == 1))
    return all(results)


def test_enrich_from_names():
    from unittest.mock import patch
    found = {"local_results": [
        {"title": "CB Granollers", "phone": "+34 619 71 98 78",
         "address": "C/ Z, 08400 Granollers", "website": "https://cbgranollers.cat"}]}
    with patch.object(engine.SESSION, "get", side_effect=_fake_get(found)):
        leads, stats = engine.enrich_from_names("a" * 64, ["CB Granollers"],
                                                use_cache=False, enrich_web=False)
    empty = {"local_results": []}
    with patch.object(engine.SESSION, "get", side_effect=_fake_get(empty)):
        leads2, stats2 = engine.enrich_from_names("a" * 64, ["Club Inexistente XYZ"],
                                                  use_cache=False, enrich_web=False)
    results = [
        check("Encuentra el negocio por su nombre", stats["encontrados"] == 1),
        check("Recupera el teléfono", leads[0].phone_e164 == "34619719878"),
        check("Conserva el nombre original del archivo", leads[0].query == "CB Granollers"),
        check("Los no encontrados se devuelven marcados",
              stats2["no_encontrados"] == 1 and leads2[0].size_hint == "No encontrado en Maps"),
        check("No inventa teléfono si no lo encuentra", leads2[0].phone_e164 == ""),
    ]
    return all(results)


# ---------------------------------------------------------------------------
# Persistencia
# ---------------------------------------------------------------------------

def test_storage():
    import os, tempfile, storage
    db = os.path.join(tempfile.gettempdir(), "lf_suite_test.db")
    if os.path.exists(db):
        os.remove(db)

    a = {"name": "CD Tudelano", "sport": "Fútbol", "city": "Sevilla",
         "phone_e164": "34619719878", "phone_kind": "Móvil", "email": "",
         "contact_name": "", "website": "https://x.com", "rating": "4.5", "email_type": ""}
    b = {"name": "CB Granollers", "sport": "Baloncesto", "city": "Granollers",
         "phone_e164": "34600112233", "phone_kind": "Móvil", "email": "info@cb.com",
         "email_type": "Genérico", "contact_name": "Marc Puig",
         "website": "https://cb.com", "rating": "4.8"}

    first = storage.save_leads([a, b], campaign="Test", path=db)
    second = storage.save_leads([a, b], campaign="Test", path=db)
    enriched = dict(a, email="info@t.com", contact_name="Ana Ruiz")
    third = storage.save_leads([enriched], path=db)
    rows = storage.fetch_leads(path=db)
    names, phones = storage.known_fingerprints(path=db)
    moved = storage.update_status([rows[0]["id"]], "Demo agendada", path=db)
    filtered = storage.fetch_leads(status="Demo agendada", path=db)
    summary = storage.stats(path=db)

    results = [
        check("Guarda leads nuevos", first["nuevos"] == 2),
        check("No duplica en la segunda pasada", second["nuevos"] == 0 and second["duplicados"] == 2),
        check("Completa huecos con datos nuevos", third["completados"] == 1),
        check("El email se rellenó al completar",
              any(r["email"] == "info@t.com" for r in rows)),
        check("Puntúa mejor al lead completo", storage.score_lead(b) > storage.score_lead(a)),
        check("Ordena por calidad", rows[0]["score"] >= rows[-1]["score"]),
        check("Devuelve claves para excluir", len(names) == 2 and len(phones) == 2),
        check("Cambia el estado", moved == 1 and len(filtered) == 1),
        check("Calcula métricas", summary["total"] == 2 and summary["con_whatsapp"] == 2),
        check("Rechaza estados inválidos",
              _raises(storage.update_status, [rows[0]["id"]], "Inventado", path=db)),
        check("Huella por teléfono es estable",
              storage.fingerprint(a) == storage.fingerprint(dict(a, name="Otro nombre"))),
    ]
    storage.reset_database(path=db)
    os.remove(db)
    return all(results)


def _raises(func, *args, **kwargs) -> bool:
    try:
        func(*args, **kwargs)
        return False
    except Exception:  # noqa: BLE001
        return True


SUITES = [
    ("Teléfonos multi-país", test_phones),
    ("Clasificación y filtros", test_classification),
    ("Localización", test_location),
    ("Seguridad (anti-SSRF)", test_security),
    ("Validación de emails", test_emails),
    ("API key y plantillas", test_validation),
    ("Generación de mensajes", test_messages),
    ("Deduplicación y caché", test_dedup_and_cache),
    ("Catálogo de selectores", test_catalog),
    ("Pipeline completo (simulado)", test_pipeline),
    ("Enriquecer desde nombres", test_enrich_from_names),
    ("Persistencia y CRM", test_storage),
]


def run_all() -> bool:
    print("=" * 62)
    print("LEADFORGE — SUITE DE TESTS")
    print("=" * 62)
    passed = 0
    for title, suite in SUITES:
        print(f"\n{title}")
        if suite():
            passed += 1
    print("\n" + "=" * 62)
    ok = passed == len(SUITES)
    print(f"{'TODO CORRECTO' if ok else 'HAY FALLOS'} — {passed}/{len(SUITES)} bloques")
    print("=" * 62)
    return ok


if __name__ == "__main__":
    raise SystemExit(0 if run_all() else 1)
