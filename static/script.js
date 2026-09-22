// ── MAP SETUP ────────────────────────────────────────────────
const map = L.map("map").setView([28.6139, 77.2090], 11);
L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
  attribution: "© OpenStreetMap contributors"
}).addTo(map);

let currentLayers = [];
let multiStops = [];

// ── TAB SWITCHING ─────────────────────────────────────────────
function switchTab(tab) {
  document.querySelectorAll(".tab").forEach(t => t.classList.remove("active"));
  document.querySelectorAll(".panel").forEach(p => p.style.display = "none");

  if (tab === "passenger") {
    document.getElementById("passenger-panel").style.display = "flex";
    document.querySelectorAll(".tab")[0].classList.add("active");
  } else {
    document.getElementById("planner-panel").style.display = "flex";
    document.querySelectorAll(".tab")[1].classList.add("active");
  }

  // recalculate map height after panel switch
  recalcMapHeight();
}

function recalcMapHeight() {
  const navbar = document.getElementById("navbar").offsetHeight;
  const panel = document.querySelector(".panel:not([style*='display:none'])").offsetHeight;
  document.getElementById("map").style.height = `calc(100vh - ${navbar + panel}px)`;
}

// ── AUTOCOMPLETE ──────────────────────────────────────────────
const debounceTimers = {};

async function showSuggestions(inputId) {
  const inputEl = document.getElementById(
    inputId === "multi" ? "multi-input" : inputId
  );
  const query = inputEl.value.trim();
  const suggestionsBox = document.getElementById(inputId + "-suggestions");

  if (query.length < 2) {
    suggestionsBox.style.display = "none";
    return;
  }

  clearTimeout(debounceTimers[inputId]);
  debounceTimers[inputId] = setTimeout(async () => {
    const res = await fetch(`http://127.0.0.1:8000/search-stops?query=${encodeURIComponent(query)}`);
    const data = await res.json();

    if (!data.results.length) {
      suggestionsBox.style.display = "none";
      return;
    }

    suggestionsBox.innerHTML = data.results.map(stop => `
      <div class="suggestion-item"
        onmousedown="selectStop('${inputId}', '${stop.stop_name}', ${stop.stop_lat}, ${stop.stop_lon})">
        ${stop.stop_name}
      </div>
    `).join("");

    suggestionsBox.style.display = "block";
  }, 500);
}

function selectStop(inputId, name, lat, lon) {
  const inputEl = document.getElementById(
    inputId === "multi" ? "multi-input" : inputId
  );
  inputEl.value = name;
  inputEl.dataset.lat = lat;
  inputEl.dataset.lon = lon;
  document.getElementById(inputId + "-suggestions").style.display = "none";
}

function hideSuggestions(inputId) {
  setTimeout(() => {
    const box = document.getElementById(inputId + "-suggestions");
    if (box) box.style.display = "none";
  }, 150);
}

// ── SIMPLE ROUTE ──────────────────────────────────────────────
async function findRoute() {
  const from = document.getElementById("from").value.trim();
  const to = document.getElementById("to").value.trim();

  if (!from || !to) { showError("Please enter both stops"); return; }

  const res = await fetch(
    `http://127.0.0.1:8000/shortest-path?from_stop=${encodeURIComponent(from)}&to_stop=${encodeURIComponent(to)}`
  );

  if (!res.ok) {
    const err = await res.json();
    showError(err.detail);
    return;
  }

  const data = await res.json();
  drawRoute(data.path, "royalblue", data.road_geometry);
  showInfo("Route Found", data.from, data.to, data.num_stops, data.total_distance_km);
}

// ── MULTI STOP ────────────────────────────────────────────────
function addMultiStop() {
  const input = document.getElementById("multi-input");
  const name = input.value.trim();
  const lat = parseFloat(input.dataset.lat);
  const lon = parseFloat(input.dataset.lon);

  if (!name || isNaN(lat) || isNaN(lon)) {
    showError("Please select a stop from the dropdown");
    return;
  }

  multiStops.push({ stop_name: name, lat, lon });
  input.value = "";
  delete input.dataset.lat;
  delete input.dataset.lon;
  renderStopTags();
}

function removeStop(index) {
  multiStops.splice(index, 1);
  renderStopTags();
}

function renderStopTags() {
  const list = document.getElementById("multi-stop-list");
  list.innerHTML = multiStops.map((s, i) => `
    <div class="stop-tag">
      ${i + 1}. ${s.stop_name}
      <span onclick="removeStop(${i})">×</span>
    </div>
  `).join("");
}

async function optimizeMulti() {
  if (multiStops.length < 2) {
    showError("Add at least 2 stops first");
    return;
  }

  const res = await fetch("http://127.0.0.1:8000/optimize-route", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(multiStops)
  });

  const data = await res.json();
  drawRoute(data.optimized_stops, "orange", data.road_geometry);
  showInfo("Optimized Route", data.optimized_stops[0].stop_name,
    data.optimized_stops[data.optimized_stops.length - 1].stop_name,
    data.optimized_stops.length, data.total_distance_km);
}

function clearMulti() {
  multiStops = [];
  renderStopTags();
  clearMap();
}

/// ── PLANNER FEATURES ─────────────────────────────────────────
async function findDeadZones() {
  clearMap();
  const res = await fetch("http://127.0.0.1:8000/dead-zones?grid_size_km=0.5&radius_km=1.0");
  const data = await res.json();

  data.dead_zones.forEach(z => {
    const marker = L.circleMarker([z.lat, z.lon], {
      radius: 5, color: "red", fillColor: "red", fillOpacity: 0.5, weight: 1
    }).addTo(map).bindPopup(`Dead zone<br>Nearest stop: ${z.nearest_stop_km} km away`);
    currentLayers.push(marker);
  });

  showResultsList(`Dead Zones Found: ${data.count}`,
    [`Areas with no bus stop within ${data.radius_km} km`]);

  if (data.dead_zones.length) {
    const bounds = L.latLngBounds(data.dead_zones.map(z => [z.lat, z.lon]));
    map.fitBounds(bounds, { padding: [40, 40] });
  }
}

async function findCriticalStops() {
  clearMap();
  const res = await fetch("http://127.0.0.1:8000/critical-stops?top_n=15");
  const data = await res.json();

  data.critical_stops.forEach((s, i) => {
    const marker = L.circleMarker([s.lat, s.lon], {
      radius: 10 - i * 0.3, color: "orange", fillColor: "orange", fillOpacity: 0.7, weight: 2
    }).addTo(map).bindPopup(`<b>${s.stop_name}</b><br>Centrality: ${s.centrality_score}`);
    currentLayers.push(marker);
  });

  showResultsList("Critical Stops (top " + data.count + ")",
    data.critical_stops.map((s, i) => `${i + 1}. ${s.stop_name} (score: ${s.centrality_score})`));

  if (data.critical_stops.length) {
    const bounds = L.latLngBounds(data.critical_stops.map(s => [s.lat, s.lon]));
    map.fitBounds(bounds, { padding: [40, 40] });
  }
}

let heatLayer = null;
async function showHeatmap() {
  clearMap();
  if (heatLayer) { map.removeLayer(heatLayer); heatLayer = null; }

  const res = await fetch("http://127.0.0.1:8000/all-stops");
  const data = await res.json();

  const points = data.stops.map(s => [s.lat, s.lon, 0.5]);
  heatLayer = L.heatLayer(points, { radius: 18, blur: 15, maxZoom: 15 }).addTo(map);
  currentLayers.push(heatLayer);

  showResultsList("Coverage Heatmap", [`${data.stops.length} stops plotted by density`]);
  map.setView([28.6139, 77.2090], 11);
}

async function findRedundantRoutes() {
  clearMap();
  const res = await fetch("http://127.0.0.1:8000/route-redundancy?threshold=0.7");
  const data = await res.json();

  if (!data.redundant_pairs.length) {
    showResultsList("Route Redundancy", ["No highly overlapping trip pairs found above the 70% threshold."]);
    return;
  }

  showResultsList(`Redundant Route Pairs (${data.count})`,
    data.redundant_pairs.map(p =>
      `Trip ${p.trip_a} ↔ Trip ${p.trip_b} — ${Math.round(p.overlap * 100)}% overlap (${p.shared_stops} shared stops)`
    ));
}

function showResultsList(title, lines) {
  const panel = document.getElementById("results-panel");
  panel.innerHTML = `<h3>${title}</h3>` + lines.map(l => `<p>${l}</p>`).join("");
  panel.style.display = "block";
}

// ── MAP HELPERS ───────────────────────────────────────────────
function drawRoute(stops, color, roadGeometry) {
  clearMap();
  const latlngs = stops.map(s => [s.lat, s.lon]);

  // use real road geometry if provided, otherwise fall back to straight lines between stops
  const lineCoords = (roadGeometry && roadGeometry.length) ? roadGeometry : latlngs;

  // draw the route line FIRST so stop markers always render on top of it
  const line = L.polyline(lineCoords, { color, weight: 5, opacity: 0.8 }).addTo(map);
  currentLayers.push(line);

  stops.forEach((stop, i) => {
    const isFirst = i === 0;
    const isLast = i === stops.length - 1;
    // white fill + colored border so markers never blend into a same-colored route line
    const border = isFirst ? "green" : isLast ? "red" : color;
    const r = (isFirst || isLast) ? 10 : 7;

    const marker = L.circleMarker([stop.lat, stop.lon], {
      radius: r, color: border, fillColor: "#fff", fillOpacity: 1, weight: 3
    }).addTo(map).bindPopup(`<b>${stop.stop_name}</b><br>Stop ${i + 1} of ${stops.length}`);

    currentLayers.push(marker);
  });

  map.fitBounds(line.getBounds(), { padding: [40, 40] });
}

function clearMap() {
  currentLayers.forEach(l => map.removeLayer(l));
  currentLayers = [];
  document.getElementById("info").style.display = "none";
  const panel = document.getElementById("results-panel");
  if (panel) panel.style.display = "none";
}

// ── UI HELPERS ────────────────────────────────────────────────
function showInfo(title, from, to, stops, dist) {
  document.getElementById("info").style.display = "block";
  document.getElementById("info-title").innerText = title;
  document.getElementById("info-from").innerText = "From: " + from;
  document.getElementById("info-to").innerText = "To: " + to;
  document.getElementById("info-stops").innerText = "Stops: " + stops;
  document.getElementById("info-dist").innerText = "Distance: " + dist + (dist !== "—" ? " km" : "");
}

function showError(msg) {
  const el = document.getElementById("error");
  el.innerText = msg;
  el.style.display = "block";
  setTimeout(() => el.style.display = "none", 3000);
}