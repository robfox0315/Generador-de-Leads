"""
LeadForge — Plataforma de generación y enriquecimiento de leads B2B.

Ejecutar:  streamlit run app.py
"""

from __future__ import annotations

import io
from datetime import datetime

import pandas as pd
import streamlit as st

APP_VERSION = "4.0"

# --- Comprobación de que todos los módulos están al día -----------------------
_MISSING: list[str] = []
try:
    import lead_engine as _engine
    if getattr(_engine, "__version__", "0") != APP_VERSION:
        _MISSING.append("lead_engine.py")
except ImportError:
    _MISSING.append("lead_engine.py")
try:
    import storage as _storage
    if getattr(_storage, "__version__", "0") != APP_VERSION:
        _MISSING.append("storage.py")
except ImportError:
    _MISSING.append("storage.py")
try:
    import catalog as _catalog
    if getattr(_catalog, "__version__", "0") != APP_VERSION:
        _MISSING.append("catalog.py")
except ImportError:
    _MISSING.append("catalog.py")
try:
    import osm_provider as _osm
    if getattr(_osm, "__version__", "0") != APP_VERSION:
        _MISSING.append("osm_provider.py")
except ImportError:
    _MISSING.append("osm_provider.py")

if _MISSING:
    st.set_page_config(page_title="LeadForge", page_icon="⚡")
    st.error("### Faltan archivos o están desactualizados")
    st.markdown(
        "Estos módulos no están en la versión **%s**:\n\n%s\n\n"
        "**Solución:** sube al repositorio la versión más reciente de esos archivos "
        "(todos en la misma carpeta que `app.py`) y pulsa *Reboot app*."
        % (APP_VERSION, "\n".join(f"- `{m}`" for m in _MISSING))
    )
    st.stop()

import storage
from catalog import SECTORS, all_terms, cities_for
from lead_engine import (
    COUNTRIES,
    DEFAULT_TEMPLATE,
    TEMPLATE_VARIABLES,
    SerpApiError,
    check_account,
    clear_cache,
    enrich_from_names,
    generate_leads,
    normalize_key,
    parse_phone,
    validate_api_key,
    validate_template,
)

st.set_page_config(page_title="LeadForge", page_icon="⚡",
                   layout="wide", initial_sidebar_state="expanded")

ACCENT = st.session_state.setdefault("accent", "#FF4D17")

st.markdown(
    f"""
    <style>
      @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600&family=Inter:wght@400;500;600;800&display=swap');

      html, body, [class*="css"], .stApp {{ font-family: 'Inter', system-ui, sans-serif; }}
      .block-container {{ padding-top: 2.2rem; max-width: 1400px; }}

      /* Cabecera */
      .lf-head {{
        display:flex; align-items:flex-end; justify-content:space-between;
        border-bottom:1px solid rgba(255,255,255,.09); padding-bottom:1.1rem; margin-bottom:.4rem;
      }}
      .lf-brand {{ font-weight:800; font-size:1.9rem; letter-spacing:-.03em; line-height:1; }}
      .lf-brand span {{ color:{ACCENT}; }}
      .lf-tag {{ color:#7F8896; font-size:.87rem; margin-top:.45rem; max-width:640px; line-height:1.5; }}
      .lf-badge {{
        font-family:'IBM Plex Mono',monospace; font-size:.7rem; letter-spacing:.08em;
        text-transform:uppercase; color:{ACCENT}; border:1px solid {ACCENT}44;
        padding:.28rem .6rem; border-radius:3px; white-space:nowrap;
      }}

      /* Tarjetas de métrica */
      .lf-kpi {{
        border:1px solid rgba(255,255,255,.09); border-top:2px solid {ACCENT};
        background:linear-gradient(180deg, rgba(255,255,255,.035), rgba(255,255,255,.012));
        padding:.85rem 1rem .8rem; border-radius:5px; height:100%;
      }}
      .lf-kpi .v {{ font-family:'IBM Plex Mono',monospace; font-size:1.7rem; font-weight:600; line-height:1.1; }}
      .lf-kpi .l {{ font-size:.68rem; text-transform:uppercase; letter-spacing:.1em; color:#7F8896; margin-top:.3rem; }}

      /* Avisos */
      .lf-note, .lf-warn, .lf-ok {{
        padding:.8rem 1rem; border-radius:4px; font-size:.87rem; line-height:1.55; margin:.3rem 0;
      }}
      .lf-note {{ border-left:3px solid {ACCENT}; background:rgba(255,77,23,.07); }}
      .lf-warn {{ border-left:3px solid #E5A50A; background:rgba(229,165,10,.09); }}
      .lf-ok   {{ border-left:3px solid #2EA043; background:rgba(46,160,67,.09); }}

      /* Barra de cuota */
      .lf-quota {{ border:1px solid rgba(255,255,255,.09); border-radius:5px; padding:.7rem .85rem; }}
      .lf-quota .top {{ display:flex; justify-content:space-between; font-size:.75rem; color:#7F8896;
        text-transform:uppercase; letter-spacing:.08em; margin-bottom:.45rem; }}
      .lf-quota .num {{ font-family:'IBM Plex Mono',monospace; color:#E8EAED; font-weight:600; }}
      .lf-bar {{ height:6px; background:rgba(255,255,255,.09); border-radius:3px; overflow:hidden; }}
      .lf-bar i {{ display:block; height:100%; border-radius:3px; }}

      .lf-section {{ font-size:.72rem; text-transform:uppercase; letter-spacing:.12em;
        color:#7F8896; font-weight:600; margin:.2rem 0 .5rem; }}

      div[data-testid="stDataFrame"] {{ font-family:'IBM Plex Mono',monospace; font-size:.82rem; }}
      .stTabs [data-baseweb="tab"] {{ font-weight:600; letter-spacing:.01em; }}
      .stTabs [aria-selected="true"] {{ color:{ACCENT} !important; }}
      section[data-testid="stSidebar"] {{ border-right:1px solid rgba(255,255,255,.07); }}
    </style>
    """,
    unsafe_allow_html=True,
)

st.markdown(
    '<div class="lf-head"><div>'
    '<div class="lf-brand">LEAD<span>FORGE</span></div>'
    '<div class="lf-tag">Generación y enriquecimiento de leads B2B. Teléfono, WhatsApp, '
    'web, email y responsable — extraídos de fuentes verificables, nunca inventados.</div>'
    '</div><div class="lf-badge">datos verificables</div></div>',
    unsafe_allow_html=True,
)


def kpi_row(items: list[tuple]) -> None:
    for col, (value, label) in zip(st.columns(len(items)), items):
        col.markdown(f'<div class="lf-kpi"><div class="v">{value}</div>'
                     f'<div class="l">{label}</div></div>', unsafe_allow_html=True)


def show_run_errors(stats: dict, context: str = "") -> bool:
    """Muestra los fallos de forma visible. Devuelve True si todo falló."""
    failed = stats.get("consultas_fallidas", 0)
    errors = stats.get("errores", [])
    if not failed and not errors:
        return False

    first = errors[0] if errors else ""
    lower = first.lower()
    if "run out" in lower or "ran out" in lower:
        st.markdown(
            '<div class="lf-warn"><b>Tu cuenta de SerpApi se quedó sin búsquedas.</b><br>'
            'El plan gratuito son 250 al mes. Entra en serpapi.com para ver tu consumo o '
            'esperar a la renovación. Mientras tanto, activa «Reutilizar resultados recientes» '
            'para trabajar con lo ya descargado.</div>', unsafe_allow_html=True)
    elif "api key" in lower:
        st.markdown('<div class="lf-warn"><b>La API key no es válida.</b> '
                    'Cópiala de nuevo desde serpapi.com → API Key.</div>',
                    unsafe_allow_html=True)
    else:
        st.markdown(f'<div class="lf-warn"><b>{failed} consultas fallaron.</b> '
                    f'Primer error: {first}</div>', unsafe_allow_html=True)

    with st.expander(f"Detalle de errores ({len(errors)})"):
        for line in errors[:15]:
            st.text(line)
    return True


def export_workbook(view: pd.DataFrame, table: pd.DataFrame) -> bytes:
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        table.to_excel(writer, index=False, sheet_name="Leads")
        if "phone_kind" in view.columns:
            wa = view[view["phone_kind"].str.startswith("Móvil", na=False)][
                ["phone_e164", "name", "message"]].copy()
            wa.columns = ["Movil", "Nombre", "Mensaje"]
            wa.to_excel(writer, index=False, sheet_name="Envio masivo")
        if "email" in view.columns:
            mail = view[view["email"].fillna("") != ""][
                ["email", "name", "city", "sport"]].copy()
            mail.columns = ["Email", "Nombre", "Ciudad", "Categoria"]
            mail.to_excel(writer, index=False, sheet_name="Email")
    return buffer.getvalue()


COLUMNS = ["name", "sport", "city", "province", "phone_display", "phone_kind",
           "email", "email_type", "contact_name", "contact_role", "website",
           "size_hint", "rating", "whatsapp_url", "message"]
HEADERS = {"name": "Nombre", "sport": "Categoría", "city": "Ciudad", "province": "Provincia",
           "phone_display": "Teléfono", "phone_kind": "Tipo", "email": "Email",
           "email_type": "Tipo email", "contact_name": "Responsable",
           "contact_role": "Cargo", "website": "Web", "size_hint": "Tamaño",
           "rating": "Rating", "whatsapp_url": "WhatsApp", "message": "Mensaje"}


def render_results(state_key: str, stats_key: str) -> None:
    data = pd.DataFrame(st.session_state[state_key])
    stats = st.session_state.get(stats_key, {})

    mobiles = int(data["phone_kind"].str.startswith("Móvil", na=False).sum())
    with_email = int((data["email"].fillna("") != "").sum())
    with_person = int((data["contact_name"].fillna("") != "").sum())

    st.markdown('<div class="lf-section">Resultado</div>', unsafe_allow_html=True)
    kpi_row([
        (len(data), "leads"),
        (mobiles, "con WhatsApp"),
        (with_email, "con email"),
        (with_person, "con responsable"),
        (stats.get("consumidas", 0), "búsquedas usadas"),
    ])

    detail = []
    for key, label in (("descartados_no_club", "fuera de sector"),
                       ("duplicados", "duplicados"),
                       ("ya_contactados", "ya contactados"),
                       ("sin_telefono", "sin teléfono"),
                       ("no_encontrados", "no encontrados"),
                       ("webs_visitadas", "webs visitadas")):
        if stats.get(key):
            detail.append(f"{stats[key]} {label}")
    if detail:
        st.caption(" · ".join(detail))

    if stats.get("presupuesto_agotado"):
        st.markdown('<div class="lf-warn">Se alcanzó tu tope de búsquedas y la ejecución '
                    'se detuvo ahí. Sube el tope o reduce ciudades y términos.</div>',
                    unsafe_allow_html=True)

    if with_person < len(data):
        st.markdown('<div class="lf-note">El nombre del responsable solo aparece cuando el '
                    'negocio lo publica en su web. Donde no consta, el campo queda vacío: '
                    'preferimos un hueco antes que un dato inventado.</div>',
                    unsafe_allow_html=True)

    st.write("")
    f1, f2, f3 = st.columns([1, 1, 2])
    only_wa = f1.checkbox("Solo con WhatsApp", key=f"wa_{state_key}")
    only_mail = f2.checkbox("Solo con email", key=f"mail_{state_key}")
    cats = sorted(x for x in data["sport"].dropna().unique() if x)
    pick = f3.multiselect("Categoría", cats, default=cats, key=f"cat_{state_key}")

    view = data.copy()
    if only_wa:
        view = view[view["phone_kind"].str.startswith("Móvil", na=False)]
    if only_mail:
        view = view[view["email"].fillna("") != ""]
    if pick:
        view = view[view["sport"].isin(pick)]

    table = view[COLUMNS].rename(columns=HEADERS)
    st.dataframe(
        table, use_container_width=True, height=430, hide_index=True,
        column_config={
            "WhatsApp": st.column_config.LinkColumn("WhatsApp", display_text="Abrir chat"),
            "Web": st.column_config.LinkColumn("Web", display_text="Visitar"),
            "Mensaje": st.column_config.TextColumn("Mensaje", width="large"),
        },
    )

    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    d1, d2 = st.columns(2)
    d1.download_button("⬇  Excel (3 hojas)", export_workbook(view, table),
                       file_name=f"leads_{stamp}.xlsx", use_container_width=True,
                       key=f"xls_{state_key}",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    d2.download_button("⬇  CSV", table.to_csv(index=False).encode("utf-8"),
                       file_name=f"leads_{stamp}.csv", mime="text/csv",
                       use_container_width=True, key=f"csv_{state_key}")
    st.caption("El Excel trae «Leads», «Envio masivo» (número, nombre y mensaje) y «Email». "
               "Verifica los emails antes de un envío masivo.")

    st.write("")
    save_col, name_col = st.columns([1, 2])
    campaign_name = name_col.text_input(
        "Nombre de campaña", value=datetime.now().strftime("Campaña %d/%m"),
        key=f"camp_{state_key}", label_visibility="collapsed",
        placeholder="Nombre de la campaña")
    if save_col.button("💾  Guardar en mi base", use_container_width=True,
                       key=f"save_{state_key}"):
        result = storage.save_leads(view.to_dict("records"), campaign=campaign_name)
        st.markdown(
            f'<div class="lf-ok"><b>{result["nuevos"]} leads nuevos guardados.</b> '
            f'{result["duplicados"]} ya estaban · {result["completados"]} completados con '
            f'datos nuevos. Se excluirán automáticamente en próximas búsquedas.</div>',
            unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Barra lateral
# ---------------------------------------------------------------------------
with st.sidebar:
    st.markdown('<div class="lf-section">Fuente de datos</div>', unsafe_allow_html=True)
    source_label = st.radio(
        "Fuente", ["OpenStreetMap · gratis", "Google Maps · más cobertura"],
        label_visibility="collapsed",
        captions=["Sin API key ni límites. Menos teléfonos.",
                  "Requiere API key de SerpApi (250/mes gratis)."])
    source = "osm" if source_label.startswith("OpenStreetMap") else "google"
    needs_key = source == "google"

    st.divider()
    st.markdown('<div class="lf-section">Conexión</div>',
                unsafe_allow_html=True) if needs_key else None

    if not needs_key:
        st.markdown('<div class="lf-ok">Modo sin clave activo: puedes buscar ya, '
                    'sin registrarte en ningún sitio.</div>', unsafe_allow_html=True)

    try:
        stored_key = st.secrets.get("SERPAPI_KEY", "")
    except Exception:  # noqa: BLE001
        stored_key = ""

    api_key = st.text_input("API key de SerpApi", value=stored_key, type="password",
                            label_visibility="collapsed", placeholder="API key de SerpApi",
                            disabled=not needs_key) if needs_key else ""

    if api_key and needs_key:
        valid, reason = validate_api_key(api_key)
        if not valid:
            st.markdown(f'<div class="lf-warn">{reason}</div>', unsafe_allow_html=True)
        else:
            if st.button("Comprobar cuenta y cuota", use_container_width=True):
                st.session_state["account"] = check_account(api_key)

            account = st.session_state.get("account")
            if account and account.get("ok"):
                left, total = account.get("left", 0), account.get("total", 0) or 1
                pct = max(0, min(100, round(left / total * 100)))
                color = "#2EA043" if pct > 30 else ("#E5A50A" if pct > 10 else "#DA3633")
                st.markdown(
                    f'<div class="lf-quota"><div class="top"><span>búsquedas restantes</span>'
                    f'<span class="num">{left} / {total}</span></div>'
                    f'<div class="lf-bar"><i style="width:{pct}%;background:{color}"></i></div>'
                    f'</div>', unsafe_allow_html=True)
                if left <= 0:
                    st.markdown('<div class="lf-warn">Sin búsquedas disponibles. '
                                'Esta es la causa habitual de «no se encontraron leads».</div>',
                                unsafe_allow_html=True)
            elif account:
                st.markdown(f'<div class="lf-warn">{account.get("error")}</div>',
                            unsafe_allow_html=True)
    elif needs_key:
        st.caption("Gratis en serpapi.com — 250 búsquedas/mes.")

    country_code = st.selectbox("País", list(COUNTRIES.keys()),
                                format_func=lambda c: COUNTRIES[c].name)

    st.divider()
    st.markdown('<div class="lf-section">Marca</div>', unsafe_allow_html=True)
    company = st.text_input("Empresa", value="Competize")
    sender = st.text_input("Quién firma", value="Roberto")
    site = st.text_input("Web", value="competize.com/es")
    st.session_state["accent"] = st.color_picker("Color de acento", ACCENT)

    st.divider()
    st.markdown('<div class="lf-section">Ajustes</div>', unsafe_allow_html=True)
    pages = st.slider("Páginas por búsqueda", 1, 3, 1)
    max_searches = st.number_input("Tope de búsquedas", 10, 1000, 200, step=10)
    only_phone = st.checkbox("Solo con teléfono", value=True)
    use_cache = st.checkbox("Reutilizar resultados recientes", value=True,
                            help="Ahorra cuota: no repite búsquedas de los últimos 3 días.")
    enrich_web = st.checkbox("Buscar email y responsable en la web", value=True)
    enrich_limit = st.slider("Máx. webs a visitar", 10, 150, 40, 10, disabled=not enrich_web)
    enrich_workers = st.slider("Peticiones en paralelo", 1, 16, 8, disabled=not enrich_web)

    st.divider()
    if st.button("Vaciar caché", use_container_width=True):
        st.success(f"{clear_cache()} respuestas eliminadas.")

# ---------------------------------------------------------------------------
# Pestañas
# ---------------------------------------------------------------------------
tab_search, tab_file, tab_base, tab_help = st.tabs(
    ["  Buscar leads  ", "  Enriquecer mi lista  ", "  Mi base  ", "  Guía  "])

# --- PESTAÑA 1: BÚSQUEDA -----------------------------------------------------
with tab_search:
    st.write("")
    col_city, col_term = st.columns(2, gap="large")

    with col_city:
        st.markdown('<div class="lf-section">Dónde buscar</div>', unsafe_allow_html=True)
        available_cities = cities_for(country_code)
        cities = st.multiselect("Ciudades", available_cities,
                                default=available_cities[:3], label_visibility="collapsed",
                                placeholder="Elige una o varias ciudades")
        extra_cities = st.text_input("Añadir otras (separadas por coma)",
                                     placeholder="Ej. Vila-real, Motril")
        cities = list(cities) + [c.strip() for c in extra_cities.split(",") if c.strip()]

    with col_term:
        st.markdown('<div class="lf-section">Qué buscar</div>', unsafe_allow_html=True)
        sector = st.selectbox("Sector", list(SECTORS.keys()), label_visibility="collapsed")
        terms = st.multiselect("Términos", all_terms(), default=SECTORS[sector],
                               label_visibility="collapsed",
                               placeholder="Elige los tipos de negocio")
        extra_terms = st.text_input("Añadir otros (separados por coma)",
                                    placeholder="Ej. club de pickleball")
        terms = list(terms) + [t.strip() for t in extra_terms.split(",") if t.strip()]

    estimated = len(set(cities)) * len(set(terms)) * (pages if source == "google" else 1)
    if source == "osm":
        st.caption(f"**{len(set(cities))} ciudades × {len(set(terms))} términos** — "
                   f"OpenStreetMap no consume cuota. Tarda algo más por cortesía "
                   f"con el servicio (≈1,5 s por consulta).")
    account = st.session_state.get("account") or {}
    left = account.get("left") if account.get("ok") else None
    warn = ""
    if left is not None and estimated > left:
        warn = f"  ·  ⚠️ supera tus {left} búsquedas disponibles"
    elif estimated > max_searches:
        warn = "  ·  ⚠️ supera tu tope, se cortará antes"
    if source == "google":
        st.caption(f"Consumo estimado: **{estimated}** búsquedas "
                   f"({len(set(cities))} ciudades × {len(set(terms))} términos × {pages}){warn}")

    with st.expander("Mensaje de contacto"):
        st.caption("Variables: " + "  ".join("{" + v + "}" for v in TEMPLATE_VARIABLES))
        template = st.text_area("Plantilla", DEFAULT_TEMPLATE, height=130,
                                label_visibility="collapsed")
        tpl_ok, tpl_reason = validate_template(template)
        if not tpl_ok:
            st.warning(tpl_reason)

    with st.expander("Excluir contactos ya trabajados"):
        st.caption("Sube Excel/CSV de campañas anteriores. Se cruzan nombre y teléfono.")
        previous = st.file_uploader("Archivos previos", type=["xlsx", "csv"],
                                    accept_multiple_files=True, label_visibility="collapsed")

    exclude_keys: set[str] = set()
    exclude_phones: set[str] = set()

    auto_names, auto_phones = storage.known_fingerprints()
    if auto_names or auto_phones:
        use_history = st.checkbox(
            f"Excluir automáticamente los {len(auto_names)} leads que ya tengo guardados",
            value=True)
        if use_history:
            exclude_keys |= auto_names
            exclude_phones |= auto_phones

    if previous:
        country_obj = COUNTRIES[country_code]
        for upload in previous:
            try:
                frame = (pd.read_csv(upload) if upload.name.lower().endswith(".csv")
                         else pd.read_excel(upload))
                lowered = {str(c).strip().lower(): c for c in frame.columns}
                name_col = next((lowered[k] for k in ("club", "nombre", "name", "empresa",
                                                      "escuela") if k in lowered),
                                frame.columns[0])
                exclude_keys |= {normalize_key(v) for v in frame[name_col].dropna()}
                phone_col = next((lowered[k] for k in ("telefono", "teléfono", "movil",
                                                       "móvil", "phone", "whatsapp")
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
    if st.button("Generar leads", type="primary", use_container_width=True):
        key_ok, key_reason = (True, "") if source == "osm" else validate_api_key(api_key)
        if not key_ok:
            st.error(key_reason)
        elif not cities or not terms:
            st.error("Elige al menos una ciudad y un tipo de negocio.")
        elif not tpl_ok:
            st.error(tpl_reason)
        else:
            bar = st.progress(0.0, text="Iniciando…")
            try:
                leads, stats = generate_leads(
                    api_key=api_key, cities=cities, sports=terms,
                    country_code=country_code, pages=pages, enrich_web=enrich_web,
                    enrich_limit=enrich_limit, enrich_workers=enrich_workers,
                    template=template,
                    template_extra={"empresa": company, "remitente": sender, "web": site},
                    only_with_phone=only_phone, exclude_keys=exclude_keys,
                    exclude_phones=exclude_phones, max_searches=int(max_searches),
                    use_cache=use_cache, source=source,
                    progress=lambda f, t: bar.progress(min(max(f, 0.0), 1.0), text=t),
                )
                bar.empty()
                st.session_state["leads"] = [l.as_dict() for l in leads]
                st.session_state["stats"] = stats
                had_errors = show_run_errors(stats)
                if not leads and not had_errors:
                    st.markdown('<div class="lf-warn">No se encontraron negocios con esos '
                                'criterios. Prueba con términos más generales o con otra '
                                'ciudad — y revisa el filtro «Solo con teléfono».</div>',
                                unsafe_allow_html=True)
            except SerpApiError as exc:
                bar.empty()
                message = str(exc)
                if "run out" in message.lower():
                    st.markdown('<div class="lf-warn"><b>Tu cuenta de SerpApi se quedó sin '
                                'búsquedas este mes.</b> Es la causa más habitual de que no '
                                'aparezcan leads. Revisa tu consumo en serpapi.com.</div>',
                                unsafe_allow_html=True)
                else:
                    st.error(f"SerpApi: {message}")

    if st.session_state.get("leads"):
        st.divider()
        render_results("leads", "stats")

# --- PESTAÑA 2: ENRIQUECER ARCHIVO -------------------------------------------
with tab_file:
    st.write("")
    st.markdown('<div class="lf-note">Sube un Excel o CSV con una columna de <b>nombres de '
                'negocios</b>. LeadForge buscará cada uno en Google Maps y devolverá teléfono, '
                'web, dirección y — cuando esté publicado — email y responsable.</div>',
                unsafe_allow_html=True)
    st.write("")

    up_col, cfg_col = st.columns([2, 1], gap="large")

    with up_col:
        st.markdown('<div class="lf-section">Tu archivo</div>', unsafe_allow_html=True)
        source = st.file_uploader("Archivo con nombres", type=["xlsx", "csv"],
                                  label_visibility="collapsed")

    names: list[str] = []
    if source:
        try:
            frame = (pd.read_csv(source) if source.name.lower().endswith(".csv")
                     else pd.read_excel(source))
            with cfg_col:
                st.markdown('<div class="lf-section">Configuración</div>',
                            unsafe_allow_html=True)
                guess = next((c for c in frame.columns
                              if str(c).strip().lower() in
                              ("club", "nombre", "name", "empresa", "escuela")),
                             frame.columns[0])
                name_col = st.selectbox("Columna con los nombres", list(frame.columns),
                                        index=list(frame.columns).index(guess))
                hint = st.text_input("Pista de zona (opcional)", placeholder="Ej. Madrid",
                                     help="Mejora la precisión si tus nombres son ambiguos.")
                limit = st.slider("Cuántos procesar", 5, min(400, max(5, len(frame))),
                                  min(50, len(frame)))
            names = [str(v).strip() for v in frame[name_col].dropna().tolist()][:limit]
            st.caption(f"Archivo con **{len(frame)}** filas. Se procesarán **{len(names)}** "
                       f"nombres · consumo estimado: **{len(names)}** búsquedas.")
            st.dataframe(frame.head(5), use_container_width=True, hide_index=True)
        except Exception as exc:  # noqa: BLE001
            st.error(f"No se pudo leer el archivo: {exc}")

    st.write("")
    if st.button("Enriquecer lista", type="primary", use_container_width=True,
                 disabled=not names):
        key_ok, key_reason = validate_api_key(api_key)
        if not key_ok:
            st.error(key_reason)
        else:
            bar = st.progress(0.0, text="Buscando…")
            try:
                leads, stats = enrich_from_names(
                    api_key=api_key, names=names, country_code=country_code,
                    location_hint=hint, enrich_web=enrich_web,
                    enrich_workers=enrich_workers, use_cache=use_cache,
                    max_searches=int(max_searches),
                    progress=lambda f, t: bar.progress(min(max(f, 0.0), 1.0), text=t),
                )
                bar.empty()
                for lead in leads:
                    if lead.phone_e164:
                        from lead_engine import render_message, whatsapp_link
                        lead.message = render_message(
                            lead, DEFAULT_TEMPLATE,
                            {"empresa": company, "remitente": sender, "web": site})
                        if lead.phone_kind.startswith("Móvil"):
                            lead.whatsapp_url = whatsapp_link(lead.phone_e164, lead.message)
                st.session_state["file_leads"] = [l.as_dict() for l in leads]
                st.session_state["file_stats"] = stats
                had_errors = show_run_errors(stats)
                if stats.get("encontrados"):
                    rate = round(stats["encontrados"] / max(1, stats["buscados"]) * 100)
                    st.markdown(f'<div class="lf-ok">Se encontraron datos de '
                                f'<b>{stats["encontrados"]} de {stats["buscados"]}</b> '
                                f'negocios ({rate} %).</div>', unsafe_allow_html=True)
            except SerpApiError as exc:
                bar.empty()
                st.error(f"SerpApi: {exc}")

    if st.session_state.get("file_leads"):
        st.divider()
        render_results("file_leads", "file_stats")


# --- PESTAÑA 3: MI BASE (CRM) ------------------------------------------------
with tab_base:
    st.write("")
    base_stats = storage.stats()

    if not base_stats["total"]:
        st.markdown('<div class="lf-note">Todavía no has guardado ningún lead. Genera una '
                    'búsqueda y pulsa <b>Guardar en mi base</b> para empezar a construir tu '
                    'histórico: se deduplican solos y se excluyen de futuras búsquedas.</div>',
                    unsafe_allow_html=True)
    else:
        st.markdown('<div class="lf-section">Resumen de tu base</div>', unsafe_allow_html=True)
        kpi_row([
            (base_stats["total"], "leads guardados"),
            (base_stats["con_whatsapp"], "con WhatsApp"),
            (base_stats["con_email"], "con email"),
            (base_stats["con_responsable"], "con responsable"),
            (base_stats["score_medio"], "calidad media /100"),
        ])

        st.write("")
        st.markdown('<div class="lf-section">Embudo comercial</div>', unsafe_allow_html=True)
        funnel = base_stats["por_estado"]
        cols = st.columns(len(storage.STATUSES))
        for col, status in zip(cols, storage.STATUSES):
            count = funnel.get(status, 0)
            share = round(count / base_stats["total"] * 100) if base_stats["total"] else 0
            col.markdown(f'<div class="lf-kpi"><div class="v">{count}</div>'
                         f'<div class="l">{status}</div>'
                         f'<div class="l" style="color:{ACCENT}">{share}%</div></div>',
                         unsafe_allow_html=True)

        if base_stats["top_ciudades"]:
            st.write("")
            chart = pd.DataFrame(base_stats["top_ciudades"]).set_index("city")
            st.bar_chart(chart, height=200, color=ACCENT)

        st.divider()
        st.markdown('<div class="lf-section">Trabajar la base</div>', unsafe_allow_html=True)

        c1, c2, c3 = st.columns([1, 1, 2])
        flt_status = c1.selectbox("Estado", ["Todos", *storage.STATUSES])
        camp_list = storage.campaigns()
        flt_camp = c2.selectbox("Campaña", ["Todas", *camp_list]) if camp_list else "Todas"
        flt_search = c3.text_input("Buscar por nombre, ciudad o provincia",
                                   placeholder="Ej. Sevilla")

        rows = storage.fetch_leads(
            status="" if flt_status == "Todos" else flt_status,
            campaign="" if flt_camp == "Todas" else flt_camp,
            search=flt_search)

        if not rows:
            st.info("Ningún lead coincide con esos filtros.")
        else:
            base_df = pd.DataFrame(rows)
            display = base_df[["id", "score", "name", "sport", "city", "province",
                               "phone_display", "email", "contact_name", "status",
                               "campaign", "whatsapp_url"]].rename(columns={
                "id": "ID", "score": "Calidad", "name": "Nombre", "sport": "Categoría",
                "city": "Ciudad", "province": "Provincia", "phone_display": "Teléfono",
                "email": "Email", "contact_name": "Responsable", "status": "Estado",
                "campaign": "Campaña", "whatsapp_url": "WhatsApp"})

            st.dataframe(
                display, use_container_width=True, height=380, hide_index=True,
                column_config={
                    "Calidad": st.column_config.ProgressColumn(
                        "Calidad", min_value=0, max_value=100, format="%d"),
                    "WhatsApp": st.column_config.LinkColumn(
                        "WhatsApp", display_text="Abrir chat"),
                })
            st.caption(f"{len(rows)} leads · ordenados por calidad. "
                       "La calidad mide cuánta información accionable tenemos, "
                       "no la probabilidad de compra.")

            st.write("")
            st.markdown('<div class="lf-section">Actualizar estado</div>',
                        unsafe_allow_html=True)
            u1, u2, u3 = st.columns([2, 1, 1])
            options = {f"{r['id']} · {r['name']}": r["id"] for r in rows}
            chosen = u1.multiselect("Leads", list(options.keys()),
                                    label_visibility="collapsed",
                                    placeholder="Elige uno o varios leads")
            new_status = u2.selectbox("Nuevo estado", storage.STATUSES,
                                      label_visibility="collapsed")
            if u3.button("Aplicar", use_container_width=True, type="primary"):
                if chosen:
                    count = storage.update_status([options[c] for c in chosen], new_status)
                    st.success(f"{count} lead(s) movidos a «{new_status}».")
                    st.rerun()
                else:
                    st.warning("Selecciona al menos un lead.")

            st.write("")
            e1, e2 = st.columns(2)
            stamp = datetime.now().strftime("%Y%m%d_%H%M")
            e1.download_button("⬇  Exportar esta vista (CSV)",
                               display.to_csv(index=False).encode("utf-8"),
                               file_name=f"mi_base_{stamp}.csv", mime="text/csv",
                               use_container_width=True)
            full = pd.DataFrame(storage.export_all())
            e2.download_button("⬇  Copia de seguridad completa (CSV)",
                               full.to_csv(index=False).encode("utf-8"),
                               file_name=f"backup_leadforge_{stamp}.csv", mime="text/csv",
                               use_container_width=True)

        st.divider()
        st.markdown('<div class="lf-warn">En Streamlit Cloud el almacenamiento es efímero: '
                    'la base se reinicia con cada redespliegue. Descarga la copia de '
                    'seguridad con regularidad, o define la variable de entorno '
                    '<code>LEADFORGE_DB</code> apuntando a un volumen persistente.</div>',
                    unsafe_allow_html=True)
        with st.expander("Zona peligrosa"):
            st.caption("Borra todos los leads guardados. No se puede deshacer.")
            if st.checkbox("Entiendo que se borrará toda mi base"):
                if st.button("Vaciar base de datos", type="secondary"):
                    storage.reset_database()
                    st.success("Base vaciada.")
                    st.rerun()


# --- PESTAÑA 4: GUÍA ---------------------------------------------------------
with tab_help:
    st.write("")
    g1, g2 = st.columns(2, gap="large")

    with g1:
        st.markdown("##### Cómo empezar")
        st.markdown(
            "1. Pega tu **API key de SerpApi** en la barra lateral (gratis, 250 búsquedas/mes).\n"
            "2. Pulsa **Comprobar cuenta y cuota** para ver cuántas te quedan.\n"
            "3. En **Buscar leads**, elige ciudades y tipos de negocio.\n"
            "4. Revisa la tabla y descarga el Excel."
        )
        st.markdown("##### Si no aparecen leads")
        st.markdown(
            "- **Sin búsquedas disponibles** — la causa más común. Compruébalo con el botón "
            "de cuota.\n"
            "- **Filtro «Solo con teléfono»** activo y los negocios no lo publican.\n"
            "- **Términos demasiado específicos** — prueba con algo más general.\n"
            "- **Ciudad pequeña** — amplía a la capital de provincia."
        )

    with g2:
        st.markdown("##### Las tres hojas del Excel")
        st.markdown(
            "- **Leads** — todo lo encontrado, con mensaje personalizado.\n"
            "- **Envio masivo** — número, nombre y mensaje, en el formato que esperan las "
            "extensiones de WhatsApp Web.\n"
            "- **Email** — solo los que tienen correo real."
        )
        st.markdown("##### Antes de lanzar una campaña")
        st.markdown(
            "- **Verifica los emails** en reoon.com o verifalia.com: enviar a direcciones que "
            "rebotan daña la reputación de tu dominio.\n"
            "- **Comprueba 5 teléfonos** al azar en Google Maps.\n"
            "- **Incluye una vía de baja** en cada comunicación (RGPD / LSSI-CE)."
        )

    st.divider()
    st.markdown(
        '<div class="lf-note"><b>Principio de diseño:</b> ningún dato se inventa. Todo '
        'teléfono, email o nombre procede de Google Maps o de la web del propio negocio. '
        'Cuando un dato no existe, el campo queda vacío — un hueco es recuperable, un dato '
        'falso quema el contacto y la reputación de quien lo envía.</div>',
        unsafe_allow_html=True)
