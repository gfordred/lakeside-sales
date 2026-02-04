"""
Lakeside Village Property Sales Map
Main Streamlit Application
"""
import streamlit as st
import pandas as pd
import sys
from pathlib import Path

# Add src to path
sys.path.append(str(Path(__file__).parent))

from src.data_loader import PropertyDataLoader
from src.map_builder import InteractiveMap
from src.analytics import Analytics
from src.id_utils import ids_match
from config.settings import (
    APP_TITLE,
    STATUS_CONFIG,
    CONTACT_EMAIL
)


def main():
    """Main application entry point"""
    
    # Page configuration
    st.set_page_config(
        page_title=APP_TITLE,
        page_icon="🏘️",
        layout="wide",
        initial_sidebar_state="expanded"
    )
    
    # Custom CSS for dark theme
    st.markdown("""
        <style>
        .main {
            padding: 1rem;
        }
        .stPlotlyChart {
            border-radius: 8px;
            box-shadow: 0 4px 12px rgba(0,0,0,0.3);
        }
        h1 {
            color: #fafafa;
            font-weight: 700;
        }
        h2, h3 {
            color: #e5e7eb;
        }
        .status-badge {
            padding: 0.25rem 0.75rem;
            border-radius: 999px;
            font-size: 0.875rem;
            font-weight: 600;
            display: inline-block;
            margin: 0.25rem;
        }
        </style>
    """, unsafe_allow_html=True)
    
    # Header
    st.title(f"🏘️ {APP_TITLE}")
    st.markdown("---")
    
    # Initialize data loader and analytics
    data_loader = PropertyDataLoader()
    analytics = Analytics()
    
    # Load property data
    with st.spinner("Loading property data..."):
        df = data_loader.fetch_properties()
    
    if df.empty:
        st.error("Unable to load property data. Please check your connection.")
        return
    
    # Layout: Sidebar and Main content
    with st.sidebar:
        render_sidebar(data_loader, df, analytics)
    
    # Main content area
    col1, col2 = st.columns([2, 1])
    
    with col1:
        render_map(df, analytics)
    
    with col2:
        render_property_details(df, analytics)
    
    # Data table section - full width below the map
    st.markdown("---")
    render_data_table(df)


def render_sidebar(data_loader: PropertyDataLoader, df, analytics: Analytics):
    """Render sidebar with search and filters"""
    
    # Logo
    logo_path = Path(__file__).parent / "assets" / "images" / "logo.jpg"
    if logo_path.exists():
        st.image(str(logo_path), width="stretch")
    
    st.header("🔍 Search & Filter")
    
    # Search box
    search_term = st.text_input(
        "Search by Stand ID",
        placeholder="e.g., Erf-001",
        help="Enter stand ID to search"
    )
    
    if search_term:
        st.session_state['selected_property'] = search_term
        analytics.track_event('search', {'query': search_term})
    
    # Refresh button
    if st.button("🔄 Refresh Data", help="Reload data from Google Sheets", width="stretch"):
        # Clear cache and force refresh
        st.cache_data.clear()
        data_loader.fetch_properties(force_refresh=True)
        st.success("Data refreshed!")
        st.rerun()
    
    st.markdown("---")
    
    # Status filter
    st.subheader("Filter by Status")
    
    status_counts = data_loader.get_status_counts()
    
    for status_key, config in STATUS_CONFIG.items():
        count = status_counts.get(status_key, 0)
        if count == 0 and status_key == 'unknown':
            continue
            
        st.checkbox(
            f"{config['label']} ({count})",
            value=True,
            key=f"filter_{status_key}",
            help=f"Show/hide {config['label'].lower()} properties"
        )
    
    st.markdown("---")
    
    # Statistics
    st.subheader("📊 Statistics")
    total_properties = len(df)
    available_count = status_counts.get('available', 0)
    
    col1, col2 = st.columns(2)
    with col1:
        st.metric("Total Properties", total_properties)
    with col2:
        st.metric("Available", available_count)
    
    # Availability percentage
    if total_properties > 0:
        availability_pct = (available_count / total_properties) * 100
        st.progress(availability_pct / 100)
        st.caption(f"{availability_pct:.1f}% available")


@st.cache_data(show_spinner=False, ttl=300)
def get_cached_map(_df_hash, df, polygons_path, background_image_path):
    """Cached map generation - renders ONCE per data version, never on filter/click"""
    # Always generate full map with ALL properties (no filtering)
    # Filtering only affects the data table, not the map visualization
    map_builder = InteractiveMap(polygons_path)
    return map_builder.create_map(df, background_image=background_image_path)


def render_map(df, analytics: Analytics):
    """Render interactive property map with filtering"""
    
    st.subheader("🗺️ Interactive Property Map")
    
    # Initialize map builder
    polygons_path = Path(__file__).parent / "data" / "polygons.json"
    
    if not polygons_path.exists():
        st.warning("Polygon data not found. Map will be empty.")
        return
    
    # Get background image path
    background_image = Path(__file__).parent / "assets" / "images" / "site_plan.jpg"
    bg_path = str(background_image) if background_image.exists() else None
    
    # Create simple hash of dataframe for caching
    df_hash = hash(tuple(df['id'].tolist()))
    
    # Create map ONCE - cached by data hash only, NOT by filters
    # This means map renders on load and never again unless data changes
    with st.spinner("Rendering map..."):
        fig = get_cached_map(df_hash, df, str(polygons_path), bg_path)
    
    # Display map with hover and click events
    event = st.plotly_chart(
        fig, 
        width="stretch", 
        key="property_map",
        on_select="rerun",  # Captures both hover and click
        selection_mode="points",
        config={
            'displayModeBar': True,
            'displaylogo': False,
            'modeBarButtonsToRemove': ['lasso2d', 'select2d']
        }
    )
    
    # Handle hover event (selection with hover data)
    if event and hasattr(event, 'selection') and event.selection:
        if hasattr(event.selection, 'points') and event.selection.points:
            hovered_property = event.selection.points[0].get('name', '')
            if hovered_property:
                # Update session state to show hovered property details
                st.session_state['selected_property'] = hovered_property
                analytics.track_event('property_hover', {'property_id': hovered_property})
    
    # Handle click selection
    if event and event.selection and event.selection.point_indices:
        clicked_idx = event.selection.point_indices[0]
        if clicked_idx is not None and 'name' in fig.data[clicked_idx]:
            clicked_property = fig.data[clicked_idx]['name']
            if clicked_property:
                st.session_state['selected_property'] = clicked_property
                analytics.track_event('property_click', {'property_id': clicked_property})
    
    st.caption("💡 Tip: Click a property to view details • Drag to pan • Scroll to zoom")
    
    # Legend below the map
    st.markdown("---")
    st.subheader("Legend")
    
    # Get status counts for legend
    status_counts = {}
    for status_key in STATUS_CONFIG.keys():
        status_counts[status_key] = len(df[df['status'] == status_key])
    
    # Display legend in columns for compact layout
    legend_cols = st.columns(len([k for k in STATUS_CONFIG.keys() if k != 'unknown']))
    col_idx = 0
    for status_key, config in STATUS_CONFIG.items():
        if status_key == 'unknown':
            continue
        count = status_counts.get(status_key, 0)
        with legend_cols[col_idx]:
            st.markdown(
                f'<div style="display:flex;align-items:center;justify-content:center;margin:0.5rem 0">'
                f'<div style="width:18px;height:18px;background:{config["color"]};'
                f'border-radius:4px;margin-right:10px;border:1px solid rgba(255,255,255,0.3)"></div>'
                f'<span>{config["label"]} ({count})</span>'
                f'</div>',
                unsafe_allow_html=True
            )
        col_idx += 1


def render_property_details(df, analytics: Analytics):
    """Render property details panel"""
    
    st.subheader("📋 Property Details")
    
    # Get selected property
    selected_id = st.session_state.get('selected_property', None)
    
    if not selected_id:
        st.info("👈 Select a property from the map or use the search box")
        return
    
    # Find property using robust matching
    property_data = None
    for idx, row in df.iterrows():
        # Check if IDs match (handles prefix/suffix differences)
        if ids_match(str(row['id']), selected_id):
            property_data = row
            break
    
    if property_data is None:
        st.warning(f"Property '{selected_id}' not found")
        return
    
    # Track property view
    analytics.track_event('property_view', {'property_id': selected_id})
    
    # Display property card
    status = property_data.get('status', 'unknown')
    color = STATUS_CONFIG.get(status, STATUS_CONFIG['unknown'])['color']
    status_label = STATUS_CONFIG.get(status, STATUS_CONFIG['unknown'])['label']
    
    st.markdown(f"""
        <div style="background: linear-gradient(135deg, {color}22 0%, {color}44 100%);
                    border-left: 4px solid {color};
                    padding: 1.5rem;
                    border-radius: 8px;
                    margin-bottom: 1rem;">
            <h3 style="margin:0 0 1rem 0;">{property_data['id']}</h3>
            <div style="background:{color}33;color:#000;padding:0.5rem 1rem;
                        border-radius:999px;display:inline-block;font-weight:600;">
                {status_label}
            </div>
        </div>
    """, unsafe_allow_html=True)
    
    # Property details
    st.markdown("### Details")
    
    col1, col2 = st.columns(2)
    
    with col1:
        if 'size' in property_data and pd.notna(property_data['size']):
            st.metric("Size", f"{property_data['size']:.0f} m²")
    
    with col2:
        if 'price' in property_data and pd.notna(property_data['price']):
            st.metric("Price", f"R {property_data['price']:,.0f}")
    
    # Contact button
    st.markdown("---")
    st.markdown("### Interested?")
    
    if st.button("📧 Contact Agent", width="stretch", type="primary"):
        analytics.track_event('contact', {'property_id': property_data['id']})
        st.success(f"Please contact us at {CONTACT_EMAIL}")
        st.balloons()


def render_data_table(df):
    """Render view-only property data table with filter support"""
    
    st.subheader("📊 Property Data Table")
    st.caption("📍 View-only data from Google Sheets")
    
    if df.empty:
        st.info("No property data available")
        return
    
    # Apply status filters to table
    active_filters = []
    for status_key in STATUS_CONFIG.keys():
        if st.session_state.get(f"filter_{status_key}", True):
            active_filters.append(status_key)
    
    # Filter dataframe
    if active_filters:
        filtered_df = df[df['status'].isin(active_filters)].copy()
    else:
        filtered_df = df.copy()
    
    # Select columns to display
    display_columns = ['id', 'status_raw', 'size', 'price']
    
    # Add any additional columns from the dataframe
    for col in filtered_df.columns:
        # Skip unnamed columns and internal columns
        if (col not in display_columns and 
            col not in ['color', 'status', 'id_norm'] and
            not col.startswith('Unnamed')):
            display_columns.append(col)
    
    # Filter to only existing columns
    display_columns = [col for col in display_columns if col in filtered_df.columns]
    
    # Create display dataframe
    display_df = filtered_df[display_columns].copy()
    
    # Rename columns for better display
    column_renames = {
        'id': 'Stand ID',
        'status_raw': 'Status',
        'size': 'Size (m²)',
        'price': 'Price (R)',
        'last_updated': 'Last Updated'
    }
    
    display_df = display_df.rename(columns=column_renames)
    
    # Format numeric columns
    if 'Size (m²)' in display_df.columns:
        display_df['Size (m²)'] = display_df['Size (m²)'].fillna(0).astype(int)
    
    if 'Price (R)' in display_df.columns:
        display_df['Price (R)'] = display_df['Price (R)'].apply(
            lambda x: f"R {x:,.0f}" if pd.notna(x) else ""
        )
    
    # Display the dataframe
    st.dataframe(
        display_df,
        width='stretch',  # Full width
        hide_index=True,
        height=400
    )
    
    # Show count
    st.caption(f"Showing {len(display_df)} properties")


if __name__ == "__main__":
    # Initialize session state
    if 'selected_property' not in st.session_state:
        st.session_state['selected_property'] = None
    
    main()
