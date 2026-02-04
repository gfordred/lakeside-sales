/* ===========================
   CONFIG — CHANGE THESE
   =========================== 
const SHEET_CSV_URL = "https://docs.google.com/spreadsheets/d/1MwhCOyGu3QycOVoU9DKCfRuXO4o6HVjuKcxjuWyveKg/edit?gid=0#gid=0/pub?gid=0&single=true&output=csv";

 const SHEET_CSV_URL = "https://docs.google.com/spreadsheets/d/e/2PACX-1vTlv6QJ03KC1bqTbshjE8ykrBPiz7ki5yZ0HjR6Q7wa6L6PObaPNLjBPhnBSa7yU7i5SkIrJx4Ddkhz/pub?gid=0&single=true&output=csv";
*/
const SHEET_CSV_URL = "https://docs.google.com/spreadsheets/d/e/2PACX-1vSJOgpf8Lu7bmrAg5LdMPEGoNLNg_an9FKR0Ix-h27VWmzkIohrtwrISUkcs9c6Of26znTnXBamvrog/pub?output=csv";

const ID_COLUMN       = "StandID";
const STATUS_COLUMN   = "Status";
const SIZE_COLUMN     = "Size";
const PRICE_COLUMN    = "Price";
const UPDATED_COLUMN  = "LastUpdated";   // <- read from sheet, show only at bottom

// If you fetch polygons from a file, set it here; otherwise leave "" and use inline JSON.
const POLYGONS_JSON_URL = "polygons.json";

const COLORS = {
  available:   "#2ecc71",
  reserved:    "#f4b400",
  unavailable: "#d93025",
  unknown:     "#9ea3a8"
};
const FILL_OPACITY = 0.35;

// Fine-tune alignment if needed later
const ALIGN_TWEAK = { scale: 0.744, dx: 475, dy: -105, rotateDeg: 0 };

/* ===========================
   RUNTIME ELEMENTS
   =========================== */
const svg     = document.getElementById("mapSvg");
const details = document.getElementById("details");
let lockedId  = "";
let mapInteractionEnabled = false;
let isMobile = false;
let globalStatusMap = {};

/* ===========================
   HELPERS
   =========================== */
const norm = s => String(s ?? "").trim().toLowerCase();

const statusKey = s => {
  const t = norm(s);
  if (t.startsWith("avail")) return "available";
  if (t.startsWith("reser") || t === "pending") return "reserved";
  if (t.startsWith("unavail")) return "unavailable";
  return "unknown";
};

function parseCSV(text) {
  const rows = []; let row = [], field = "", inQ = false;
  for (let i=0;i<text.length;i++) {
    const c = text[i];
    if (inQ) {
      if (c === '"') {
        if (text[i+1] === '"') { field += '"'; i++; }
        else { inQ = false; }
      } else field += c;
    } else {
      if (c === '"') inQ = true;
      else if (c === ",") { row.push(field); field = ""; }
      else if (c === "\n") { row.push(field); rows.push(row); row = []; field=""; }
      else if (c === "\r") {} else field += c;
    }
  }
  if (field.length || row.length) { row.push(field); rows.push(row); }
  return rows;
}

function formatSAST(isoLike) {
  if (!isoLike) return "";
  // Accept "YYYY-MM-DDTHH:mm:ss" or "YYYY-MM-DD HH:mm:ss"
  const d = new Date(String(isoLike).trim().replace(" ", "T"));
  if (Number.isNaN(+d)) return String(isoLike);
  return new Intl.DateTimeFormat("en-ZA", {
    timeZone: "Africa/Johannesburg",
    year: "numeric", month: "long", day: "2-digit",
    hour: "2-digit", minute: "2-digit"
  }).format(d) + " SAST";
}

/* ===========================
   ARTWORK / POLYGON MAPPING
   =========================== */
function getPolysLayer(){
  let layer = svg.querySelector('#polys-layer');
  if(!layer){
    const vp = svg.querySelector('#viewport') || svg;
    layer = document.createElementNS(svg.namespaceURI, 'g');
    layer.setAttribute('id','polys-layer');
    vp.appendChild(layer);
  }
  return layer;
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
  let minX=Infinity, minY=Infinity, maxX=-Infinity, maxY=-Infinity;
  polys.forEach(({points}) => {
    points.trim().split(/\s+/).forEach(pair => {
      const [x,y] = pair.split(',').map(Number);
      if (Number.isFinite(x) && Number.isFinite(y)) {
        if (x<minX) minX=x; if (y<minY) minY=y;
        if (x>maxX) maxX=x; if (y>maxY) maxY=y;
      }
    });
  });
  return { minX, minY, maxX, maxY, width:maxX-minX, height:maxY-minY };
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
  const tx = dst.x + (dst.width  - scaledW)/2 - src.minX * s;
  const ty = dst.y + (dst.height - scaledH)/2 - src.minY * s;

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
        Y = dx * sin - dy * cos + cy;
      }
      X += ALIGN_TWEAK.dx;
      Y += ALIGN_TWEAK.dy;
      return `${X},${Y}`;
    }).join(' ')
  }));
}

/* ===========================
   SHEET & POLYGONS LOAD
   =========================== */
async function loadSheet() {
  if (!SHEET_CSV_URL) return { statusMap:{}, lastUpdated:"" };
  const res  = await fetch(SHEET_CSV_URL, { cache: "no-store" });
  const text = await res.text();

  const rows = parseCSV(text);
  if (!rows.length) return { statusMap:{}, lastUpdated:"" };

  const headers = rows[0].map(h => h.trim());
  const idx = {
    id:      headers.findIndex(h => norm(h) === norm(ID_COLUMN)),
    status:  headers.findIndex(h => norm(h) === norm(STATUS_COLUMN)),
    updated: headers.findIndex(h => norm(h) === norm(UPDATED_COLUMN))
  };

  // Pull *one* timestamp from the LastUpdated column (first non-empty cell)
  let lastUpdatedVal = "";
  if (idx.updated >= 0) {
    for (let r = 1; r < rows.length; r++) {
      const v = rows[r][idx.updated];
      if (v && String(v).trim()) { lastUpdatedVal = String(v).trim(); break; }
    }
  }

  // Build the status map
  const map = {};
  for (let r=1; r<rows.length; r++) {
    const row   = rows[r];
    const idVal = row[idx.id] ?? "";
    const sVal  = row[idx.status] ?? "";
    if (!idVal) continue;
    map[norm(idVal)] = {
      id: String(idVal).trim(),
      status: statusKey(sVal),
      rawStatus: sVal,
      row: Object.fromEntries(headers.map((h,i)=>[h,row[i]]))
    };
  }
  return { statusMap: map, lastUpdated: lastUpdatedVal };
}

async function loadPolygons(){
  let polygons = [];
  if (POLYGONS_JSON_URL){
    const res = await fetch(POLYGONS_JSON_URL, { cache:'no-store' });
    const data = await res.json();
    polygons = Array.isArray(data.polygons) ? data.polygons : [];
  } else {
    const inline = document.getElementById('polygons-data');
    if (inline && inline.textContent.trim()){
      try {
        const data = JSON.parse(inline.textContent);
        polygons = Array.isArray(data.polygons) ? data.polygons : [];
      } catch (e){
        console.error('Polygons inline JSON parse error:', e);
        alert('Polygons JSON is not valid. Check for trailing commas or stray text.');
        return [];
      }
    }
  }
  
  // Detect and fix duplicate IDs
  const idMap = new Map();
  const normalized = polygons.map((poly, idx) => {
    let id = poly.id;
    const normalizedId = norm(id);
    
    if (idMap.has(normalizedId)) {
      const count = idMap.get(normalizedId);
      idMap.set(normalizedId, count + 1);
      const newId = `${id}-dup${count}`;
      console.warn(`Duplicate polygon ID detected: "${id}" renamed to "${newId}"`);
      return { ...poly, id: newId };
    } else {
      idMap.set(normalizedId, 1);
      return poly;
    }
  });
  
  return normalized;
}

/* ===========================
   DRAWING & INTERACTION
   =========================== */
function colorForStatus(key) { return COLORS[key] || COLORS.unknown; }

function makePolygon({ id: polyId, points }, statusMap) {
  const svgNS = "http://www.w3.org/2000/svg";
  const p = document.createElementNS(svgNS, "polygon");
  p.setAttribute("points", points);
  if (polyId) p.setAttribute("id", polyId);
  p.setAttribute("data-stand-id", polyId);

  const rec =
    statusMap[norm(polyId || "")] ||
    statusMap[norm((polyId || "").replace(/^stand-/, ""))] ||
    null;
  const stat = rec ? rec.status : "unknown";

  p.style.fill = (COLORS[stat] || COLORS.unknown);
  p.style.fillOpacity = FILL_OPACITY;
  p.style.stroke = "#000";
  p.style.strokeOpacity = 0.35;
  p.style.strokeWidth = "1";
  p.style.pointerEvents = "auto";

  // Create forgiving hit area (invisible overlay with wider stroke)
  const hitArea = document.createElementNS(svgNS, "polygon");
  hitArea.setAttribute("points", points);
  hitArea.setAttribute("data-hit-for", polyId);
  hitArea.style.fill = "transparent";
  hitArea.style.stroke = "transparent";
  hitArea.style.strokeWidth = isMobile ? "15" : "8";
  hitArea.style.pointerEvents = "stroke";
  hitArea.style.cursor = "pointer";

  // Shared interaction handlers
  const handlePointerInteraction = (target) => {
    const standId = target.getAttribute("data-stand-id") || target.getAttribute("data-hit-for");
    if (!standId) return null;
    return standId;
  };

  const onPointerEnter = (ev) => {
    const standId = handlePointerInteraction(ev.target);
    if (standId && (!lockedId || lockedId === standId)) {
      const currentRec = globalStatusMap[norm(standId)] || globalStatusMap[norm(standId.replace(/^stand-/, ""))] || null;
      showDetails(standId, currentRec, lockedId === standId);
    }
  };

  const onPointerLeave = (ev) => {
    if (!lockedId) clearDetails();
  };

  // Click-to-lock with movement slop
  let downX = 0, downY = 0, downPid = null;
  const CLICK_SLOP = isMobile ? 10 : 6;

  const onPointerDown = (ev) => {
    downX = ev.clientX; downY = ev.clientY;
    downPid = ev.pointerId;
  };

  const onPointerUp = (ev) => {
    const standId = handlePointerInteraction(ev.target);
    if (!standId) return;
    
    const moved = Math.hypot(ev.clientX - downX, ev.clientY - downY) > CLICK_SLOP;
    downPid = null;
    if (moved) return;

    if (lockedId === standId) {
      lockedId = "";
      clearDetails();
      setActivePolygon(null);
    } else {
      lockedId = standId;
      const currentRec = globalStatusMap[norm(standId)] || globalStatusMap[norm(standId.replace(/^stand-/, ""))] || null;
      showDetails(standId, currentRec, true);
      setActivePolygon(standId);
      
      // Scroll details into view on mobile
      if (isMobile) {
        setTimeout(() => {
          const detailsEl = document.getElementById('details');
          if (detailsEl) {
            detailsEl.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
          }
        }, 100);
      }
    }
  };

  // Attach handlers to both polygon and hit area
  [p, hitArea].forEach(el => {
    el.addEventListener("mouseenter", onPointerEnter);
    el.addEventListener("mouseleave", onPointerLeave);
    el.addEventListener("pointerdown", onPointerDown);
    el.addEventListener("pointerup", onPointerUp);
  });

  const layer = getPolysLayer();
  layer.appendChild(p);
  layer.appendChild(hitArea);
}

function setActivePolygon(id) {
  getPolysLayer().querySelectorAll("polygon")
    .forEach(el => el.classList.toggle("active", id && el.id === id));
}

function showDetails(standId, rec, locked = false) {
  const label = rec?.id || standId || "(unknown)";
  const statusKeyed = rec?.status || "unknown";
  const statusTxt = rec?.rawStatus || statusKeyed;

  details.classList.remove("muted");
  details.innerHTML = `
    <div class="detail-row"><div class="detail-label">Stand:</div><div><b>${label}</b></div></div>
    <div class="detail-row"><div class="detail-label">Status:</div>
      <div><span class="pill" style="background:${colorForStatus(statusKeyed)}22;border-color:${colorForStatus(statusKeyed)}55">
        ${statusTxt}
      </span></div>
    </div>
    ${
      rec
        ? Object.entries(rec.row)
            // Hide ID, Status, and LastUpdated from the details panel
            .filter(([h]) =>
              norm(h)!==norm(ID_COLUMN) &&
              norm(h)!==norm(STATUS_COLUMN) &&
              norm(h)!==norm(UPDATED_COLUMN)
            )
            .map(([h,v]) => {
              let val = v || "";
              if (norm(h) === norm(SIZE_COLUMN) && val) val = `${val} m²`;
              return `<div class="detail-row"><div class="detail-label">${h}:</div><div>${val}</div></div>`;
            }).join("")
        : `<div class="muted">No extra data in sheet for this stand.</div>`
    }
    ${locked ? `<div class="muted" style="margin-top:8px">Locked. Click the stand again to unlock or press esc.</div>` : "" }
  `;
}

function clearDetails() {
  if (lockedId) return;
  details.classList.add("muted");
  details.textContent = "Hover over a stand on the map to see its details here.";
}

/* ===========================
   PAN & ZOOM
   =========================== */
function setupPanZoom() {
  const vp = svg.querySelector('#viewport');
  if (!vp) return;

  let scale = 1, minScale = 0.7, maxScale = 4;
  let tx = 0, ty = 0;
  let isPanning = false;
  let lastX = 0, lastY = 0;

  const zoomInBtn = document.getElementById('zoomIn');
  const zoomOutBtn = document.getElementById('zoomOut');
  const zoomResetBtn = document.getElementById('zoomReset');

  // Add aria-labels for accessibility
  if (zoomInBtn) zoomInBtn.setAttribute('aria-label', 'Zoom in');
  if (zoomOutBtn) zoomOutBtn.setAttribute('aria-label', 'Zoom out');
  if (zoomResetBtn) zoomResetBtn.setAttribute('aria-label', 'Reset zoom');

  function applyTransform() {
    vp.setAttribute('transform', `translate(${tx} ${ty}) scale(${scale})`);
    svg.classList.toggle('can-pan', scale > 1.001);
  }

  function zoomAt(clientX, clientY, delta) {
    const rect = svg.getBoundingClientRect();
    const cx = clientX ?? (rect.left + rect.width/2);
    const cy = clientY ?? (rect.top + rect.height/2);
    const factor = Math.exp(delta);

    const newScale = Math.min(maxScale, Math.max(minScale, scale * factor));
    if (newScale === scale) return;

    tx = cx - (cx - tx) * (newScale/scale);
    ty = cy - (cy - ty) * (newScale/scale);

    scale = newScale;
    applyTransform();
  }

  svg.addEventListener('wheel', (e) => {
    if (isMobile && !mapInteractionEnabled) return;
    e.preventDefault();
    const delta = -e.deltaY * 0.0015;
    zoomAt(e.clientX, e.clientY, delta);
  }, { passive:false });

  svg.addEventListener('pointerdown', (e) => {
    if (e.target.closest && e.target.closest('#polys-layer polygon')) return;
    if (e.target.closest && e.target.closest('#polys-layer polygon[data-hit-for]')) return;
    if (e.button !== 0) return;
    
    // On mobile, only allow panning if map interaction is enabled
    if (isMobile && !mapInteractionEnabled) return;
    
    isPanning = true;
    svg.setPointerCapture(e.pointerId);
    svg.classList.add('grabbing');
    lastX = e.clientX; lastY = e.clientY;
  });
  svg.addEventListener('pointermove', (e) => {
    if (!isPanning) return;
    const dx = e.clientX - lastX;
    const dy = e.clientY - lastY;
    lastX = e.clientX; lastY = e.clientY;
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
  zoomResetBtn?.addEventListener('click', () => { scale = 1; tx = 0; ty = 0; applyTransform(); });

  applyTransform();
}

/* ===========================
   MAP INTERACTION MODE (MOBILE)
   =========================== */
function setupMapInteractionToggle() {
  // Check if mobile
  isMobile = window.matchMedia('(max-width: 768px)').matches;
  if (!isMobile) return;

  // Create toggle button
  const mapWrap = document.getElementById('mapWrap');
  if (!mapWrap) return;

  const toggleContainer = document.createElement('div');
  toggleContainer.className = 'map-mode-toggle';
  
  const toggleBtn = document.createElement('button');
  toggleBtn.setAttribute('aria-label', 'Toggle map interaction mode');
  toggleBtn.setAttribute('aria-pressed', 'false');
  
  // Load saved preference
  const savedMode = localStorage.getItem('mapInteractionMode');
  if (savedMode === 'enabled') {
    mapInteractionEnabled = true;
  }
  
  function updateToggleUI() {
    if (mapInteractionEnabled) {
      toggleBtn.textContent = '🗺️ Move Map';
      toggleBtn.classList.add('active');
      toggleBtn.setAttribute('aria-pressed', 'true');
      svg.style.touchAction = 'none';
    } else {
      toggleBtn.textContent = '📜 Scroll Page';
      toggleBtn.classList.remove('active');
      toggleBtn.setAttribute('aria-pressed', 'false');
      svg.style.touchAction = 'pan-y pinch-zoom';
    }
  }
  
  toggleBtn.addEventListener('click', () => {
    mapInteractionEnabled = !mapInteractionEnabled;
    localStorage.setItem('mapInteractionMode', mapInteractionEnabled ? 'enabled' : 'disabled');
    updateToggleUI();
  });
  
  updateToggleUI();
  toggleContainer.appendChild(toggleBtn);
  mapWrap.appendChild(toggleContainer);
  
  // Update on resize
  window.addEventListener('resize', () => {
    const nowMobile = window.matchMedia('(max-width: 768px)').matches;
    if (nowMobile !== isMobile) {
      isMobile = nowMobile;
      if (!isMobile) {
        svg.style.touchAction = 'none';
      } else {
        updateToggleUI();
      }
    }
  });
}

/* ===========================
   INIT
   =========================== */
async function init(){
  fitSvgToArtwork();

  const [{ statusMap, lastUpdated }, polysRaw] = await Promise.all([loadSheet(), loadPolygons()]);
  globalStatusMap = statusMap;
  const polys = remapPolygonsToArtwork(polysRaw);

  const layer = getPolysLayer();
  layer.innerHTML = "";
  polys.forEach(p => makePolygon(p, statusMap));

  // Bottom line only (sheet-wide timestamp)
  //const footerEl = document.getElementById("lastUpdated");
  //if (footerEl) {
    //footerEl.textContent = lastUpdated
    //  ? `Last updated ${formatSAST(lastUpdated)}`
   //   : "Last updated …";
 // }
}

document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape' && lockedId) {
    lockedId = "";
    clearDetails();
    setActivePolygon(null);
  }
});

document.addEventListener('DOMContentLoaded', () => {
  // Detect mobile early
  isMobile = window.matchMedia('(max-width: 768px)').matches;
  
  init();
  setupPanZoom();
  setupMapInteractionToggle();
});





