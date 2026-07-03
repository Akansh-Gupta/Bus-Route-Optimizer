// initialize map centered on Delhi
const map = L.map("map").setView([28.6139, 77.2090], 12);

// OpenStreetMap tiles — free, no API key needed
L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    attribution: "© OpenStreetMap contributors"
}).addTo(map);

let currentLayers = [];

function showError(msg) {
    const el = document.getElementById("error");
    el.innerText = msg;
    el.style.display = "block";
    setTimeout(() => el.style.display = "none", 3000);
}

async function findRoute() {
    const from = document.getElementById("from").value.trim();
    const to = document.getElementById("to").value.trim();

    if (!from || !to) { showError("Please enter both stops"); return; }

    // call your FastAPI backend
    const res = await fetch(
        `http://127.0.0.1:8000/shortest-path?from_stop=${encodeURIComponent(from)}&to_stop=${encodeURIComponent(to)}`
    );

    if (!res.ok) {
        const err = await res.json();
        showError(err.detail);
        return;
    }

    const data = await res.json();

    // clear previous route from map
    currentLayers.forEach(l => map.removeLayer(l));
    currentLayers = [];

    const latlngs = [];

    data.path.forEach((stop, i) => {
        const isFirst = i === 0;
        const isLast = i === data.path.length - 1;

        // green for start, red for end, blue for middle stops
        const color = isFirst ? "green" : isLast ? "red" : "royalblue";
        const radius = (isFirst || isLast) ? 10 : 6;

        const marker = L.circleMarker([stop.lat, stop.lon], {
            radius,
            color,
            fillColor: color,
            fillOpacity: 0.9,
            weight: 2
        })
            .addTo(map)
            .bindPopup(`<b>${stop.stop_name}</b><br>Stop ${i + 1} of ${data.path.length}`);

        currentLayers.push(marker);
        latlngs.push([stop.lat, stop.lon]);
    });

    // draw the route as a blue line
    const line = L.polyline(latlngs, {
        color: "royalblue",
        weight: 5,
        opacity: 0.8
    }).addTo(map);

    currentLayers.push(line);

    // auto zoom map to fit the full route
    map.fitBounds(line.getBounds(), { padding: [40, 40] });

    // show info box
    document.getElementById("info").style.display = "block";
    document.getElementById("info-from").innerText = "From: " + data.from;
    document.getElementById("info-to").innerText = "To: " + data.to;
    document.getElementById("info-stops").innerText = "Stops: " + data.num_stops;
    document.getElementById("info-dist").innerText = "Distance: " + data.total_distance_km + " km";
}