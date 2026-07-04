// ── MAP SETUP ────────────────────────────────────────────────
const map = L.map("map").setView([28.6139, 77.2090], 11);
L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
  attribution: "© OpenStreetMap contributors"
}).addTo(map);

let currentLayers = [];
let multiStops    = [];

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
  const navbar  = document.getElementById("navbar").offsetHeight;
  const panel   = document.querySelector(".panel:not([style*='display:none'])").offsetHeight;
  document.getElementById("map").style.height = `calc(100vh - ${navbar + panel}px)`;
}

// ── AUTOCOMPLETE ──────────────────────────────────────────────
const debounceTimers = {};

async function showSuggestions(inputId) {
  const inputEl = document.getElementById(
    inputId === "multi" ? "multi-input" : inputId
  );
  const query         = inputEl.value.trim();
  const suggestionsBox = document.getElementById(inputId + "-suggestions");

  if (query.length < 2) {
    suggestionsBox.style.display = "none";
    return;
  }

  clearTimeout(debounceTimers[inputId]);
  debounceTimers[inputId] = setTimeout(async () => {
    const res  = await fetch(`http://127.0.0.1:8000/search-stops?query=${encodeURIComponent(query)}`);
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
  const to   = document.getElementById("to").value.trim();

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
  drawRoute(data.path, "royalblue");
  showInfo("Route Found", data.from, data.to, data.num_stops, data.total_distance_km);
}

// ── MULTI STOP ────────────────────────────────────────────────
function addMultiStop() {
  const input = document.getElementById("multi-input");
  const name  = input.value.trim();
  const lat   = parseFloat(input.dataset.lat);
  const lon   = parseFloat(input.dataset.lon);

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
  drawRoute(data.optimized_stops, "orange");
  showInfo("Optimized Route", data.optimized_stops[0].stop_name,
    data.optimized_stops[data.optimized_stops.length - 1].stop_name,
    data.optimized_stops.length, "—");
}

function clearMulti() {
  multiStops = [];
  renderStopTags();
  clearMap();
}

// ── PLANNER FEATURES (placeholders for now) ───────────────────
function findDeadZones()       { showError("Coming soon — Dead Zone Detector"); }
function findCriticalStops()   { showError("Coming soon — Critical Stop Finder"); }
function showHeatmap()         { showError("Coming soon — Coverage Heatmap"); }
function findRedundantRoutes() { showError("Coming soon — Route Redundancy"); }

// ── MAP HELPERS ───────────────────────────────────────────────
function drawRoute(stops, color) {
  clearMap();
  const latlngs = [];

  stops.forEach((stop, i) => {
    const isFirst = i === 0;
    const isLast  = i === stops.length - 1;
    const c       = isFirst ? "green" : isLast ? "red" : color;
    const r       = (isFirst || isLast) ? 10 : 6;

    const marker = L.circleMarker([stop.lat, stop.lon], {
      radius: r, color: c, fillColor: c, fillOpacity: 0.9, weight: 2
    }).addTo(map).bindPopup(`<b>${stop.stop_name}</b><br>Stop ${i + 1} of ${stops.length}`);

    currentLayers.push(marker);
    latlngs.push([stop.lat, stop.lon]);
  });

  const line = L.polyline(latlngs, { color, weight: 5, opacity: 0.8 }).addTo(map);
  currentLayers.push(line);
  map.fitBounds(line.getBounds(), { padding: [40, 40] });
}

function clearMap() {
  currentLayers.forEach(l => map.removeLayer(l));
  currentLayers = [];
  document.getElementById("info").style.display = "none";
}

// ── UI HELPERS ────────────────────────────────────────────────
function showInfo(title, from, to, stops, dist) {
  document.getElementById("info").style.display = "block";
  document.getElementById("info-title").innerText  = title;
  document.getElementById("info-from").innerText   = "From: "     + from;
  document.getElementById("info-to").innerText     = "To: "       + to;
  document.getElementById("info-stops").innerText  = "Stops: "    + stops;
  document.getElementById("info-dist").innerText   = "Distance: " + dist + (dist !== "—" ? " km" : "");
}

function showError(msg) {
  const el = document.getElementById("error");
  el.innerText       = msg;
  el.style.display   = "block";
  setTimeout(() => el.style.display = "none", 3000);
}