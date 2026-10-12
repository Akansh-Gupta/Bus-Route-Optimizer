# Delhi Bus Route Optimizer

Finds the shortest bus route between two Delhi stops, draws it on an interactive map along real roads, optimizes multi-stop trips, and analyzes the transit network, all built on real Delhi GTFS data (10,559 stops).

<!-- Add screenshots or a short GIF here, e.g. ![Route demo](docs/demo.gif) -->

## Features

**Passenger view**
- Shortest route between two named stops using A* search, with stop autocomplete
- Real road-following geometry on the map (OpenRouteService), with direction arrows and visible stop markers
- Multi-stop route optimization: best visiting order solved as a Traveling Salesman Problem, with total distance
- Natural-language chat: "take me from Laxmi Nagar to ITO" (rule-based parser, no paid API)

**Planner view**
- **Dead Zone Detector:** grid search over Delhi for areas with no stop within a given radius
- **Critical Stop Finder:** betweenness centrality to find stops most routes funnel through
- **Coverage Heatmap:** stop density visualization
- **Route Redundancy:** Jaccard similarity of stop sets to flag overlapping routes

## Tech Stack

| Layer | Technology |
|---|---|
| Language | Python 3.11+ |
| Graph and pathfinding | NetworkX (A*, directed graph) |
| Multi-stop optimization | Google OR-Tools |
| Data processing | Pandas |
| Backend API | FastAPI + Uvicorn |
| Road geometry | OpenRouteService (ORS) API |
| Frontend | Leaflet.js, OpenStreetMap tiles, leaflet.heat |
| Dataset | Delhi GTFS from [Open Transit Data](https://otd.delhi.gov.in) |

## How It Works

- **Graph:** bus stops are nodes; direct bus connections are directed edges weighted by Haversine distance in km.
- **A\*:** uses Haversine distance to the target as the heuristic. It never overestimates, so A* guarantees the shortest path while exploring fewer nodes than Dijkstra.
- **Directed graph with fallback:** Delhi's feed gives opposite carriageways separate stop IDs, so an undirected graph let routes illegally hop across the road and zigzag. The graph is directed, with an undirected fallback used only when no directed path exists or the directed path is 20%+ longer. The API flags this with `used_undirected_fallback`.
- **Path cleanup:** `simplify_path()` merges stops under 80 m apart and `remove_loops()` trims revisits before the path is sent to ORS.
- **Road geometry:** ORS traces real roads between consecutive stops; loops are removed per segment. If ORS fails, the app falls back to straight lines.
- **Multi-stop:** OR-Tools solves the visiting order over a Haversine distance matrix, then ORS traces each leg.

## API Endpoints

| Endpoint | Method | Purpose |
|---|---|---|
| `/shortest-path` | GET | A* shortest path between two named stops, with road geometry |
| `/search-stops` | GET | Autocomplete by partial stop name |
| `/optimize-route` | POST | Multi-stop TSP ordering with road geometry |
| `/dead-zones` | GET | Grid points with no coverage within a radius |
| `/all-stops` | GET | Bulk stop coordinates (heatmap) |
| `/critical-stops` | GET | Top-N stops by betweenness centrality |
| `/route-redundancy` | GET | Route pairs with high stop-set overlap |
| `/chat` | POST | Natural language to shortest path |

## Setup

1. **Clone and install**
   ```bash
   git clone https://github.com/Akansh-Gupta/Bus-Route-Optimizer.git
   cd Bus-Route-Optimizer
   pip install -r requirements.txt
   ```
2. **Download the GTFS data** from [otd.delhi.gov.in](https://otd.delhi.gov.in) and place `stops.txt` and `stop_times.txt` in a `data/` folder. The data is not included in the repository because of its size.
3. **Add an OpenRouteService key.** Get a free key at [openrouteservice.org](https://openrouteservice.org) and create a `.env` file in the project root:
   ```
   ORS_API_KEY=your_key_here
   ```
4. **Run the server**
   ```bash
   python -m uvicorn main:app --reload
   ```
5. Open `index.html` in your browser while the server is running (API at `http://127.0.0.1:8000`).

## Project Structure

```
bus-route-optimizer/
├── data/            GTFS files (gitignored)
├── static/          script.js, style.css
├── main.py          FastAPI server, graph, A*, endpoints
├── optimizer.py     OR-Tools TSP and dead-zone detection
├── index.html
├── requirements.txt
└── README.md
```

## Limitations and Future Work

- **No transfers or timetables:** cost is distance only; edges don't know which bus route they belong to. Upgrade: (stop, route) nodes with transfer penalties and time-dependent routing using GTFS schedules.
- **Straight-line distances:** edge weights and TSP ordering use Haversine, which underestimates road distance. Upgrade: ORS Matrix API.
- **Data quality:** the feed has no `parent_station` or `direction_id`, and some stops share one ID across both directions. Routing accuracy is bounded by the source data.
- **Static data only:** GTFS-realtime vehicle positions exist but are not integrated.
