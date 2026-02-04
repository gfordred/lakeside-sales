#!/usr/bin/env python3
"""
Lakeside Sales - Interactive Stand Map Flask Application

Environment Variables:
  SHEET_CSV_URL     - Google Sheets CSV export URL (optional)
  ID_COLUMN         - Column name for stand ID (default: StandID)
  STATUS_COLUMN     - Column name for status (default: Status)
  SIZE_COLUMN       - Column name for size (default: Size)
  PRICE_COLUMN      - Column name for price (default: Price)
  UPDATED_COLUMN    - Column name for last updated (default: LastUpdated)
  PORT              - Server port (default: 5000)

Run locally:
  python app.py

Production (gunicorn):
  gunicorn -w 2 -b 0.0.0.0:8000 app:app
"""

import os
import csv
import io
import json
import time
import logging
from datetime import datetime
from threading import Lock
from typing import Dict, List, Optional, Tuple
from urllib.request import urlopen
from urllib.error import URLError

from flask import Flask, render_template_string, jsonify, request, send_file

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Configuration
SHEET_CSV_URL = os.getenv('SHEET_CSV_URL', 'https://docs.google.com/spreadsheets/d/e/2PACX-1vSJOgpf8Lu7bmrAg5LdMPEGoNLNg_an9FKR0Ix-h27VWmzkIohrtwrISUkcs9c6Of26znTnXBamvrog/pub?output=csv')
ID_COLUMN = os.getenv('ID_COLUMN', 'StandID')
STATUS_COLUMN = os.getenv('STATUS_COLUMN', 'Status')
SIZE_COLUMN = os.getenv('SIZE_COLUMN', 'Size')
PRICE_COLUMN = os.getenv('PRICE_COLUMN', 'Price')
UPDATED_COLUMN = os.getenv('UPDATED_COLUMN', 'LastUpdated')
PORT = int(os.getenv('PORT', 5000))

# Cache settings
SHEET_CACHE_SECONDS = 60
POLYGON_CACHE_SECONDS = 3600

# Color mapping
COLORS = {
    'available': '#2ecc71',
    'reserved': '#f4b400',
    'unavailable': '#d93025',
    'unknown': '#9ea3a8'
}

# Global cache
_sheet_cache = {'data': None, 'timestamp': 0}
_polygon_cache = {'data': None, 'timestamp': 0}
_cache_lock = Lock()

app = Flask(__name__)


def normalize_id(stand_id: str) -> str:
    """Normalize stand ID for consistent matching."""
    if not stand_id:
        return ''
    s = str(stand_id).strip().lower()
    # Remove 'stand-' prefix for matching
    if s.startswith('stand-'):
        s = s[6:]
    return s


def status_key(status: str) -> str:
    """Map status string to color key."""
    s = str(status).strip().lower()
    if s.startswith('avail'):
        return 'available'
    if s.startswith('reser') or s == 'pending':
        return 'reserved'
    if s.startswith('unavail') or s.startswith('sold'):
        return 'unavailable'
    return 'unknown'


def load_polygons_from_file() -> List[Dict]:
    """Load and normalize polygon data from polygons.json."""
    try:
        polygon_file = os.path.join(os.path.dirname(__file__), 'polygons.json')
        with open(polygon_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        polygons = data.get('polygons', [])
        
        # Track duplicates and normalize
        seen_ids = {}
        normalized_polygons = []
        
        for idx, poly in enumerate(polygons):
            poly_id = poly.get('id', '')
            points = poly.get('points', '')
            
            # Validate points
            if not points or not isinstance(points, str):
                logger.warning(f"Polygon at index {idx} has invalid points, skipping")
                continue
            
            # Try to parse points to validate
            try:
                point_pairs = points.strip().split()
                for pair in point_pairs:
                    x, y = pair.split(',')
                    float(x)
                    float(y)
            except (ValueError, AttributeError) as e:
                logger.warning(f"Polygon {poly_id} has unparseable points: {e}, skipping")
                continue
            
            # Normalize ID for duplicate detection
            normalized_key = normalize_id(poly_id)
            
            # Handle duplicates - keep first occurrence
            if normalized_key in seen_ids:
                logger.warning(f"Duplicate polygon ID detected: '{poly_id}' (normalized: '{normalized_key}'). "
                             f"First occurrence at index {seen_ids[normalized_key]}, duplicate at index {idx}. "
                             f"Keeping first occurrence.")
                continue
            
            seen_ids[normalized_key] = idx
            
            # Handle case inconsistencies
            if poly_id and poly_id != poly_id.lower():
                # Check for common typos like "ERf" instead of "Erf"
                if 'ERf' in poly_id or 'eRf' in poly_id:
                    logger.warning(f"Case inconsistency detected in polygon ID: '{poly_id}'. "
                                 f"This may cause matching issues.")
            
            normalized_polygons.append({
                'id': poly_id,
                'points': points,
                'normalized_id': normalized_key
            })
        
        logger.info(f"Loaded {len(normalized_polygons)} valid polygons ({len(polygons) - len(normalized_polygons)} skipped)")
        return normalized_polygons
        
    except FileNotFoundError:
        logger.error("polygons.json not found")
        return []
    except json.JSONDecodeError as e:
        logger.error(f"Error parsing polygons.json: {e}")
        return []
    except Exception as e:
        logger.error(f"Unexpected error loading polygons: {e}")
        return []


def fetch_sheet_data() -> Tuple[Dict, str]:
    """Fetch and parse Google Sheets CSV data."""
    if not SHEET_CSV_URL:
        return {}, ''
    
    try:
        with urlopen(SHEET_CSV_URL, timeout=10) as response:
            csv_text = response.read().decode('utf-8')
        
        reader = csv.DictReader(io.StringIO(csv_text))
        
        # Find column indices (case-insensitive)
        fieldnames = reader.fieldnames or []
        fieldnames_lower = {f.strip().lower(): f for f in fieldnames}
        
        id_col = fieldnames_lower.get(ID_COLUMN.lower(), ID_COLUMN)
        status_col = fieldnames_lower.get(STATUS_COLUMN.lower(), STATUS_COLUMN)
        updated_col = fieldnames_lower.get(UPDATED_COLUMN.lower(), UPDATED_COLUMN)
        
        status_map = {}
        last_updated = ''
        
        for row in reader:
            stand_id = row.get(id_col, '').strip()
            if not stand_id:
                continue
            
            status_val = row.get(status_col, '').strip()
            
            # Extract last updated timestamp (first non-empty value)
            if not last_updated and updated_col in row:
                updated_val = row.get(updated_col, '').strip()
                if updated_val:
                    last_updated = updated_val
            
            # Store with normalized key
            normalized_key = normalize_id(stand_id)
            status_map[normalized_key] = {
                'id': stand_id,
                'status': status_key(status_val),
                'rawStatus': status_val,
                'row': row
            }
        
        logger.info(f"Fetched {len(status_map)} stand records from sheet")
        return status_map, last_updated
        
    except URLError as e:
        logger.error(f"Error fetching sheet data: {e}")
        return {}, ''
    except Exception as e:
        logger.error(f"Unexpected error parsing sheet: {e}")
        return {}, ''


def get_cached_polygons() -> List[Dict]:
    """Get cached polygon data."""
    with _cache_lock:
        now = time.time()
        if _polygon_cache['data'] is None or (now - _polygon_cache['timestamp']) > POLYGON_CACHE_SECONDS:
            _polygon_cache['data'] = load_polygons_from_file()
            _polygon_cache['timestamp'] = now
        return _polygon_cache['data']


def get_cached_sheet_data() -> Tuple[Dict, str]:
    """Get cached sheet data."""
    with _cache_lock:
        now = time.time()
        if _sheet_cache['data'] is None or (now - _sheet_cache['timestamp']) > SHEET_CACHE_SECONDS:
            _sheet_cache['data'] = fetch_sheet_data()
            _sheet_cache['timestamp'] = now
        return _sheet_cache['data']


@app.route('/')
def index():
    """Render main page."""
    return render_template_string(HTML_TEMPLATE)


@app.route('/api/polygons')
def api_polygons():
    """Return normalized polygon data."""
    polygons = get_cached_polygons()
    # Remove normalized_id from response
    response_polygons = [{'id': p['id'], 'points': p['points']} for p in polygons]
    
    return jsonify({
        'polygons': response_polygons
    }), 200, {
        'Cache-Control': f'public, max-age={POLYGON_CACHE_SECONDS}'
    }


@app.route('/api/stands')
def api_stands():
    """Return stand status data merged with polygons."""
    status_map, last_updated = get_cached_sheet_data()
    polygons = get_cached_polygons()
    
    # Build response with polygon-aware matching
    stands = {}
    for poly in polygons:
        poly_id = poly['id']
        normalized_key = poly['normalized_id']
        
        # Try to find matching status
        status_info = status_map.get(normalized_key)
        
        if status_info:
            stands[poly_id] = status_info
        else:
            # No match found, mark as unknown
            stands[poly_id] = {
                'id': poly_id,
                'status': 'unknown',
                'rawStatus': 'Unknown',
                'row': {}
            }
    
    return jsonify({
        'stands': stands,
        'lastUpdated': last_updated
    }), 200, {
        'Cache-Control': f'public, max-age={SHEET_CACHE_SECONDS}'
    }


@app.route('/health')
def health():
    """Health check endpoint."""
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.utcnow().isoformat()
    })


@app.route('/logo.jpg')
def serve_logo():
    """Serve logo image."""
    logo_path = os.path.join(os.path.dirname(__file__), 'LakesideVillageLogo.jpg')
    if os.path.exists(logo_path):
        return send_file(logo_path, mimetype='image/jpeg')
    return '', 404


@app.route('/siteplan.svg')
def serve_siteplan():
    """Serve site plan SVG extracted from index.html."""
    # Try to extract the embedded image from index.html
    index_path = os.path.join(os.path.dirname(__file__), 'index.html')
    if os.path.exists(index_path):
        return send_file(index_path, mimetype='text/html')
    return '', 404


# HTML Template with embedded CSS and JavaScript
HTML_TEMPLATE = r'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, user-scalable=no">
    <title>Lakeside Sales - Interactive Stand Map</title>
    <style>
:root { color-scheme: light; }

/* Layout */
html, body { height:100%; margin:0; overflow: hidden; font-family: Arial, Helvetica, sans-serif; }
#layout { height: 100vh; overflow: hidden; display:flex; gap: 12px; padding: 12px; box-sizing: border-box; }

/* Left map column */
#mapCard { flex:1; overflow:hidden; min-height: 0; background:#fff; border-radius: 8px; }
#mapWrap { width:100%; height:100%; position:relative; }
svg#mapSvg { display:block; width:100%; height:100%; cursor:default; }

/* Polygons */
#polys-layer polygon {
  fill:#9ea3a8; fill-opacity:.35;
  stroke:#000; stroke-opacity:.35; stroke-width:1;
  cursor:pointer;
  transition:fill-opacity .15s, stroke-opacity .15s;
  touch-action: manipulation;
}
#polys-layer polygon:hover { fill-opacity:.55; stroke-opacity:.55; }
#polys-layer polygon.active {
  stroke: #ffcc00;
  stroke-width: 5;
  stroke-opacity: 1;
  fill-opacity: 0.65;
  filter: drop-shadow(0 0 8px rgba(255, 204, 0, 0.9));
}

/* Pan/zoom affordances */
#mapSvg { touch-action: none; }
#mapSvg.grabbing { cursor: grabbing; }
#mapSvg.can-pan { cursor: grab; }

/* Overlay zoom buttons */
.zoom-controls {
  position: absolute;
  top: 12px; left: 12px;
  display: flex; gap: 6px;
  z-index: 5;
}
.zoom-controls button {
  border: 1px solid rgba(0,0,0,.2);
  background: #fff;
  border-radius: 8px;
  padding: 6px 10px;
  font: 600 14px/1 Arial, Helvetica, sans-serif;
  box-shadow: 0 2px 8px rgba(0,0,0,.15);
  cursor: pointer;
}
.zoom-controls button:active { transform: translateY(1px); }

/* Right column (sidebar) */
#side {
  width: 420px;
  overflow-y: auto;
  overflow-x: hidden;
  min-height: 0;
  position: relative;
  display: flex;
  flex-direction: column;
  overscroll-behavior: contain;
  background:#fff;
  border-radius: 8px;
  padding: 16px;
}
#logo { width:100%; height:auto; display:block; margin:0 0 14px 0; }
h2 { margin:0 0 6px; font-size:18px; }
.muted { color:#6b7280; }
#details { min-height:140px; border-top:1px solid #eee; border-bottom:1px solid #eee; padding:14px 0; }
.detail-row { display:flex; gap:10px; margin:6px 0; }
.detail-label { width:92px; color:#6b7280; }
.legend { margin-top:8px; display:grid; grid-template-columns: 18px auto; align-items:center; gap:8px 10px; }
.swatch { width:18px; height:18px; border-radius:4px; border:1px solid rgba(0,0,0,.15); }
.swatch.green { background:#2ecc71; }
.swatch.yellow { background:#f4b400; }
.swatch.red { background:#d93025; }
.swatch.gray { background:#9ea3a8; }
.pill { display:inline-block; padding:2px 8px; border-radius:999px; font-size:12px; border:1px solid #e5e7eb; }

/* Search box */
#searchBox {
  margin: 12px 0;
  padding: 8px 12px;
  border: 1px solid #d1d5db;
  border-radius: 6px;
  font-size: 14px;
  width: 100%;
  box-sizing: border-box;
}
#searchBox:focus {
  outline: none;
  border-color: #2ecc71;
}

/* Legend pinned at bottom (desktop) */
#legendBlock {
  margin-top: auto;
  position: sticky;
  bottom: 0;
  background: #fff;
  border-top: 1px solid #eee;
  padding: 12px 0 10px;
}
#legendBlock .legend{
  display: grid;
  grid-template-columns: 1.1rem 1fr;
  gap: .4rem .6rem;
  align-items: center;
}

/* Hide old drawer header rows on desktop */
@media (min-width: 769px) {
  .drawer-header { display:none; }
}

/* Mobile */
@media (max-width: 768px) {
  #layout { flex-direction: column; height: 100vh; padding: 8px; gap: 8px; }

  /* Map on top, fixed height */
  #mapCard {
    height: 38vh;
    min-height: 240px;
    order: 1;
  }
  #mapWrap, svg#mapSvg { height: 100%; }

  /* Sidebar always visible, below map */
  #side {
    position: static;
    width: 100%;
    height: auto;
    max-height: none;
    overflow: visible;
    border-top: 1px solid #e5e7eb;
    box-shadow: none;
    order: 2;
    display: block;
    padding: 12px 14px 18px;
  }

  .drawer-header { display: none !important; }

  #side, #side * { font-size: 15px; }
  .detail-label { width: 110px; }
  .pill { padding: 4px 10px; font-size: 13px; }

  #logo { max-width: 220px; height: auto; margin: 8px auto 6px; display:block; }

  #legendBlock {
    position: static;
    padding: 10px 0 8px;
    background: #fff;
    border-top: 1px solid #eee;
    margin-top: 12px;
    padding-left: 2px; padding-right: 2px;
  }
  #legendBlock .legend {
    grid-template-columns: 1.1rem 1fr;
    gap: .45rem .6rem;
  }
}
    </style>
</head>
<body>
    <div id="layout">
        <div id="mapCard">
            <div id="mapWrap">
                <svg id="mapSvg" viewBox="0 0 3200 2000" preserveAspectRatio="xMidYMid meet">
                    <g id="viewport">
                        <g id="siteplan"></g>
                        <g id="polys-layer"></g>
                    </g>
                </svg>
                <div class="zoom-controls">
                    <button id="zoomIn" title="Zoom In">+</button>
                    <button id="zoomOut" title="Zoom Out">−</button>
                    <button id="zoomReset" title="Reset View">⟲</button>
                </div>
            </div>
        </div>
        
        <div id="side">
            <img id="logo" src="/logo.jpg" alt="Lakeside Village Logo" onerror="this.style.display='none'" />
            <h2>Lakeside Sales</h2>
            <p class="muted">Interactive Stand Map</p>
            
            <input type="text" id="searchBox" placeholder="Search stand (e.g., Erf-001)..." />
            
            <h2 style="margin-top: 16px;">Stand Details</h2>
            <p class="muted">Hover over a stand on the map to see its details here.</p>
            
            <div id="details" class="muted">
                Hover over a stand on the map to see its details here.
            </div>
            
            <div id="legendBlock">
                <h3 style="margin: 0 0 8px; font-size: 16px;">Availability Guide</h3>
                <div class="legend">
                    <div class="swatch green"></div><span>For Sale</span>
                    <div class="swatch yellow"></div><span>Reserved</span>
                    <div class="swatch red"></div><span>Sold</span>
                    <div class="swatch gray"></div><span>Unknown</span>
                </div>
            </div>
        </div>
    </div>

    <script>
(function() {
    'use strict';
    
    const COLORS = {
        available: '#2ecc71',
        reserved: '#f4b400',
        unavailable: '#d93025',
        unknown: '#9ea3a8'
    };
    const FILL_OPACITY = 0.35;
    
    // Alignment tweaks to match polygons with site plan background
    const ALIGN_TWEAK = { scale: 0.744, dx: 275, dy: -105, rotateDeg: 0 };
    
    const svg = document.getElementById('mapSvg');
    const details = document.getElementById('details');
    const searchBox = document.getElementById('searchBox');
    let lockedId = '';
    let standsData = {};
    let polygonsData = [];
    
    // Normalize ID for matching
    function normalizeId(id) {
        if (!id) return '';
        let s = String(id).trim().toLowerCase();
        if (s.startsWith('stand-')) s = s.substring(6);
        return s;
    }
    
    function colorForStatus(key) {
        return COLORS[key] || COLORS.unknown;
    }
    
    function getPolysLayer() {
        return document.getElementById('polys-layer');
    }
    
    function getPlanNode() {
        let n = svg.querySelector('#siteplan');
        if (n) return n;
        
        const images = [...svg.querySelectorAll('image')];
        if (images.length) {
            const bestImg = images.reduce((best, im) => {
                const w = im.width?.baseVal?.value || +im.getAttribute('width') || 0;
                const h = im.height?.baseVal?.value || +im.getAttribute('height') || 0;
                const sBest = (best.width?.baseVal?.value || +best.getAttribute('width') || 0) *
                            (best.height?.baseVal?.value || +best.getAttribute('height') || 0);
                const sThis = w * h;
                return sThis > sBest ? im : best;
            }, images[0]);
            return bestImg.closest('g') || bestImg;
        }
        n = svg.querySelector('g[clip-path]');
        if (n) return n;
        return svg;
    }
    
    function artworkBBox() {
        const node = getPlanNode();
        if (!node || !node.getBBox) {
            const vb = svg.viewBox?.baseVal || { x:0, y:0, width:100, height:100 };
            return { x: vb.x, y: vb.y, width: vb.width, height: vb.height };
        }
        const bb = node.getBBox();
        if (!isFinite(bb.width) || !isFinite(bb.height) || bb.width === 0 || bb.height === 0) {
            const vb = svg.viewBox?.baseVal || { x:0, y:0, width:100, height:100 };
            return { x: vb.x, y: vb.y, width: vb.width, height: vb.height };
        }
        return bb;
    }
    
    function polygonsBBox(polys) {
        let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
        polys.forEach(({points}) => {
            points.trim().split(/\s+/).forEach(pair => {
                const [x, y] = pair.split(',').map(Number);
                if (Number.isFinite(x) && Number.isFinite(y)) {
                    if (x < minX) minX = x;
                    if (y < minY) minY = y;
                    if (x > maxX) maxX = x;
                    if (y > maxY) maxY = y;
                }
            });
        });
        return { minX, minY, maxX, maxY, width: maxX - minX, height: maxY - minY };
    }
    
    function fitSvgToArtwork() {
        const bb = artworkBBox();
        svg.setAttribute('viewBox', `${bb.x} ${bb.y} ${bb.width} ${bb.height}`);
    }
    
    function remapPolygonsToArtwork(polys) {
        const src = polygonsBBox(polys);
        const dst = artworkBBox();
        if (!isFinite(src.width) || !isFinite(src.height) || src.width <= 0 || src.height <= 0) return polys;
        
        let s = Math.min(dst.width / src.width, dst.height / src.height);
        s *= ALIGN_TWEAK.scale;
        
        const scaledW = src.width * s, scaledH = src.height * s;
        const tx = dst.x + (dst.width - scaledW) / 2 - src.minX * s;
        const ty = dst.y + (dst.height - scaledH) / 2 - src.minY * s;
        
        const cx = dst.x + dst.width / 2;
        const cy = dst.y + dst.height / 2;
        const rad = ALIGN_TWEAK.rotateDeg * Math.PI / 180;
        const cos = Math.cos(rad), sin = Math.sin(rad);
        
        return polys.map(({ id, points }) => ({
            id,
            points: points.trim().split(/\s+/).map(pair => {
                let [x, y] = pair.split(',').map(Number);
                let X = x * s + tx;
                let Y = y * s + ty;
                if (ALIGN_TWEAK.rotateDeg) {
                    const dx = X - cx, dy = Y - cy;
                    X = dx * cos - dy * sin + cx;
                    Y = dx * sin + dy * cos + cy;
                }
                X += ALIGN_TWEAK.dx;
                Y += ALIGN_TWEAK.dy;
                return `${X},${Y}`;
            }).join(' ')
        }));
    }
    
    function makePolygon(polyData) {
        const svgNS = 'http://www.w3.org/2000/svg';
        const p = document.createElementNS(svgNS, 'polygon');
        const polyId = polyData.id;
        
        p.setAttribute('points', polyData.points);
        if (polyId) p.setAttribute('id', polyId);
        
        const rec = standsData[polyId] || null;
        const stat = rec ? rec.status : 'unknown';
        
        p.style.fill = colorForStatus(stat);
        p.style.fillOpacity = FILL_OPACITY;
        p.style.stroke = '#000';
        p.style.strokeOpacity = 0.35;
        p.style.strokeWidth = '1';
        p.style.pointerEvents = 'auto';
        
        p.addEventListener('mouseenter', () => {
            if (!lockedId || lockedId === polyId) {
                showDetails(polyId, rec, lockedId === polyId);
            }
        });
        
        p.addEventListener('mouseleave', () => {
            if (!lockedId) clearDetails();
        });
        
        // Click-to-lock with movement slop
        let downX = 0, downY = 0, downPid = null;
        const CLICK_SLOP = 6;
        
        p.addEventListener('pointerdown', (ev) => {
            downX = ev.clientX;
            downY = ev.clientY;
            downPid = ev.pointerId;
            try { p.setPointerCapture(downPid); } catch(e) {}
        });
        
        p.addEventListener('pointerup', (ev) => {
            const moved = Math.hypot(ev.clientX - downX, ev.clientY - downY) > CLICK_SLOP;
            if (downPid !== null) {
                try { p.releasePointerCapture(downPid); } catch(e) {}
                downPid = null;
            }
            if (moved) return;
            
            if (lockedId === polyId) {
                lockedId = '';
                clearDetails();
                setActivePolygon(null);
            } else {
                lockedId = polyId;
                showDetails(polyId, rec, true);
                setActivePolygon(polyId);
            }
        });
        
        getPolysLayer().appendChild(p);
    }
    
    function setActivePolygon(id) {
        getPolysLayer().querySelectorAll('polygon').forEach(el => {
            el.classList.toggle('active', id && el.id === id);
        });
    }
    
    function showDetails(standId, rec, locked = false) {
        const label = rec?.id || standId || '(unknown)';
        const statusKeyed = rec?.status || 'unknown';
        const statusTxt = rec?.rawStatus || statusKeyed;
        
        details.classList.remove('muted');
        
        let html = `
            <div class="detail-row">
                <div class="detail-label">Stand:</div>
                <div><b>${escapeHtml(label)}</b></div>
            </div>
            <div class="detail-row">
                <div class="detail-label">Status:</div>
                <div>
                    <span class="pill" style="background:${colorForStatus(statusKeyed)}22;border-color:${colorForStatus(statusKeyed)}55">
                        ${escapeHtml(statusTxt)}
                    </span>
                </div>
            </div>
        `;
        
        if (rec && rec.row) {
            const row = rec.row;
            const skipCols = ['standid', 'status', 'lastupdated'];
            
            for (let key in row) {
                if (skipCols.includes(key.toLowerCase())) continue;
                
                let val = row[key] || '';
                if (key.toLowerCase() === 'size' && val) {
                    val = `${val} m²`;
                }
                
                html += `
                    <div class="detail-row">
                        <div class="detail-label">${escapeHtml(key)}:</div>
                        <div>${escapeHtml(val)}</div>
                    </div>
                `;
            }
        } else {
            html += '<div class="muted">No extra data in sheet for this stand.</div>';
        }
        
        if (locked) {
            html += '<div class="muted" style="margin-top:8px">Locked. Click the stand again to unlock or press Esc.</div>';
        }
        
        details.innerHTML = html;
    }
    
    function clearDetails() {
        if (lockedId) return;
        details.classList.add('muted');
        details.textContent = 'Hover over a stand on the map to see its details here.';
    }
    
    function escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
    
    // Pan & Zoom
    function setupPanZoom() {
        const vp = document.getElementById('viewport');
        if (!vp) return;
        
        let scale = 1, minScale = 0.7, maxScale = 4;
        let tx = 0, ty = 0;
        let isPanning = false;
        let lastX = 0, lastY = 0;
        
        const zoomInBtn = document.getElementById('zoomIn');
        const zoomOutBtn = document.getElementById('zoomOut');
        const zoomResetBtn = document.getElementById('zoomReset');
        
        function applyTransform() {
            vp.setAttribute('transform', `translate(${tx} ${ty}) scale(${scale})`);
            svg.classList.toggle('can-pan', scale > 1.001);
        }
        
        function zoomAt(clientX, clientY, delta) {
            const rect = svg.getBoundingClientRect();
            const cx = clientX ?? (rect.left + rect.width / 2);
            const cy = clientY ?? (rect.top + rect.height / 2);
            const factor = Math.exp(delta);
            
            const newScale = Math.min(maxScale, Math.max(minScale, scale * factor));
            if (newScale === scale) return;
            
            tx = cx - (cx - tx) * (newScale / scale);
            ty = cy - (cy - ty) * (newScale / scale);
            
            scale = newScale;
            applyTransform();
        }
        
        svg.addEventListener('wheel', (e) => {
            e.preventDefault();
            const delta = -e.deltaY * 0.0015;
            zoomAt(e.clientX, e.clientY, delta);
        }, { passive: false });
        
        svg.addEventListener('pointerdown', (e) => {
            if (e.target.closest && e.target.closest('#polys-layer polygon')) return;
            if (e.button !== 0) return;
            isPanning = true;
            svg.setPointerCapture(e.pointerId);
            svg.classList.add('grabbing');
            lastX = e.clientX;
            lastY = e.clientY;
        });
        
        svg.addEventListener('pointermove', (e) => {
            if (!isPanning) return;
            const dx = e.clientX - lastX;
            const dy = e.clientY - lastY;
            lastX = e.clientX;
            lastY = e.clientY;
            tx += dx;
            ty += dy;
            applyTransform();
        });
        
        svg.addEventListener('pointerup', () => {
            isPanning = false;
            svg.classList.remove('grabbing');
        });
        
        svg.addEventListener('pointercancel', () => {
            isPanning = false;
            svg.classList.remove('grabbing');
        });
        
        zoomInBtn?.addEventListener('click', () => zoomAt(undefined, undefined, +0.25));
        zoomOutBtn?.addEventListener('click', () => zoomAt(undefined, undefined, -0.25));
        zoomResetBtn?.addEventListener('click', () => {
            scale = 1;
            tx = 0;
            ty = 0;
            applyTransform();
        });
        
        applyTransform();
    }
    
    // Search functionality
    function setupSearch() {
        searchBox.addEventListener('input', (e) => {
            const query = e.target.value.trim().toLowerCase();
            if (!query) return;
            
            // Find matching polygon
            const match = polygonsData.find(p => {
                const id = p.id.toLowerCase();
                return id.includes(query) || normalizeId(id).includes(query);
            });
            
            if (match) {
                // Lock on this polygon
                lockedId = match.id;
                const rec = standsData[match.id] || null;
                showDetails(match.id, rec, true);
                setActivePolygon(match.id);
                
                // Zoom to polygon bbox
                zoomToPolygon(match);
            }
        });
    }
    
    function zoomToPolygon(poly) {
        const points = poly.points.trim().split(/\s+/);
        let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
        
        points.forEach(pair => {
            const [x, y] = pair.split(',').map(Number);
            if (isFinite(x) && isFinite(y)) {
                if (x < minX) minX = x;
                if (y < minY) minY = y;
                if (x > maxX) maxX = x;
                if (y > maxY) maxY = y;
            }
        });
        
        if (!isFinite(minX)) return;
        
        const padding = 100;
        const viewBox = `${minX - padding} ${minY - padding} ${maxX - minX + 2 * padding} ${maxY - minY + 2 * padding}`;
        svg.setAttribute('viewBox', viewBox);
    }
    
    // Load site plan background
    function loadSitePlan(callback) {
        // Load the index.html and extract the embedded image
        fetch('/siteplan.svg')
            .then(response => response.text())
            .then(html => {
                const parser = new DOMParser();
                const doc = parser.parseFromString(html, 'text/html');
                const imageElement = doc.querySelector('image[id="image_2"]');
                
                if (imageElement) {
                    const svgNS = 'http://www.w3.org/2000/svg';
                    const siteplanGroup = document.getElementById('siteplan');
                    
                    // Clone the entire layer structure from original
                    const layer1 = doc.querySelector('g[id="layer_1"]');
                    if (layer1) {
                        const clonedLayer = layer1.cloneNode(true);
                        siteplanGroup.appendChild(clonedLayer);
                        
                        // Wait for image to load, then fit viewBox and callback
                        setTimeout(() => {
                            fitSvgToArtwork();
                            if (callback) callback();
                        }, 100);
                    }
                }
            })
            .catch(err => {
                console.log('Site plan not loaded:', err);
                if (callback) callback();
            });
    }
    
    // Initialize
    async function init() {
        try {
            // Load polygons and stands data first
            const [polygonsResp, standsResp] = await Promise.all([
                fetch('/api/polygons'),
                fetch('/api/stands')
            ]);
            
            const polygonsJson = await polygonsResp.json();
            const standsJson = await standsResp.json();
            
            polygonsData = polygonsJson.polygons || [];
            standsData = standsJson.stands || {};
            
            // Load site plan background, then align and render polygons
            loadSitePlan(() => {
                // Remap polygons to align with artwork
                const remappedPolygons = remapPolygonsToArtwork(polygonsData);
                
                // Render polygons
                const layer = getPolysLayer();
                layer.innerHTML = '';
                remappedPolygons.forEach(p => makePolygon(p));
                
                console.log(`Loaded ${polygonsData.length} polygons and ${Object.keys(standsData).length} stand records`);
            });
            
        } catch (err) {
            console.error('Error loading data:', err);
            details.innerHTML = '<div style="color: red;">Error loading stand data. Please refresh the page.</div>';
        }
    }
    
    // Keyboard shortcuts
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && lockedId) {
            lockedId = '';
            clearDetails();
            setActivePolygon(null);
        }
    });
    
    // Start
    document.addEventListener('DOMContentLoaded', () => {
        init();
        setupPanZoom();
        setupSearch();
    });
})();
    </script>
</body>
</html>
'''


if __name__ == '__main__':
    logger.info(f"Starting Lakeside Sales Flask app on port {PORT}")
    logger.info(f"Sheet URL configured: {bool(SHEET_CSV_URL)}")
    app.run(host='0.0.0.0', port=PORT, debug=False)
