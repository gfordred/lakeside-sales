"""
Data loader for fetching property information from Google Sheets
"""
import pandas as pd
import streamlit as st
from datetime import datetime, timedelta
import requests
from pathlib import Path
import json
from config.settings import (
    GOOGLE_SHEETS_URL,
    COLUMN_MAPPING,
    STATUS_CONFIG,
    DATA_CACHE_TTL
)


class PropertyDataLoader:
    """Handles loading and caching property data from Google Sheets"""
    
    def __init__(self):
        self.sheet_url = GOOGLE_SHEETS_URL
        self.cache_dir = Path(__file__).parent.parent / "data"
        self.cache_file = self.cache_dir / "properties_cache.csv"
        self.cache_meta_file = self.cache_dir / "properties_cache.meta"
        
        # Ensure cache directory exists
        self.cache_dir.mkdir(exist_ok=True)
        
    @st.cache_data(ttl=DATA_CACHE_TTL)
    def fetch_properties(_self, force_refresh: bool = False) -> pd.DataFrame:
        """
        Fetch property data from Google Sheets with local caching
        
        Args:
            force_refresh: If True, bypass cache and fetch from Google Sheets
            
        Returns:
            pd.DataFrame: Property data with standardized columns
        """
        # Check if we should use local cache
        if not force_refresh and _self._is_cache_valid():
            try:
                df = _self._load_from_cache()
                if not df.empty:
                    return df
            except Exception as e:
                st.warning(f"Cache load failed: {e}. Fetching fresh data...")
        
        # Fetch from Google Sheets
        try:
            df = _self._fetch_from_google_sheets()
            
            # Save to local cache
            if not df.empty:
                _self._save_to_cache(df)
            
            return df
            
        except Exception as e:
            st.error(f"Error loading property data: {str(e)}")
            
            # Try to load stale cache as fallback
            if _self.cache_file.exists():
                st.warning("Loading cached data as fallback...")
                return _self._load_from_cache()
            
            return pd.DataFrame()
    
    def _is_cache_valid(self) -> bool:
        """Check if local cache exists and is still valid"""
        if not self.cache_file.exists() or not self.cache_meta_file.exists():
            return False
        
        try:
            with open(self.cache_meta_file, 'r') as f:
                meta = json.load(f)
            
            cache_time = datetime.fromisoformat(meta['timestamp'])
            age = datetime.now() - cache_time
            
            # Cache is valid if less than TTL seconds old
            return age.total_seconds() < DATA_CACHE_TTL
        except Exception:
            return False
    
    def _load_from_cache(self) -> pd.DataFrame:
        """Load property data from local cache"""
        df = pd.read_csv(self.cache_file)
        return df
    
    def _save_to_cache(self, df: pd.DataFrame):
        """Save property data to local cache"""
        try:
            df.to_csv(self.cache_file, index=False)
            
            # Save metadata
            meta = {
                'timestamp': datetime.now().isoformat(),
                'source': self.sheet_url,
                'rows': len(df)
            }
            
            with open(self.cache_meta_file, 'w') as f:
                json.dump(meta, f, indent=2)
        except Exception as e:
            st.warning(f"Failed to save cache: {e}")
    
    def _fetch_from_google_sheets(self) -> pd.DataFrame:
        """Fetch data directly from Google Sheets"""
        # Fetch CSV data
        response = requests.get(self.sheet_url)
        response.raise_for_status()
        
        # Parse CSV
        from io import StringIO
        df = pd.read_csv(StringIO(response.text))
        
        # Standardize column names
        df = df.rename(columns={
            COLUMN_MAPPING['id']: 'id',
            COLUMN_MAPPING['status']: 'status_raw',
            COLUMN_MAPPING['size']: 'size',
            COLUMN_MAPPING['price']: 'price',
            COLUMN_MAPPING['last_updated']: 'last_updated'
        })
        
        # Normalize status
        df['status'] = df['status_raw'].apply(self._normalize_status)
        
        # Add color mapping
        df['color'] = df['status'].map(
            {k: v['color'] for k, v in STATUS_CONFIG.items()}
        )
        
        # Clean numeric columns
        if 'size' in df.columns:
            df['size'] = pd.to_numeric(df['size'], errors='coerce')
        if 'price' in df.columns:
            df['price'] = pd.to_numeric(df['price'], errors='coerce')
        
        return df
    
    @staticmethod
    def _normalize_status(status: str) -> str:
        """
        Normalize status string to standard category
        
        Args:
            status: Raw status from spreadsheet
            
        Returns:
            str: Normalized status key
        """
        if pd.isna(status):
            return "unknown"
            
        status_lower = str(status).strip().lower()
        
        for status_key, config in STATUS_CONFIG.items():
            for keyword in config['keywords']:
                if status_lower.startswith(keyword):
                    return status_key
        
        return "unknown"
    
    def get_property(self, stand_id: str) -> dict:
        """
        Get details for a specific property
        
        Args:
            stand_id: Property ID
            
        Returns:
            dict: Property details or empty dict if not found
        """
        df = self.fetch_properties()
        
        if df.empty:
            return {}
        
        # Normalize stand ID for matching
        stand_id_norm = str(stand_id).strip().lower()
        df['id_norm'] = df['id'].str.strip().str.lower()
        
        property_df = df[df['id_norm'] == stand_id_norm]
        
        if property_df.empty:
            # Try without "stand-" prefix
            stand_id_alt = stand_id_norm.replace("stand-", "")
            property_df = df[df['id_norm'].str.replace("stand-", "") == stand_id_alt]
        
        if not property_df.empty:
            return property_df.iloc[0].to_dict()
        
        return {}
    
    def get_status_counts(self) -> dict:
        """
        Get count of properties by status
        
        Returns:
            dict: Status counts
        """
        df = self.fetch_properties()
        
        if df.empty:
            return {k: 0 for k in STATUS_CONFIG.keys()}
        
        counts = df['status'].value_counts().to_dict()
        
        # Ensure all statuses are represented
        for status in STATUS_CONFIG.keys():
            if status not in counts:
                counts[status] = 0
        
        return counts
