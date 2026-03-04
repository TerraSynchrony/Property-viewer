# Experience Builder

A Streamlit-based interactive web application for exploring Schenectady County property parcels and ownership data using ArcGIS FeatureServer layers and Leaflet maps.

## Features

- **Interactive map** powered by Folium (Leaflet.js) with multiple basemap options (OpenStreetMap, CartoDB Positron, CartoDB Dark Matter)
- **Live parcel data** from the NYS Tax Parcel Centroid Points public FeatureServer, filtered to Schenectady County
- **Owner and address search** to filter parcels by owner name or parcel address
- **Popup details** for each parcel showing configurable fields (owner, address, SBL, assessed value, etc.)
- **Pagination support** to load large datasets efficiently
- **Custom polygon layer** support — point the app at any ArcGIS parcel polygon FeatureServer

## Requirements

- Python 3.9+
- See `requirements.txt` for Python package dependencies

## Installation

```bash
pip install -r requirements.txt
```

## Running the App

```bash
streamlit run app.py
```

Then open the local URL shown in your terminal (default: http://localhost:8501).

## Usage

1. Use the **sidebar** to choose the data source (public centroid points or your own polygon FeatureServer URL).
2. Apply optional **filters** by county name, owner, or parcel address.
3. Adjust **performance** settings (max features, minimum zoom level before data loads).
4. Choose which **fields** to display in each parcel's popup.
5. Pan and zoom the map — parcel data loads automatically for the current map view when zoomed in enough.

## Data Source

Default: [NYS Tax Parcel Centroid Points](https://gisservices.its.ny.gov/arcgis/rest/services/NYS_Tax_Parcel_Centroid_Points/FeatureServer/0) — a public ArcGIS FeatureServer provided by NYS ITS Geospatial Services.

## License

See repository for license details.
