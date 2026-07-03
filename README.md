# 🚌 Delhi Bus Route Optimizer

A shortest-path based bus route optimizer built on real Delhi GTFS data. Given any two bus stops in Delhi, it finds the most efficient route using Dijkstra's algorithm and displays it on an interactive map.

> 🚧 **Status: In Progress** — Core routing and API done. Map visualization and multi-stop optimizer coming next.

---

## 📌 Features

- ✅ Shortest path between any two Delhi bus stops
- ✅ Real distance calculation using Haversine formula
- ✅ REST API to query routes programmatically
- ✅ Stop name search endpoint
- ✅ Interactive map with route visualization (Leaflet.js)
- ⏳ Multi-stop route optimizer (OR-Tools) — coming soon
- ⏳ AI chatbot interface — coming soon

---

## 🗂️ Project Structure

```
bus-optimizer/
├── data/
│   ├── stops.txt           # Delhi bus stop locations (GTFS)
│   └── stop_times.txt      # Stop sequences per trip (GTFS)
├── main.py                 # FastAPI server + API endpoints
├── index.html              # Frontend map (Leaflet.js)
└── README.md
```

---

## 🧠 How It Works

```
GTFS Data (stops + trips)
        ↓
Build a weighted graph
  nodes  = bus stops
  edges  = direct connections between consecutive stops
  weight = real distance in km (Haversine formula)
        ↓
Dijkstra's Algorithm finds shortest path
        ↓
FastAPI serves the result as JSON
        ↓
Leaflet.js draws it on OpenStreetMap
```

---

## 🛠️ Tech Stack

| Layer | Technology |
|---|---|
| Language | Python 3.11+ |
| Graph & Pathfinding | NetworkX (Dijkstra) |
| Data Processing | Pandas |
| Backend API | FastAPI + Uvicorn |
| Frontend Map | Leaflet.js + OpenStreetMap |
| Dataset | Delhi GTFS (otd.delhi.gov.in) |

---

## 📊 Dataset

Data sourced from the **Delhi Open Transit Data portal** → [otd.delhi.gov.in](https://otd.delhi.gov.in/documentation/)

```
Stops loaded:       10,559
Route connections:  20,646
```

---

## 🚀 Getting Started

### 1. Clone the repo
```bash
git clone https://github.com/yourusername/bus-optimizer.git
cd bus-optimizer
```

### 2. Install dependencies
```bash
pip install fastapi uvicorn pandas networkx
```

### 3. Add GTFS data
Download Delhi GTFS data from [otd.delhi.gov.in](https://otd.delhi.gov.in/documentation/) and place `stops.txt` and `stop_times.txt` inside the `data/` folder.

### 4. Run the API server
```bash
uvicorn main:app --reload
```

### 5. Open the map
Open `index.html` directly in your browser.

---

## 🔌 API Endpoints

### `GET /shortest-path`
Find the shortest route between two stops.

**Parameters:**
| Param | Type | Example |
|---|---|---|
| `from_stop` | string | `Laxmi Nagar` |
| `to_stop` | string | `ITO` |

**Example:**
```
GET http://127.0.0.1:8000/shortest-path?from_stop=Laxmi Nagar&to_stop=ITO
```

**Response:**
```json
{
  "from": "Laxmi Nagar",
  "to": "ITO",
  "total_distance_km": 3.82,
  "num_stops": 5,
  "path": [
    { "stop_id": 131, "stop_name": "Laxmi Nagar", "lat": 28.63, "lon": 77.27 },
    { "stop_id": 1116, "stop_name": "Laxmi Nagar / Shakarpur Crossing", "lat": 28.63, "lon": 77.26 },
    ...
  ]
}
```

---

### `GET /search-stops`
Search for stop names (useful for autocomplete).

**Parameters:**
| Param | Type | Example |
|---|---|---|
| `query` | string | `Laxmi` |

**Example:**
```
GET http://127.0.0.1:8000/search-stops?query=Laxmi
```

**Response:**
```json
{
  "results": [
    { "stop_id": 131, "stop_name": "Laxmi Nagar" },
    { "stop_id": 277, "stop_name": "Laxmi Vihar" },
    ...
  ]
}
```

---

## 📍 Interactive API Docs
FastAPI auto-generates a testing UI at:
```
http://127.0.0.1:8000/docs
```

---

## 🗺️ Roadmap

- [x] Load real Delhi GTFS data
- [x] Build weighted graph with Haversine distances
- [x] Dijkstra shortest path between two stops
- [x] FastAPI backend with JSON responses
- [x] Leaflet.js map with route visualization
- [ ] Multi-stop optimizer using Google OR-Tools
- [ ] AI chatbot interface (natural language input)
- [ ] Deployment on Render + Vercel

---

## 👤 Author

Akansh Gupta
[GitHub](https://github.com/Akansh-Gupta) · [LinkedIn](www.linkedin.com/in/akanshgupta-)

---

## 📄 License

This project is for educational purposes. GTFS data © Delhi Integrated Multi-Modal Transit System (DIMTS).
