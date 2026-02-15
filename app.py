# app.py
"""
Streamlit Leaflet (Folium) app to view Schenectady County parcels + ownership.

Default data source:
- NYS Tax Parcel Centroid Points (public), filtered to Schenectady County,
  includes ownership fields like PRIMARY_OWNER and mailing address fields.
  Source: NYS ITS Geospatial Services FeatureServer.  1

Optional:
- You can point the app to a parcel polygon FeatureServer layer you have access to.

Run:
  pip install -r requirements.txt
  streamlit run app.py
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple

import requests
import streamlit as st
from streamlit_folium import st_folium

import folium


DEFAULT_POINTS_LAYER_URL = (
    "https://gisservices.its.ny.gov/arcgis/rest/services/"
    "NYS_Tax_Parcel_Centroid_Points/FeatureServer/0"
)


@dataclass(frozen=True)
class BBox:
    west: float
    south: float
    east: float
    north: float

    def to_envelope(self) -> Dict[str, float]:
        return {"xmin": self.west, "ymin": self.south, "xmax": self.east, "ymax": self.north}

    def normalized(self) -> "BBox":
        w, e = sorted([self.west, self.east])
        s, n = sorted([self.south, self.north])
        return BBox(w, s, e, n)

    def clamp(self) -> "BBox":
        w = max(-180.0, min(180.0, self.west))
        e = max(-180.0, min(180.0, self.east))
        s = max(-90.0, min(90.0, self.south))
        n = max(-90.0, min(90.0, self.north))
        return BBox(w, s, e, n)

    def approx_area_deg2(self) -> float:
        b = self.normalized().clamp()
        return max(0.0, (b.east - b.west) * (b.north - b.south))


def _http_get_json(url: str, params: Dict[str, Any], timeout_s: int = 30) -> Dict[str, Any]:
    r = requests.get(url, params=params, timeout=timeout_s)
    r.raise_for_status()
    return r.json()


def _arcgis_query_geojson(
    layer_url: str,
    where: str,
    out_fields: str,
    bbox: Optional[BBox],
    result_record_count: int,
    result_offset: int,
) -> Dict[str, Any]:
    """
    Query ArcGIS FeatureServer layer and return GeoJSON.
    Uses bbox envelope if provided (in SR 4326) for fast, map-bounds loading.
    """
    query_url = f"{layer_url}/query"
    params: Dict[str, Any] = {
        "f": "geojson",
        "where": where,
        "outFields": out_fields,
        "returnGeometry": "true",
        "outSR": "4326",
        "resultRecordCount": result_record_count,
        "resultOffset": result_offset,
    }
    if bbox is not None:
        b = bbox.normalized().clamp()
        params.update(
            {
                "geometry": b.to_envelope(),
                "geometryType": "esriGeometryEnvelope",
                "inSR": "4326",
                "spatialRel": "esriSpatialRelIntersects",
            }
        )

    return _http_get_json(query_url, params=params)


def _arcgis_count(layer_url: str, where: str, bbox: Optional[BBox]) -> int:
    """
    Get count for a query (used to paginate).
    """
    query_url = f"{layer_url}/query"
    params: Dict[str, Any] = {
        "f": "json",
        "where": where,
        "returnCountOnly": "true",
    }
    if bbox is not None:
        b = bbox.normalized().clamp()
        params.update(
            {
                "geometry": b.to_envelope(),
                "geometryType": "esriGeometryEnvelope",
                "inSR": "4326",
                "spatialRel": "esriSpatialRelIntersects",
            }
        )
    data = _http_get_json(query_url, params=params)
    return int(data.get("count", 0))


@st.cache_data(show_spinner=False, ttl=300)
def fetch_features_geojson(
    layer_url: str,
    where: str,
    out_fields: str,
    bbox: Optional[BBox],
    max_features: int,
    page_size: int = 1000,
) -> Dict[str, Any]:
    """
    Fetch up to max_features features (GeoJSON FeatureCollection), with pagination.
    Cached for 5 minutes keyed on inputs.
    """
    total = _arcgis_count(layer_url, where, bbox)
    if total <= 0:
        return {"type": "FeatureCollection", "features": []}

    target = min(total, max_features)
    pages = int(math.ceil(target / page_size))

    features: List[Dict[str, Any]] = []
    for i in range(pages):
        offset = i * page_size
        remaining = target - offset
        rc = min(page_size, remaining)
        chunk = _arcgis_query_geojson(
            layer_url=layer_url,
            where=where,
            out_fields=out_fields,
            bbox=bbox,
            result_record_count=rc,
            result_offset=offset,
        )
        chunk_features = chunk.get("features", [])
        features.extend(chunk_features)
        if len(features) >= target:
            break

    return {"type": "FeatureCollection", "features": features[:target]}


def make_map(center: Tuple[float, float], zoom: int) -> folium.Map:
    m = folium.Map(location=center, zoom_start=zoom, control_scale=True, tiles="OpenStreetMap")
    folium.TileLayer("CartoDB positron", name="Positron").add_to(m)
    folium.TileLayer("CartoDB dark_matter", name="Dark").add_to(m)
    folium.LayerControl(collapsed=True).add_to(m)
    return m


def add_points_layer(
    m: folium.Map,
    geojson: Dict[str, Any],
    popup_fields: List[str],
    layer_name: str,
) -> None:
    """
    Render points as CircleMarkers via GeoJson + point_to_layer.
    """
    def _point_to_layer(feature: Dict[str, Any], latlng: Tuple[float, float]) -> folium.CircleMarker:
        props = feature.get("properties", {}) or {}
        lines = []
        for f in popup_fields:
            v = props.get(f)
            if v is None or v == "":
                continue
            lines.append(f"<b>{f}</b>: {v}")
        html = "<br/>".join(lines) if lines else "No attributes"
        return folium.CircleMarker(
            location=latlng,
            radius=4,
            weight=1,
            fill=True,
            fill_opacity=0.7,
            popup=folium.Popup(html, max_width=350),
            tooltip=str(props.get("PARCEL_ADDR") or props.get("PRINT_KEY") or props.get("SBL") or "Parcel"),
        )

    folium.GeoJson(
        geojson,
        name=layer_name,
        marker=folium.Marker(),
        tooltip=folium.GeoJsonTooltip(fields=[]),
        popup=folium.GeoJsonPopup(fields=[]),
        point_to_layer=_point_to_layer,
    ).add_to(m)


def bbox_from_folium_state(state: Dict[str, Any]) -> Optional[BBox]:
    bounds = state.get("bounds") if state else None
    if not bounds:
        return None
    sw = bounds.get("_southWest")
    ne = bounds.get("_northEast")
    if not sw or not ne:
        return None
    return BBox(west=float(sw["lng"]), south=float(sw["lat"]), east=float(ne["lng"]), north=float(ne["lat"]))


def main() -> None:
    st.set_page_config(page_title="Schenectady Parcels + Ownership", layout="wide")

    st.title("Schenectady County Parcels + Ownership (Streamlit + Leaflet)")
    st.caption(
        "Default layer = NYS Tax Parcel Centroid Points (public) filtered to Schenectady. "
        "If you have a parcel polygon FeatureServer, paste it in the sidebar."
    )

    with st.sidebar:
        st.header("Data source")

        mode = st.radio(
            "Layer type",
            options=["Centroid points (public)", "Parcel polygons (your service URL)"],
            index=0,
        )

        if mode == "Centroid points (public)":
            layer_url = DEFAULT_POINTS_LAYER_URL
            st.write("Using NYS centroid points FeatureServer.")
        else:
            layer_url = st.text_input(
                "Parcel polygon FeatureServer layer URL (…/FeatureServer/<layerId>)",
                value="",
                placeholder="https://…/arcgis/rest/services/…/FeatureServer/0",
            ).strip()

        st.divider()
        st.header("Filters")

        county_name = st.text_input("COUNTY_NAME", value="Schenectady").strip()
        owner_search = st.text_input("Owner contains (optional)", value="").strip()
        addr_search = st.text_input("Parcel address contains (optional)", value="").strip()

        st.divider()
        st.header("Performance")
        max_features = st.slider("Max features to load per map view", 500, 5000, 2000, step=250)
        min_zoom = st.slider("Only load when zoom ≥", 10, 18, 13, step=1)

        st.divider()
        st.header("Columns in popup")
        popup_fields = st.multiselect(
            "Fields",
            options=[
                "PRINT_KEY",
                "SBL",
                "PARCEL_ADDR",
                "PRIMARY_OWNER",
                "MAIL_ADDR",
                "MAIL_CITY",
                "MAIL_STATE",
                "MAIL_ZIP",
                "PROP_CLASS",
                "TOTAL_AV",
                "FULL_MARKET_VAL",
                "ACRES",
                "MUNI_NAME",
                "CITYTOWN_NAME",
            ],
            default=["PARCEL_ADDR", "PRIMARY_OWNER", "MAIL_ADDR", "MAIL_CITY", "MAIL_STATE", "MAIL_ZIP", "SBL"],
        )

    # Basic guards
    if mode != "Centroid points (public)" and not layer_url:
        st.warning("Paste your parcel polygon FeatureServer layer URL in the sidebar.")
        st.stop()

    # Map defaults centered on Schenectady County area
    center = (42.81, -73.94)
    zoom = 12

    col_map, col_results = st.columns([2, 1], gap="large")
    with col_map:
        m = make_map(center=center, zoom=zoom)
        st.write("Pan/zoom the map; features load for the current view when zoomed in enough.")

        map_state = st_folium(m, height=650, width=None)

    # Build WHERE clause
    where_parts = [f"COUNTY_NAME = '{county_name.replace(\"'\", \"''\")}'"]
    if owner_search:
        s = owner_search.replace("'", "''").upper()
        where_parts.append(f"UPPER(PRIMARY_OWNER) LIKE '%{s}%'")
    if addr_search:
        s = addr_search.replace("'", "''").upper()
        where_parts.append(f"UPPER(PARCEL_ADDR) LIKE '%{s}%'")
    where = " AND ".join(where_parts)

    # Decide whether to fetch based on zoom
    current_zoom = int(map_state.get("zoom", zoom)) if map_state else zoom
    bbox = bbox_from_folium_state(map_state)

    with col_results:
        st.subheader("Loaded")
        st.write(f"Zoom: **{current_zoom}** (min **{min_zoom}**)")
        st.code(where, language="sql")

        if bbox:
            st.write("Bounds (W,S,E,N):")
            st.code(f"{bbox.west:.5f}, {bbox.south:.5f}, {bbox.east:.5f}, {bbox.north:.5f}")

        if current_zoom < min_zoom:
            st.info("Zoom in to load parcels for the current view.")
            st.stop()

        if bbox and bbox.approx_area_deg2() > 2.0:
            st.warning("Your view is very large; zoom in more to avoid hitting record limits.")
            st.stop()

        out_fields = ",".join(sorted(set(popup_fields + ["PARCEL_ADDR", "PRIMARY_OWNER", "SBL", "PRINT_KEY"])))

        with st.spinner("Querying parcels…"):
            try:
                geojson = fetch_features_geojson(
                    layer_url=layer_url,
                    where=where,
                    out_fields=out_fields,
                    bbox=bbox,
                    max_features=max_features,
                )
            except requests.HTTPError as e:
                st.error(f"ArcGIS query failed: {e}")
                st.stop()
            except requests.RequestException as e:
                st.error(f"Network error: {e}")
                st.stop()

        feats = geojson.get("features", [])
        st.metric("Features", len(feats))

        if not feats:
            st.info("No features found for current view + filters.")
            st.stop()

        # Render second map with data (avoid re-render loop by keeping it simple)
        with col_map:
            m2 = make_map(center=center, zoom=current_zoom)
            add_points_layer(
                m=m2,
                geojson=geojson,
                popup_fields=popup_fields,
                layer_name=("Parcel points" if mode == "Centroid points (public)" else "Parcels"),
            )
            st_folium(m2, height=650, width=None, key="data_map")

        # Simple “table” preview
        st.subheader("Preview")
        rows = []
        for f in feats[:200]:
            p = f.get("properties", {}) or {}
            rows.append(
                {
                    "PARCEL_ADDR": p.get("PARCEL_ADDR"),
                    "PRIMARY_OWNER": p.get("PRIMARY_OWNER"),
                    "SBL": p.get("SBL"),
                    "PRINT_KEY": p.get("PRINT_KEY"),
                    "MAIL_CITY": p.get("MAIL_CITY"),
                    "MAIL_ZIP": p.get("MAIL_ZIP"),
                }
            )
        st.dataframe(rows, use_container_width=True, height=320)


if __name__ == "__main__":
    main()
