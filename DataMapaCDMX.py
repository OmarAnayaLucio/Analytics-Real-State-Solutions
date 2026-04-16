"""
Mapa Interactivo CDMX - Precio Promedio por Metro Cuadrado por Colonia
=======================================================================
Dependencias:
    pip install folium geopandas pandas requests shapely branca

Uso:
    python mapa_cdmx_precio_m2.py

Genera un archivo 'mapa_cdmx.html' que puedes abrir en cualquier navegador.

Nota sobre los datos:
    - El GeoJSON de colonias se descarga desde el portal de datos abiertos de la CDMX.
    - Los precios de ejemplo son ficticios y están organizados por alcaldía para
      que puedas reemplazarlos fácilmente con datos reales (p.ej. de Lamudi,
      Inmuebles24, Propiedades.com o tu propio dataset).
"""

import json
import math
import random
import urllib.request
from pathlib import Path

import branca.colormap as cm
import folium
import geopandas as gpd
import pandas as pd

# ──────────────────────────────────────────────────────────────────────────────
# 1. DATOS DE PRECIOS POR COLONIA
#    Reemplaza este diccionario (o carga un CSV) con tus datos reales.
#    Formato: { "NOMBRE_COLONIA": precio_promedio_m2_en_pesos }
#
#    Fuentes sugeridas para datos reales:
#      • Datos abiertos CDMX:  https://datos.cdmx.gob.mx
#      • SHF (Sociedad Hipotecaria Federal): https://www.shf.gob.mx
#      • Scraping de portales inmobiliarios (Lamudi, Inmuebles24, etc.)
# ──────────────────────────────────────────────────────────────────────────────

# Precios base por alcaldía (MXN/m²) — valores aproximados de mercado 2024
PRECIOS_BASE_ALCALDIA = {
    "MIGUEL HIDALGO":       85_000,
    "BENITO JUAREZ":        75_000,
    "CUAUHTEMOC":           65_000,
    "ALVARO OBREGON":       55_000,
    "COYOACAN":             60_000,
    "TLALPAN":              45_000,
    "XOCHIMILCO":           28_000,
    "MILPA ALTA":           18_000,
    "TLAHUAC":              22_000,
    "IZTAPALAPA":           25_000,
    "IZTACALCO":            35_000,
    "VENUSTIANO CARRANZA":  38_000,
    "GUSTAVO A MADERO":     30_000,
    "AZCAPOTZALCO":         40_000,
    "MAGDALENA CONTRERAS":  42_000,
    "CUAJIMALPA":           68_000,
}

# Colonias icónicas con precios conocidos (MXN/m²)
PRECIOS_CONOCIDOS = {
    "POLANCO":                    130_000,
    "LOMAS DE CHAPULTEPEC":       120_000,
    "SANTA FE":                   95_000,
    "CONDESA":                    90_000,
    "ROMA NORTE":                 88_000,
    "ROMA SUR":                   80_000,
    "NARVARTE PONIENTE":          72_000,
    "NARVARTE ORIENTE":           68_000,
    "DEL VALLE NORTE":            70_000,
    "DEL VALLE CENTRO":           70_000,
    "DEL VALLE SUR":              65_000,
    "NAPOLES":                    68_000,
    "INSURGENTES MIXCOAC":        60_000,
    "MIXCOAC":                    58_000,
    "SAN ANGEL":                  75_000,
    "PEDREGAL DE CARRASCO":       55_000,
    "COYOACAN":                   62_000,
    "XOCO":                       65_000,
    "HIPÓDROMO":                  85_000,
    "HIPÓDROMO CONDESA":          88_000,
    "JUÁREZ":                     78_000,
    "CENTRO HISTÓRICO":           50_000,
    "TEPITO":                     25_000,
    "DOCTORES":                   40_000,
    "OBRERA":                     38_000,
    "GUERRERO":                   32_000,
    "SANTA MARIA LA RIBERA":      55_000,
    "SAN RAFAEL":                 55_000,
    "TABACALERA":                 52_000,
    "CUAUHTÉMOC":                 65_000,
    "ANZURES":                    75_000,
    "IRRIGACIÓN":                 72_000,
    "GRANADA":                    78_000,
    "AMPLIACIÓN GRANADA":         72_000,
    "BOSQUES DE LAS LOMAS":      115_000,
    "INTERLOMAS":                 80_000,
    "PERALVILLO":                 28_000,
    "LINDAVISTA":                 42_000,
    "VALLEJO":                    35_000,
    "INDUSTRIAL VALLEJO":         30_000,
    "ECHEGARAY":                  45_000,
    "TIZAPÁN":                    68_000,
    "FLORIDA":                    70_000,
    "EXTREMADURA INSURGENTES":    72_000,
    "CIUDAD DE LOS DEPORTES":     68_000,
    "PORTALES":                   55_000,
    "PORTALES NORTE":             55_000,
    "PORTALES SUR":               52_000,
    "IZTAPALAPA CENTRO":          24_000,
    "PEÑÓN DE LOS BAÑOS":         30_000,
    "AGRÍCOLA ORIENTAL":          28_000,
    "XOCHIMILCO CENTRO":          26_000,
    "MILPA ALTA CENTRO":          17_000,
}


def generar_precio(nombre_colonia: str, nombre_alcaldia: str) -> int:
    """
    Devuelve el precio/m² de una colonia.
    Si hay dato conocido lo usa; si no, genera uno basado en la alcaldía
    con variación aleatoria (±20 %) usando el nombre como semilla.
    """
    nombre_upper = nombre_colonia.upper().strip()

    # Buscar coincidencia exacta o parcial en precios conocidos
    for k, v in PRECIOS_CONOCIDOS.items():
        if k in nombre_upper or nombre_upper in k:
            rng = random.Random(hash(nombre_colonia))
            variacion = rng.uniform(0.92, 1.08)
            return int(v * variacion)

    # Usar precio base de la alcaldía con variación
    alcaldia_upper = nombre_alcaldia.upper().strip()
    base = 35_000  # fallback
    for k, v in PRECIOS_BASE_ALCALDIA.items():
        if k in alcaldia_upper or alcaldia_upper in k:
            base = v
            break

    rng = random.Random(hash(nombre_colonia + nombre_alcaldia))
    variacion = rng.uniform(0.80, 1.20)
    return int(base * variacion)


# ──────────────────────────────────────────────────────────────────────────────
# 2. DESCARGA DEL GEOJSON DE COLONIAS CDMX
# ──────────────────────────────────────────────────────────────────────────────

GEOJSON_LOCAL = Path("colonias_cdmx.geojson")

# ── Fuentes en orden de prioridad ──────────────────────────────────────────
# Fuente 1: API oficial datos abiertos CDMX (OpenDataSoft) — sin límite de registros
# Fuente 2: JuveCampos/Shapes_Resiliencia_CDMX_CIDE — colonias con geometrías CDMX
# Fuente 3: Portal datos abiertos CDMX (descarga directa)
GEOJSON_URLS = [
    # Portal de Datos Abiertos CDMX — API OpenDataSoft (descarga completa)
    "https://datos.cdmx.gob.mx/api/explore/v2.1/catalog/datasets/coloniascdmx/exports/geojson?limit=-1&timezone=UTC&use_labels=false&epsg=4326",
    # JuveCampos — Shapes Resiliencia CDMX (GitHub raw, colonias con geometrías)
    "https://raw.githubusercontent.com/JuveCampos/Shapes_Resiliencia_CDMX_CIDE/master/geojsons/Division%20Politica/Poligono_colonias.geojson",
    # Respaldo: otro repositorio con colonias CDMX
    "https://raw.githubusercontent.com/mxabierto/boundaryservice/master/data/geojson/09-COLONIAS.geojson",
]


def obtener_geojson() -> gpd.GeoDataFrame:
    """Descarga (o lee desde caché local) el GeoJSON de colonias CDMX."""
    if GEOJSON_LOCAL.exists():
        print("✔  Usando GeoJSON local (caché).")
        gdf = gpd.read_file(GEOJSON_LOCAL)
        print(f"   {len(gdf)} colonias cargadas.")
        print(f"   Columnas disponibles: {list(gdf.columns)}")
        return gdf

    print("⬇  Descargando GeoJSON de colonias CDMX …")
    last_error = None

    for i, url in enumerate(GEOJSON_URLS, 1):
        try:
            print(f"   Intentando fuente {i}/{len(GEOJSON_URLS)}: {url[:80]}…")
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "Mozilla/5.0 (compatible; MapaCDMX/1.0)"},
            )
            with urllib.request.urlopen(req, timeout=30) as response:
                data = response.read()
            GEOJSON_LOCAL.write_bytes(data)
            print(f"✔  Descarga completada desde fuente {i}.")
            gdf = gpd.read_file(GEOJSON_LOCAL)
            print(f"   {len(gdf)} colonias cargadas.")
            print(f"   Columnas disponibles: {list(gdf.columns)}")
            return gdf
        except Exception as e:
            last_error = e
            print(f"   ✗ Fuente {i} falló: {e}")

    # Todas las fuentes fallaron
    raise RuntimeError(
        "No se pudo descargar el GeoJSON desde ninguna fuente.\n\n"
        "Opciones manuales:\n"
        "  1. Descarga desde el portal de datos abiertos CDMX:\n"
        "     https://datos.cdmx.gob.mx/explore/dataset/coloniascdmx/export/\n"
        "     (botón 'GeoJSON') → guarda como 'colonias_cdmx.geojson'\n\n"
        "  2. O desde GitHub:\n"
        "     https://github.com/JuveCampos/Shapes_Resiliencia_CDMX_CIDE\n"
        "     carpeta: sig/Division Politica/Colonias/colonias.geojson\n\n"
        f"Último error: {last_error}"
    )


# ──────────────────────────────────────────────────────────────────────────────
# 3. PREPARAR DATAFRAME CON PRECIOS
# ──────────────────────────────────────────────────────────────────────────────

def preparar_datos(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Detecta columnas de nombre/alcaldía y agrega columna de precio."""

    # Detectar columna de nombre de colonia
    candidatos_colonia = [
        c for c in gdf.columns
        if any(k in c.lower() for k in ["colonia", "nom_col", "nombre", "col_"])
    ]
    candidatos_alcaldia = [
        c for c in gdf.columns
        if any(k in c.lower() for k in ["alcaldia", "municipio", "delegacion", "nom_mun", "mun"])
    ]

    col_nombre   = candidatos_colonia[0]  if candidatos_colonia  else gdf.columns[0]
    col_alcaldia = candidatos_alcaldia[0] if candidatos_alcaldia else gdf.columns[1]

    print(f"   Columna colonia   → '{col_nombre}'")
    print(f"   Columna alcaldía  → '{col_alcaldia}'")

    gdf = gdf.copy()
    gdf["COLONIA"]   = gdf[col_nombre].astype(str).str.strip().str.title()
    gdf["ALCALDIA"]  = gdf[col_alcaldia].astype(str).str.strip().str.title()

    gdf["precio_m2"] = gdf.apply(
        lambda r: generar_precio(r["COLONIA"], r["ALCALDIA"]), axis=1
    )

    # Asegurarse de que el CRS sea WGS84 para Folium
    if gdf.crs is not None and gdf.crs.to_epsg() != 4326:
        gdf = gdf.to_crs(epsg=4326)

    return gdf


# ──────────────────────────────────────────────────────────────────────────────
# 4. CREAR MAPA INTERACTIVO CON FOLIUM
# ──────────────────────────────────────────────────────────────────────────────

def crear_mapa(gdf: gpd.GeoDataFrame, output_path: str = "mapa_cdmx.html") -> None:
    """Genera el mapa choroplético interactivo y lo guarda como HTML."""

    precio_min = int(gdf["precio_m2"].min())
    precio_max = int(gdf["precio_m2"].max())
    print(f"\n   Rango de precios: ${precio_min:,} – ${precio_max:,} MXN/m²")

    # Colormap: verde (barato) → amarillo → rojo (caro)
    colormap = cm.LinearColormap(
        colors=["#2ecc71", "#f1c40f", "#e67e22", "#e74c3c", "#8e44ad"],
        vmin=precio_min,
        vmax=precio_max,
        caption="Precio promedio por m² (MXN)",
    )

    # Centrar mapa en CDMX
    mapa = folium.Map(
        location=[19.4326, -99.1332],
        zoom_start=11,
        tiles="CartoDB positron",
        prefer_canvas=True,
    )

    # Capa de tiles alternativa (oscura) para toggle
    folium.TileLayer(
        tiles="CartoDB dark_matter",
        name="Mapa oscuro",
        show=False,
    ).add_to(mapa)

    folium.TileLayer(
        tiles="OpenStreetMap",
        name="OpenStreetMap",
        show=False,
    ).add_to(mapa)

    # ── Tooltip personalizado ──────────────────────────────────────────────
    def estilo(feature):
        precio = feature["properties"].get("precio_m2", 0)
        return {
            "fillColor":   colormap(precio),
            "color":       "#333333",
            "weight":      0.4,
            "fillOpacity": 0.75,
        }

    def hover_estilo(feature):
        return {
            "fillColor":   colormap(feature["properties"].get("precio_m2", 0)),
            "color":       "#ffffff",
            "weight":      2.0,
            "fillOpacity": 0.90,
        }

    # Convertir a GeoJSON para Folium (serializar precio_m2)
    geojson_data = json.loads(gdf.to_json())

    folium.GeoJson(
        geojson_data,
        name="Precio por m²",
        style_function=estilo,
        highlight_function=hover_estilo,
        tooltip=folium.GeoJsonTooltip(
            fields=["COLONIA", "ALCALDIA", "precio_m2"],
            aliases=["🏘 Colonia:", "🏛 Alcaldía:", "💰 Precio/m²:"],
            localize=True,
            sticky=True,
            labels=True,
            style=(
                "background-color: #ffffff;"
                "color: #1a1a2e;"
                "font-family: 'Segoe UI', sans-serif;"
                "font-size: 13px;"
                "border-radius: 6px;"
                "border: 1px solid #ddd;"
                "padding: 8px 12px;"
                "box-shadow: 2px 2px 8px rgba(0,0,0,0.15);"
            ),
            max_width=280,
        ),
        popup=folium.GeoJsonPopup(
            fields=["COLONIA", "ALCALDIA", "precio_m2"],
            aliases=["Colonia", "Alcaldía", "Precio promedio / m²"],
            localize=True,
            labels=True,
            style=(
                "background-color: #ffffff;"
                "color: #1a1a2e;"
                "font-family: 'Segoe UI', sans-serif;"
                "font-size: 14px;"
                "border-radius: 8px;"
                "border: none;"
                "box-shadow: 0 4px 16px rgba(0,0,0,0.2);"
            ),
            max_width=320,
        ),
    ).add_to(mapa)

    # Colorbar
    colormap.add_to(mapa)

    # Control de capas
    folium.LayerControl(collapsed=False).add_to(mapa)

    # ── Panel de estadísticas (HTML personalizado) ─────────────────────────
    top5 = (
        gdf[["COLONIA", "ALCALDIA", "precio_m2"]]
        .sort_values("precio_m2", ascending=False)
        .head(5)
    )
    bot5 = (
        gdf[["COLONIA", "ALCALDIA", "precio_m2"]]
        .sort_values("precio_m2")
        .head(5)
    )

    def filas_html(df, emoji):
        rows = ""
        for _, r in df.iterrows():
            rows += (
                f"<tr>"
                f"<td style='padding:3px 6px'>{emoji} {r['COLONIA']}</td>"
                f"<td style='padding:3px 6px;color:#888'>{r['ALCALDIA']}</td>"
                f"<td style='padding:3px 6px;text-align:right;font-weight:600'>"
                f"${r['precio_m2']:,.0f}</td>"
                f"</tr>"
            )
        return rows

    stats_html = f"""
    <div id="stats-panel" style="
        position: fixed;
        bottom: 40px;
        right: 12px;
        z-index: 1000;
        background: rgba(255,255,255,0.96);
        backdrop-filter: blur(6px);
        border-radius: 12px;
        padding: 16px 18px;
        box-shadow: 0 4px 20px rgba(0,0,0,0.18);
        font-family: 'Segoe UI', sans-serif;
        font-size: 12.5px;
        color: #1a1a2e;
        max-width: 340px;
        border: 1px solid #e5e5e5;
    ">
      <div style="font-size:15px;font-weight:700;margin-bottom:10px;
                  border-bottom:2px solid #e74c3c;padding-bottom:6px">
        🏙 Precios CDMX — Resumen
      </div>
      <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px;margin-bottom:12px">
        <div style="background:#f8f9fa;border-radius:8px;padding:8px;text-align:center">
          <div style="font-size:10px;color:#888;text-transform:uppercase">Mínimo</div>
          <div style="font-size:14px;font-weight:700;color:#2ecc71">${precio_min:,}</div>
        </div>
        <div style="background:#f8f9fa;border-radius:8px;padding:8px;text-align:center">
          <div style="font-size:10px;color:#888;text-transform:uppercase">Promedio</div>
          <div style="font-size:14px;font-weight:700;color:#e67e22">
            ${int(gdf["precio_m2"].mean()):,}
          </div>
        </div>
        <div style="background:#f8f9fa;border-radius:8px;padding:8px;text-align:center">
          <div style="font-size:10px;color:#888;text-transform:uppercase">Máximo</div>
          <div style="font-size:14px;font-weight:700;color:#e74c3c">${precio_max:,}</div>
        </div>
      </div>

      <div style="font-weight:600;margin-bottom:4px">🔺 Top 5 más caras (MXN/m²)</div>
      <table style="width:100%;border-collapse:collapse;margin-bottom:10px;font-size:11.5px">
        {filas_html(top5, "💎")}
      </table>

      <div style="font-weight:600;margin-bottom:4px">🔻 Top 5 más económicas (MXN/m²)</div>
      <table style="width:100%;border-collapse:collapse;font-size:11.5px">
        {filas_html(bot5, "🏠")}
      </table>

      <div style="margin-top:10px;font-size:10px;color:#aaa;text-align:center">
        * Datos de muestra — reemplaza con tu dataset real
      </div>
    </div>
    """

    mapa.get_root().html.add_child(folium.Element(stats_html))

    # ── Guardar ────────────────────────────────────────────────────────────
    mapa.save(output_path)
    print(f"\n✅  Mapa guardado en → '{output_path}'")
    print("   Ábrelo en tu navegador para explorar los precios por colonia.")


# ──────────────────────────────────────────────────────────────────────────────
# 5. FUNCIÓN EXTRA: CARGAR TUS PROPIOS DATOS DESDE CSV
# ──────────────────────────────────────────────────────────────────────────────

def cargar_precios_desde_csv(ruta_csv: str) -> dict:
    """
    Carga precios desde un CSV con columnas 'colonia' y 'precio_m2'.
    Úsala así:
        precios = cargar_precios_desde_csv("mis_precios.csv")
        PRECIOS_CONOCIDOS.update(precios)

    Formato del CSV:
        colonia,precio_m2
        Polanco,130000
        Condesa,90000
        ...
    """
    df = pd.read_csv(ruta_csv)
    df.columns = [c.lower().strip() for c in df.columns]
    return dict(zip(df["colonia"].str.upper(), df["precio_m2"].astype(int)))


# ──────────────────────────────────────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("  MAPA INTERACTIVO CDMX — Precio promedio m² por colonia")
    print("=" * 60)

    # Opcional: cargar precios reales desde CSV
    # PRECIOS_CONOCIDOS.update(cargar_precios_desde_csv("mis_precios.csv"))

    gdf = obtener_geojson()
    gdf = preparar_datos(gdf)
    crear_mapa(gdf, output_path="mapa_cdmx.html")
