const API_BASE = "http://127.0.0.1:8000";

// ── MAP SETUP ────────────────────────────────────────────────
const map = L.map("map").setView([28.6139, 77.2090], 11);
L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
  attribution: "© OpenStreetMap contributors"
}).addTo(map);

let currentLayers = [];
let multiStops = [];

// ── SIDEBAR COLLAPSE ─────────────────────────────────────────
function toggleSidebar() {
  document.body.classList.toggle("collapsed");
  // give the CSS transition a moment, then let Leaflet recalc its size
  setTimeout(() => map.invalidateSize(), 260);
}

// ── TAB SWITCHING ─────────────────────────────────────────────
function switchTab(tab) {
  document.querySelectorAll(".tab").forEach(t => t.classList.remove("active"));
  document.querySelectorAll(".panel").forEach(p => p.style.display = "none");

  const order = ["passenger", "planner", "chat"];
  document.getElementById(tab + "-panel").style.display = "flex";
  document.querySelectorAll(".tab")[order.indexOf(tab)].classList.add("active");
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
    const res = await fetch(`${API_BASE}/search-stops?query=${encodeURIComponent(query)}`);
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
function extractErrorMessage(err) {
  const detail = err && err.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail.map(d => (d && d.msg) ? d.msg : JSON.stringify(d)).join("; ");
  }
  if (detail && typeof detail === "object") return detail.msg || JSON.stringify(detail);
  return "Something went wrong talking to the server.";
}

async function findRoute() {
  const from = document.getElementById("from").value.trim();
  const to = document.getElementById("to").value.trim();

  if (!from || !to) { showError("Please enter both stops"); return; }

  try {
    const res = await fetch(
      `${API_BASE}/shortest-path?from_stop=${encodeURIComponent(from)}&to_stop=${encodeURIComponent(to)}`
    );

    if (!res.ok) {
      const err = await res.json();
      showError(extractErrorMessage(err));
      return;
    }

    const data = await res.json();
    drawRoute(data.path, "royalblue", data.road_geometry);
    showInfo("Route Found", data.from, data.to, data.num_stops, data.total_distance_km);
  } catch (e) {
    showError("Couldn't reach the server. Is the backend running?");
  }
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

  const res = await fetch(`${API_BASE}/optimize-route`, {
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

// ── CHAT (natural-language route finder) ────────────────────
function appendChatMsg(text, cls) {
  const log = document.getElementById("chat-log");
  const div = document.createElement("div");
  div.className = "chat-msg " + cls;
  div.innerText = text;
  log.appendChild(div);
  log.scrollTop = log.scrollHeight;
}

async function sendChat() {
  const input = document.getElementById("chat-input");
  const message = input.value.trim();
  if (!message) return;

  appendChatMsg(message, "user");
  input.value = "";

  try {
    const res = await fetch(`${API_BASE}/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message })
    });

    const data = await res.json();

    if (!res.ok) {
      appendChatMsg(data.detail || "Couldn't understand that.", "bot error");
      return;
    }

    drawRoute(data.path, "royalblue", data.road_geometry);
    showInfo("Route Found", data.from, data.to, data.num_stops, data.total_distance_km);
    appendChatMsg(
      `Found a route from ${data.from} to ${data.to} — ${data.num_stops} stops, ${data.total_distance_km} km.`,
      "bot"
    );
  } catch (e) {
    appendChatMsg("Something went wrong reaching the server.", "bot error");
  }
}

/// ── PLANNER FEATURES ─────────────────────────────────────────
async function findDeadZones() {
  clearMap();
  const res = await fetch(`${API_BASE}/dead-zones?grid_size_km=0.5&radius_km=1.0`);
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
  const res = await fetch(`${API_BASE}/critical-stops?top_n=15`);
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

  const res = await fetch(`${API_BASE}/all-stops`);
  const data = await res.json();

  const points = data.stops.map(s => [s.lat, s.lon, 0.5]);
  heatLayer = L.heatLayer(points, { radius: 18, blur: 15, maxZoom: 15 }).addTo(map);
  currentLayers.push(heatLayer);

  showResultsList("Coverage Heatmap", [`${data.stops.length} stops plotted by density`]);
  map.setView([28.6139, 77.2090], 11);
}

async function findRedundantRoutes() {
  clearMap();
  const res = await fetch(`${API_BASE}/route-redundancy?threshold=0.7`);
  const data = await res.json();

  if (!data.redundant_pairs.length) {
    showResultsList("Route Redundancy", ["No two different routes overlap above the 70% threshold."]);
    return;
  }

  showResultsList(
    `Redundant Routes (${data.count})`,
    [
      "Different routes that cover almost the same stops — candidates to merge or trim. " +
      "(Runs of the same route at different times of day are excluded — those aren't redundancy.)",
      ...data.redundant_pairs.map(p =>
        `Route ${p.route_a} (${p.route_a_from} → ${p.route_a_to}) overlaps ` +
        `Route ${p.route_b} (${p.route_b_from} → ${p.route_b_to}) — ` +
        `${Math.round(p.overlap * 100)}% shared (${p.shared_stops} stops in common)`
      )
    ]
  );
}

function showResultsList(title, lines) {
  const panel = document.getElementById("results-panel");
  const body = document.getElementById("results-body");
  body.innerHTML = `<h3>${title}</h3>` + lines.map(l => `<p>${l}</p>`).join("");
  panel.style.display = "block";
}

function hideResults() {
  document.getElementById("results-panel").style.display = "none";
}

function hideInfo() {
  document.getElementById("info").style.display = "none";
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

  const arrows = L.polylineDecorator(line, {
    patterns: [
      {
        offset: 25,
        repeat: 80,
        symbol: L.Symbol.arrowHead({
          pixelSize: 10,
          polygon: false,
          pathOptions: { stroke: true, color, weight: 3, opacity: 0.9 }
        })
      }
    ]
  }).addTo(map);
  currentLayers.push(arrows);

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
  hideInfo();
  hideResults();
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
