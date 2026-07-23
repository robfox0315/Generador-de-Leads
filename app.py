"""
LeadForge — Generador de leads verificados por ciudad y sector.

Ejecutar:  streamlit run app.py
"""

from __future__ import annotations

import io
from datetime import datetime

import pandas as pd
import streamlit as st

from lead_engine import (
    COUNTRIES,
    DEFAULT_TEMPLATE,
    TEMPLATE_VARIABLES,
    SerpApiError,
    clear_cache,
    generate_leads,
    normalize_key,
    parse_phone,
    validate_api_key,
    validate_template,
)

st.set_page_config(page_title="LeadForge", page_icon="⚡", layout="wide")

if "accent" not in st.session_state:
    st.session_state["accent"] = "#FF4D17"
ACCENT = st.session_state["accent"]

st.markdown(
    f"""
    <style>
      @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600&family=Inter:wght@400;600;800&display=swap');
      html, body, [class*="css"] {{ font-family: 'Inter', system-ui, sans-serif; }}
      .lf-title {{ font-weight: 800; font-size: 2.1rem; letter-spacing: -.02em; margin: 0; }}
      .lf-title span {{ color: {ACCENT}; }}
      .lf-sub {{ color: #8B94A3; font-size: .95rem; margin-top: .15rem; }}
      .lf-rule {{ height: 3px; background: {ACCENT}; width: 64px; margin: .9rem 0 1.4rem; }}
      .lf-metric {{ border: 1px solid rgba(255,255,255,.10); border-left: 3px solid {ACCENT};
        padding: .75rem .95rem; border-radius: 4px; background: rgba(255,255,255,.02); }}
      .lf-metric .k {{ font-family: 'IBM Plex Mono', monospace; font-size: 1.55rem; font-weight: 600; }}
      .lf-metric .l {{ font-size: .72rem; text-transform: uppercase; letter-spacing: .09em; color: #8B94A3; }}
      .lf-note {{ border-left: 3px solid {ACCENT}; background: rgba(255,77,23,.07);
        padding: .7rem .9rem; border-radius: 4px; font-size: .88rem; }}
      div[data-testid="stDataFrame"] {{ font-family: 'IBM Plex Mono', monospace; }}
    </style>
    """,
    unsafe_allow_html=True,
)

st.markdown(
    '<p class="lf-title">LEAD<span>FORGE</span></p>'
    '<p class="lf-sub">Leads reales por ciudad y sector. Teléfono, web, email y responsable '
    '— extraídos de fuentes verificables, nunca inventados.</p>'
    '<div class="lf-rule"></div>',
    unsafe_allow_html=True,
)

PRESETS = {
    "Clubes deportivos": [
        "club de futbol base", "escuela de futbol", "club de baloncesto",
        "club de balonmano", "club de padel", "club deportivo",
    ],
    "Gimnasios y fitness": [
        "gimnasio", "entrenamiento personal", "box crossfit", "estudio de pilates",
    ],
    "Academias y formación": [
        "academia de idiomas", "centro de estudios", "academia refuerzo escolar",
    ],
    "Hostelería": ["restaurante", "cafeteria", "bar de tapas"],
    "Personalizado": [],
}

# ---------------------------------------------------------------------------
# Barra lateral
# ---------------------------------------------------------------------------
with st.sidebar:
    st.subheader("Conexión")

    stored_key = ""
    try:
        stored_key = st.secrets.get("SERPAPI_KEY", "")
    except Exception:  # noqa: BLE001 — secrets.toml puede no existir
        stored_key = ""

    api_key = st.text_input(
        "API key de SerpApi", value=stored_key, type="password",
        help="Se usa solo en esta sesión. Para fijarla al equipo, añádela a .streamlit/secrets.toml",
    )
    if api_key:
        ok, reason = validate_api_key(api_key)
        st.caption("✅ Key válida" if ok else f"⚠️ {reason}")
    else:
        st.caption("Consíguela gratis en serpapi.com — 250 búsquedas/mes.")

    country_code = st.selectbox(
        "País", options=list(COUNTRIES.keys()),
        format_func=lambda c: COUNTRIES[c].name, index=0,
    )

    st.divider()
    st.subheader("Marca")
    company = st.text_input("Empresa", value="Competize")
    sender = st.text_input("Quién firma", value="Roberto")
    site = st.text_input("Web", value="competize.com/es")
    st.session_state["accent"] = st.color_picker("Color de acento", ACCENT)

    st.divider()
    st.subheader("Precisión")
    pages = st.slider("Páginas por búsqueda", 1, 3, 1,
                      help="1 página ≈ 20 resultados y consume 1 búsqueda.")
    max_searches = st.number_input("Tope de búsquedas (presupuesto)", 10, 1000, 200, step=10,
                                   help="Corta la ejecución al llegar a este número.")
    only_phone = st.checkbox("Solo negocios con teléfono", value=True)
    use_cache = st.checkbox("Reutilizar resultados recientes", value=True,
                            help="Ahorra cuota: no repite búsquedas hechas en los últimos 3 días.")

    st.divider()
    st.subheader("Enriquecimiento web")
    enrich_web = st.checkbox("Buscar email y responsable en la web", value=True)
    enrich_limit = st.slider("Máx. webs a visitar", 10, 150, 40, step=10, disabled=not enrich_web)
    enrich_workers = st.slider("Peticiones en paralelo", 1, 16, 8, disabled=not enrich_web,
                               help="Más rápido, pero sé razonable con los servidores ajenos.")

    st.divider()
    if st.button("Vaciar caché", use_container_width=True):
        st.success(f"{clear_cache()} respuestas eliminadas.")

# ---------------------------------------------------------------------------
# Criterios
# ---------------------------------------------------------------------------
left, right = st.columns(2, gap="large")

with left:
    st.markdown("##### Dónde buscar")
    cities_raw = st.text_area("Ciudades", value="Sevilla\nGranada\nZaragoza",
                              height=140, label_visibility="collapsed")
    cities = [c.strip() for c in cities_raw.splitlines() if c.strip()]

with right:
    st.markdown("##### Qué buscar")
    preset = st.selectbox("Sector", list(PRESETS.keys()))
    default_terms = "\n".join(PRESETS[preset]) if PRESETS[preset] else "club de futbol base"
    sports_raw = st.text_area("Términos", value=default_terms, height=140,
                              key=f"terms_{preset}", label_visibility="collapsed")
    sports = [s.strip() for s in sports_raw.splitlines() if s.strip()]

estimated = len(set(cities)) * len(set(sports)) * pages
budget_note = "" if estimated <= max_searches else "  ·  ⚠️ supera tu tope, se cortará antes"
st.caption(f"Consumo estimado: **{estimated}** búsquedas "
           f"({len(set(cities))} ciudades × {len(set(sports))} términos × {pages} páginas).{budget_note}")

with st.expander("Mensaje de contacto", expanded=False):
    st.caption("Variables: " + " ".join("{" + v + "}" for v in TEMPLATE_VARIABLES))
    template = st.text_area("Plantilla", value=DEFAULT_TEMPLATE, height=140,
                            label_visibility="collapsed")
    tpl_ok, tpl_reason = validate_template(template)
    if not tpl_ok:
        st.warning(tpl_reason)

with st.expander("Excluir contactos ya trabajados", expanded=False):
    st.caption("Sube Excel/CSV de campañas anteriores. Se cruzan por nombre y por teléfono.")
    previous = st.file_uploader("Archivos previos", type=["xlsx", "csv"],
                                accept_multiple_files=True, label_visibility="collapsed")

exclude_keys: set[str] = set()
exclude_phones: set[str] = set()
if previous:
    country_obj = COUNTRIES[country_code]
    for upload in previous:
        try:
            frame = (pd.read_csv(upload) if upload.name.lower().endswith(".csv")
                     else pd.read_excel(upload))
            lowered = {str(c).strip().lower(): c for c in frame.columns}
            name_col = next((lowered[k] for k in
                             ("club", "nombre", "name", "empresa", "escuela") if k in lowered),
                            frame.columns[0])
            exclude_keys |= {normalize_key(v) for v in frame[name_col].dropna()}
            phone_col = next((lowered[k] for k in
                              ("telefono", "teléfono", "movil", "móvil", "phone", "whatsapp")
                              if k in lowered), None)
            if phone_col:
                for value in frame[phone_col].dropna():
                    parsed = parse_phone(str(value), country_obj)
                    if parsed.e164:
                        exclude_phones.add(parsed.e164)
        except Exception as exc:  # noqa: BLE001
            st.warning(f"No se pudo leer {upload.name}: {exc}")
    st.info(f"Excluidos: {len(exclude_keys)} nombres y {len(exclude_phones)} teléfonos.")

st.write("")
launch = st.button("Generar leads", type="primary", use_container_width=True)

# ---------------------------------------------------------------------------
# Ejecución
# ---------------------------------------------------------------------------
if launch:
    key_ok, key_reason = validate_api_key(api_key)
    if not key_ok:
        st.error(key_reason)
    elif not cities or not sports:
        st.error("Indica al menos una ciudad y un término de búsqueda.")
    elif not tpl_ok:
        st.error(tpl_reason)
    else:
        bar = st.progress(0.0, text="Iniciando…")

        def report(fraction: float, label: str) -> None:
            bar.progress(min(max(fraction, 0.0), 1.0), text=label)

        try:
            leads, stats = generate_leads(
                api_key=api_key,
                cities=cities,
                sports=sports,
                country_code=country_code,
                pages=pages,
                enrich_web=enrich_web,
                enrich_limit=enrich_limit,
                enrich_workers=enrich_workers,
                template=template,
                template_extra={"empresa": company, "remitente": sender, "web": site},
                only_with_phone=only_phone,
                exclude_keys=exclude_keys,
                exclude_phones=exclude_phones,
                max_searches=int(max_searches),
                use_cache=use_cache,
                progress=report,
            )
            bar.empty()
            st.session_state["leads"] = [lead.as_dict() for lead in leads]
            st.session_state["stats"] = stats
            if not leads:
                st.warning("No se encontraron leads con esos criterios. "
                           "Prueba con otras ciudades o términos más generales.")
        except SerpApiError as exc:
            bar.empty()
            st.error(f"SerpApi: {exc}")

# ---------------------------------------------------------------------------
# Resultados
# ---------------------------------------------------------------------------
if st.session_state.get("leads"):
    data = pd.DataFrame(st.session_state["leads"])
    stats = st.session_state.get("stats", {})

    mobiles = int(data["phone_kind"].str.startswith("Móvil").sum())
    with_email = int((data["email"] != "").sum())
    with_person = int((data["contact_name"] != "").sum())

    st.markdown("#### Resultado")
    tiles = [
        (len(data), "leads únicos"),
        (mobiles, "con WhatsApp"),
        (with_email, "con email real"),
        (with_person, "con responsable"),
        (stats.get("consumidas", 0), "búsquedas gastadas"),
    ]
    for col, (value, label) in zip(st.columns(5), tiles):
        col.markdown(f'<div class="lf-metric"><div class="k">{value}</div>'
                     f'<div class="l">{label}</div></div>', unsafe_allow_html=True)

    st.caption(
        f"Filtrados: {stats.get('descartados_no_club', 0)} fuera de sector · "
        f"{stats.get('duplicados', 0)} duplicados · "
        f"{stats.get('ya_contactados', 0)} ya contactados · "
        f"{stats.get('sin_telefono', 0)} sin teléfono · "
        f"{stats.get('webs_visitadas', 0)} webs visitadas."
    )

    if stats.get("presupuesto_agotado"):
        st.warning(f"Se alcanzó el tope de {max_searches} búsquedas y la ejecución se detuvo ahí.")
    if stats.get("consultas_fallidas"):
        with st.expander(f"{stats['consultas_fallidas']} consultas fallaron"):
            for line in stats.get("errores", [])[:10]:
                st.text(line)

    if with_person < len(data):
        st.markdown('<div class="lf-note">El nombre del responsable solo aparece cuando el '
                    'negocio lo publica en su web. Donde no consta, el campo queda vacío: '
                    'preferimos un hueco antes que un dato inventado.</div>',
                    unsafe_allow_html=True)

    st.write("")
    f1, f2, f3 = st.columns(3)
    only_wa = f1.checkbox("Solo con WhatsApp")
    only_mail = f2.checkbox("Solo con email")
    categories = sorted(data["sport"].unique().tolist())
    pick = f3.multiselect("Categoría", categories, default=categories)

    view = data.copy()
    if only_wa:
        view = view[view["phone_kind"].str.startswith("Móvil")]
    if only_mail:
        view = view[view["email"] != ""]
    if pick:
        view = view[view["sport"].isin(pick)]

    columns = ["name", "sport", "city", "province", "phone_display", "phone_kind",
               "email", "email_type", "contact_name", "contact_role", "website",
               "size_hint", "rating", "whatsapp_url", "message"]
    headers = {
        "name": "Nombre", "sport": "Categoría", "city": "Ciudad", "province": "Provincia",
        "phone_display": "Teléfono", "phone_kind": "Tipo", "email": "Email",
        "email_type": "Tipo email", "contact_name": "Responsable", "contact_role": "Cargo",
        "website": "Web", "size_hint": "Tamaño", "rating": "Rating",
        "whatsapp_url": "WhatsApp", "message": "Mensaje",
    }
    table = view[columns].rename(columns=headers)

    st.dataframe(
        table, use_container_width=True, height=440,
        column_config={
            "WhatsApp": st.column_config.LinkColumn("WhatsApp", display_text="Abrir chat"),
            "Web": st.column_config.LinkColumn("Web", display_text="Visitar"),
            "Mensaje": st.column_config.TextColumn("Mensaje", width="large"),
        },
    )

    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        table.to_excel(writer, index=False, sheet_name="Leads")
        wa_rows = view[view["phone_kind"].str.startswith("Móvil")][
            ["phone_e164", "name", "message"]
        ].copy()
        wa_rows.columns = ["Movil", "Club", "Mensaje"]
        wa_rows.to_excel(writer, index=False, sheet_name="Envio masivo")
        mail_rows = view[view["email"] != ""][["email", "name", "city", "sport"]].copy()
        mail_rows.columns = ["Email", "Club", "Ciudad", "Categoria"]
        mail_rows.to_excel(writer, index=False, sheet_name="Email")

    d1, d2 = st.columns(2)
    d1.download_button("Descargar Excel", buffer.getvalue(),
                       file_name=f"leads_{stamp}.xlsx", use_container_width=True,
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    d2.download_button("Descargar CSV", table.to_csv(index=False).encode("utf-8"),
                       file_name=f"leads_{stamp}.csv", mime="text/csv",
                       use_container_width=True)

    st.caption("El Excel trae tres hojas: todos los leads, «Envio masivo» "
               "(número, nombre y mensaje) y «Email». Verifica los emails antes "
               "de un envío masivo para no dañar la reputación de tu dominio.")
else:
    st.info("Configura la búsqueda y pulsa **Generar leads** para empezar.")
