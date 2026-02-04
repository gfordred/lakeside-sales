"""
Configuration settings for the Lakeside Property Sales application
"""
import os
from dotenv import load_dotenv

load_dotenv()

# Google Sheets Configuration
GOOGLE_SHEETS_URL = os.getenv(
    "GOOGLE_SHEETS_URL",
    "https://docs.google.com/spreadsheets/d/e/2PACX-1vSJOgpf8Lu7bmrAg5LdMPEGoNLNg_an9FKR0Ix-h27VWmzkIohrtwrISUkcs9c6Of26znTnXBamvrog/pub?output=csv"
)

# Column mappings from Google Sheets
COLUMN_MAPPING = {
    "id": "StandID",
    "status": "Status",
    "size": "Size",
    "price": "Price",
    "last_updated": "LastUpdated"
}

# Status configurations
STATUS_CONFIG = {
    "available": {
        "color": "#2ecc71",
        "label": "Available",
        "keywords": ["avail"]
    },
    "reserved": {
        "color": "#f4b400",
        "label": "Reserved",
        "keywords": ["reser", "pending"]
    },
    "unavailable": {
        "color": "#d93025",
        "label": "Unavailable",
        "keywords": ["unavail", "sold"]
    },
    "unknown": {
        "color": "#9ea3a8",
        "label": "Unknown",
        "keywords": []
    }
}

# UI Configuration
APP_TITLE = "Lakeside Village - Property Sales Map"
CONTACT_EMAIL = os.getenv("CONTACT_EMAIL", "info@lakesidevillage.com")
ANALYTICS_ID = os.getenv("ANALYTICS_ID", "")

# Cache settings (in seconds)
DATA_CACHE_TTL = 300  # 5 minutes

# Map settings
MAP_CENTER = {"lat": -26.0, "lon": 28.0}  # Approximate center
MAP_ZOOM = 16
FILL_OPACITY = 0.35
