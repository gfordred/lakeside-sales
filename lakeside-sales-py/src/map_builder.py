"""
Map builder for creating interactive property maps with Plotly
"""
import plotly.graph_objects as go
import json
from typing import List, Dict
import pandas as pd
from config.settings import STATUS_CONFIG, FILL_OPACITY
from src.id_utils import ids_match


class InteractiveMap:
    """Builds interactive property maps using Plotly"""
    
    def __init__(self, polygons_file: str = None):
        """
        Initialize map builder
        
        Args:
            polygons_file: Path to polygons JSON file
        """
        self.polygons_file = polygons_file
        self.polygons = []
        self.global_bbox = None
        
        if polygons_file:
            self.load_polygons(polygons_file)
            self._calculate_global_bbox()
    
    def load_polygons(self, file_path: str):
        """Load polygon data from JSON file"""
        try:
            with open(file_path, 'r') as f:
                data = json.load(f)
                self.polygons = data.get('polygons', [])
        except Exception as e:
            print(f"Error loading polygons: {e}")
            self.polygons = []
    
    def _calculate_global_bbox(self):
        """Calculate bounding box of ALL polygons (matching JavaScript polygonsBBox)"""
        if not self.polygons:
            return
        
        min_x = float('inf')
        min_y = float('inf')
        max_x = float('-inf')
        max_y = float('-inf')
        
        for polygon in self.polygons:
            points_str = polygon.get('points', '')
            pairs = points_str.strip().split()
            
            for pair in pairs:
                try:
                    x, y = pair.split(',')
                    x, y = float(x), float(y)
                    if x < min_x: min_x = x
                    if y < min_y: min_y = y
                    if x > max_x: max_x = x
                    if y > max_y: max_y = y
                except (ValueError, AttributeError):
                    continue
        
        self.global_bbox = {
            'minX': min_x,
            'minY': min_y,
            'maxX': max_x,
            'maxY': max_y,
            'width': max_x - min_x,
            'height': max_y - min_y
        }
    
    def create_map(self, df: pd.DataFrame, background_image: str = None) -> go.Figure:
        """
        Create interactive map with property polygons
        
        Args:
            df: DataFrame with property data
            background_image: Path to background site plan image
            
        Returns:
            go.Figure: Plotly figure object
        """
        fig = go.Figure()
        
        # Get artwork (image) bounding box
        artwork_bbox = None
        if background_image:
            from PIL import Image
            from pathlib import Path
            
            img_path = Path(background_image)
            if img_path.exists():
                # Load image
                img = Image.open(img_path)
                
                # Get image dimensions
                img_width, img_height = img.size
                
                artwork_bbox = {
                    'x': 0,
                    'y': 0,
                    'width': img_width,
                    'height': img_height
                }
                
                # Add image as background
                fig.add_layout_image(
                    dict(
                        source=img,
                        xref="x",
                        yref="y",
                        x=0,
                        y=0,
                        sizex=img_width,
                        sizey=img_height,
                        sizing="stretch",
                        opacity=0.6,
                        layer="below"
                    )
                )
        
        # Create property lookup
        property_lookup = df.set_index('id').to_dict('index')
        
        # Add each polygon with transformation
        for polygon in self.polygons:
            self._add_polygon(fig, polygon, property_lookup, artwork_bbox)
        
        # Configure layout
        fig.update_layout(
            showlegend=False,
            hovermode='closest',
            plot_bgcolor='#0e1117',
            paper_bgcolor='#0e1117',
            xaxis=dict(
                showgrid=False,
                zeroline=False,
                showticklabels=False,
                scaleanchor="y",
                scaleratio=1,
            ),
            yaxis=dict(
                showgrid=False,
                zeroline=False,
                showticklabels=False,
                autorange='reversed'
            ),
            margin=dict(l=0, r=0, t=0, b=0),
            height=600,
            dragmode='zoom',  # Changed from 'pan' for better polygon interaction
        )
        
        # Enable zoom and pan
        fig.update_xaxes(fixedrange=False)
        fig.update_yaxes(fixedrange=False)
        
        return fig
    
    def _add_polygon(self, fig: go.Figure, polygon: Dict, property_lookup: Dict, artwork_bbox: Dict = None):
        """
        Add a single polygon to the map
        
        Args:
            fig: Plotly figure
            polygon: Polygon data with id and points
            property_lookup: Dictionary of property data
            artwork_bbox: Bounding box of the artwork/image
        """
        polygon_id = polygon.get('id', '')
        points_str = polygon.get('points', '')
        
        # Parse points with transformation
        coords = self._parse_and_transform_points(points_str, artwork_bbox)
        
        if not coords:
            return
        
        # Get property data
        property_data = self._get_property_data(polygon_id, property_lookup)
        
        # Extract coordinates
        x_coords = [c[0] for c in coords]
        y_coords = [c[1] for c in coords]
        
        # Close the polygon
        x_coords.append(x_coords[0])
        y_coords.append(y_coords[0])
        
        # Determine color
        color = property_data.get('color', STATUS_CONFIG['unknown']['color'])
        
        # Create hover text
        hover_text = self._create_hover_text(polygon_id, property_data)
        
        # Add polygon trace
        fig.add_trace(go.Scatter(
            x=x_coords,
            y=y_coords,
            fill='toself',
            fillcolor=color,
            opacity=0.55,  # Reduced for better background visibility
            line=dict(color='white', width=2),
            hovertext=hover_text,
            hoverinfo='text',
            mode='lines',
            name=polygon_id,
            showlegend=False,
        ))
    
    def _parse_and_transform_points(self, points_str: str, artwork_bbox: Dict = None) -> List[tuple]:
        """
        Parse SVG points and transform them to match the artwork
        This exactly matches the JavaScript remapPolygonsToArtwork function
        
        Args:
            points_str: Space-separated coordinate pairs (x,y)
            artwork_bbox: Bounding box of the artwork/image
            
        Returns:
            List of (x, y) tuples
        """
        if not points_str or not self.global_bbox:
            return []
        
        # Parse raw coordinates
        raw_coords = []
        pairs = points_str.strip().split()
        
        for pair in pairs:
            try:
                x, y = pair.split(',')
                raw_coords.append((float(x), float(y)))
            except (ValueError, AttributeError):
                continue
        
        if not raw_coords:
            return []
        
        # Use artwork bbox if provided, otherwise use default
        if artwork_bbox:
            dst = artwork_bbox
        else:
            # Default to global polygon bbox
            dst = {
                'x': 0,
                'y': 0,
                'width': self.global_bbox['width'],
                'height': self.global_bbox['height']
            }
        
        src = self.global_bbox
        
        # Calculate scale to fit (matching JavaScript logic)
        if src['width'] <= 0 or src['height'] <= 0:
            return raw_coords
        
        scale = min(dst['width'] / src['width'], dst['height'] / src['height'])
        
        # Apply ALIGN_TWEAK scale
        ALIGN_SCALE = 0.744
        scale *= ALIGN_SCALE
        
        # Calculate centering translation
        scaled_width = src['width'] * scale
        scaled_height = src['height'] * scale
        tx = dst['x'] + (dst['width'] - scaled_width) / 2 - src['minX'] * scale
        ty = dst['y'] + (dst['height'] - scaled_height) / 2 - src['minY'] * scale
        
        # Center point for rotation
        cx = dst['x'] + dst['width'] / 2
        cy = dst['y'] + dst['height'] / 2
        
        # ALIGN_TWEAK parameters - fine-tuned for perfect alignment
        # Higher dx = more right, more negative dy = more up
        ALIGN_DX = 820  # Fine-tuned to move polygons RIGHT
        ALIGN_DY = -160  # Fine-tuned to move polygons UP
        ALIGN_ROTATE_DEG = 0
        
        # Transform each coordinate
        transformed_coords = []
        for x_orig, y_orig in raw_coords:
            # Apply scale and translation
            x_trans = x_orig * scale + tx
            y_trans = y_orig * scale + ty
            
            # Apply rotation if needed
            if ALIGN_ROTATE_DEG != 0:
                import math
                rad = ALIGN_ROTATE_DEG * math.pi / 180
                cos_r = math.cos(rad)
                sin_r = math.sin(rad)
                dx_from_center = x_trans - cx
                dy_from_center = y_trans - cy
                x_rotated = dx_from_center * cos_r - dy_from_center * sin_r + cx
                y_rotated = dx_from_center * sin_r + dy_from_center * cos_r + cy
            else:
                x_rotated = x_trans
                y_rotated = y_trans
            
            # Apply final ALIGN_TWEAK offsets
            x_final = x_rotated + ALIGN_DX
            y_final = y_rotated + ALIGN_DY
            
            transformed_coords.append((x_final, y_final))
        
        return transformed_coords
    
    @staticmethod
    def _get_property_data(polygon_id: str, property_lookup: Dict) -> Dict:
        """Get property data for a polygon ID"""
        # Try direct match
        if polygon_id in property_lookup:
            return property_lookup[polygon_id]
        
        # Use robust ID matching
        for prop_id, data in property_lookup.items():
            if ids_match(polygon_id, prop_id):
                return data
        
        return {}
    
    @staticmethod
    def _create_hover_text(polygon_id: str, property_data: Dict) -> str:
        """Create rich hover tooltip showing all property details"""
        if not property_data:
            return f"<b>{polygon_id}</b><br>No data available"
            
        lines = [f"<b>{polygon_id}</b>"]
        
        # Always show status first
        status = property_data.get('status_raw', property_data.get('status', 'Unknown'))
        lines.append(f"Status: {status}")
        
        # Exclude keys we've already handled or don't want to show
        exclude_keys = {'id', 'color', 'status', 'status_raw', 'id_norm', 'points', 'geometry'}
        
        # Show specific important fields first if present
        if 'size' in property_data and pd.notna(property_data['size']):
            lines.append(f"Size: {property_data['size']:.0f} m²")
            exclude_keys.add('size')
            
        if 'price' in property_data and pd.notna(property_data['price']):
            lines.append(f"Price: R {property_data['price']:,.0f}")
            exclude_keys.add('price')
            
        # Show remaining fields
        for key, value in property_data.items():
            if key not in exclude_keys and pd.notna(value) and str(value).strip():
                # Format key: 'last_updated' -> 'Last Updated'
                formatted_key = key.replace('_', ' ').title()
                lines.append(f"{formatted_key}: {value}")
        
        return "<br>".join(lines)
