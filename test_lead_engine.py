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

SUITES = [
    ("Teléfonos multi-país", test_phones),
    ("Clasificación y filtros", test_classification),
    ("Localización", test_location),
    ("Seguridad (anti-SSRF)", test_security),
    ("Validación de emails", test_emails),
    ("API key y plantillas", test_validation),
    ("Generación de mensajes", test_messages),
    ("Deduplicación y caché", test_dedup_and_cache),
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
