# ⚡ LeadForge

Generador de leads B2B reales por **ciudad** y **sector**. Devuelve teléfono, WhatsApp,
web, email y responsable — todo extraído de fuentes verificables.

> **Principio de diseño:** ningún dato de contacto se inventa. Si un email o un nombre
> no está publicado, el campo queda vacío. Un hueco es recuperable; un dato falso quema
> el lead y la reputación de quien lo envía.

---

## Qué hace

| Etapa | Fuente | Resultado |
|---|---|---|
| 1. Búsqueda | Google Maps vía SerpApi | Nombre, teléfono, dirección, web, rating |
| 2. Normalización | Reglas por país | Teléfono en E.164 + clasificado móvil/fijo |
| 3. Localización | Código postal real | Provincia y ciudad (España) |
| 4. Enriquecimiento | Web propia del negocio | Email real y nombre del responsable si están publicados |
| 5. Filtrado | Lista de exclusión | Descarta lo que no es del sector, duplicados y ya contactados |
| 6. Salida | — | Excel con hoja lista para envío masivo + enlaces `wa.me` |

**Países soportados:** España, México, Colombia, Argentina, Chile, Perú.
Cada uno con su propia lógica de numeración (longitud, prefijo, cómo se detecta un móvil).

---

## Instalación local

```bash
git clone https://github.com/TU_USUARIO/leadforge.git
cd leadforge
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

Se abre en `http://localhost:8501`.

---

## Despliegue en Streamlit Community Cloud (gratis)

1. Sube el repositorio a GitHub.
2. Entra en [share.streamlit.io](https://share.streamlit.io) con tu cuenta de GitHub.
3. **New app** → elige el repositorio, rama `main`, archivo `app.py` → **Deploy**.
4. La API key se introduce desde la interfaz, así que no hace falta configurar secretos.

Si prefieres dejarla fija para tu equipo, crea `.streamlit/secrets.toml`:

```toml
SERPAPI_KEY = "tu_clave"
```

y léela en `app.py` con `st.secrets.get("SERPAPI_KEY", "")` como valor por defecto del campo.

---

## Uso

1. Pega tu **API key de SerpApi** (250 búsquedas gratis al mes en serpapi.com).
2. Elige **país**, escribe **ciudades** y **términos de búsqueda** (o usa un preset).
3. Opcional: sube Excel de campañas anteriores para **no repetir contactos**.
4. Ajusta la **plantilla de mensaje** con las variables disponibles.
5. **Generar leads** → revisa la tabla → descarga Excel o CSV.

La hoja **«Envio masivo»** del Excel sale con tres columnas (`Movil`, `Club`, `Mensaje`),
el formato que esperan las extensiones de envío por WhatsApp Web.

### Consumo de búsquedas

`ciudades × términos × páginas` = búsquedas de SerpApi.
Ejemplo: 3 ciudades × 6 términos × 1 página = **18 búsquedas** ≈ 360 negocios.

---

## Variables de la plantilla

| Variable | Contenido |
|---|---|
| `{club}` | Nombre del negocio |
| `{ciudad}` / `{provincia}` | Localización real |
| `{deporte}` | Categoría detectada |
| `{dolor}` | Punto de dolor según la categoría |
| `{contacto}` | Nombre del responsable (si está publicado) |
| `{saludo}` | `", Nombre"` si hay responsable; vacío si no |

---

## Arquitectura

```
leadforge/
├── app.py                 Interfaz Streamlit
├── lead_engine.py         Motor: búsqueda, normalización, scraping, mensajes
├── requirements.txt
└── .streamlit/config.toml Tema
```

`lead_engine.py` no depende de Streamlit: puede usarse desde un script, un cron
o una API sin tocar una línea.

```python
from lead_engine import generate_leads

leads, stats = generate_leads(
    api_key="...",
    cities=["Sevilla", "Granada"],
    sports=["club de futbol base"],
    country_code="es",
)
```

---

## Límites conocidos

- **El nombre del responsable** solo aparece si el negocio lo publica en su web.
  Google Maps no expone datos personales, y no se deduce ni se genera.
- **El email** se busca en la web propia del negocio. Verifícalo antes de un envío
  masivo (reoon.com, verifalia.com) para no dañar la reputación del dominio.
- **SerpApi tiene cuota**: el plan gratuito son 250 búsquedas al mes.
- El rastreo web respeta un límite de páginas por dominio y se salta el sitio si no responde.

## Cumplimiento

Los datos proceden de fuentes públicas. En comunicaciones comerciales B2B incluye
siempre una vía de baja y atiende las solicitudes de supresión (RGPD / LSSI-CE).

---

## Calidad y auditoría

El proyecto pasó una auditoría técnica antes del despliegue (ver `AUDITORIA.md`):
protección anti-SSRF, respeto de robots.txt, caché de API, reintentos con backoff,
tope de presupuesto, deduplicación por nombre y teléfono, y validación de emails.

```bash
python test_lead_engine.py     # 50 comprobaciones, no consume cuota de API
```

## Rendimiento

| Operación | v1 | v2 |
|---|---|---|
| Enriquecer 40 webs | hasta 20 min (secuencial) | 1-2 min (concurrente) |
| Repetir una búsqueda | consume cuota | gratis desde caché (3 días) |
| Consulta fallida | aborta todo | se aísla y continúa |
