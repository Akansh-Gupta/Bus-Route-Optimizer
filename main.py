# to run the server:- python -m uvicorn main:app --reload

import networkx as nx
import pandas as pd
import os
import requests

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from math import radians, sin, cos, sqrt, atan2
from optimizer import optimize_route, find_dead_zones
from pydantic import BaseModel

load_dotenv()
ORS_API_KEY = os.environ.get("ORS_API_KEY")

app = FastAPI()

# allows map to talk to this API without browser errors
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# load data once when server starts
stops = pd.read_csv("data/stops.txt")
stop_times = pd.read_csv("data/stop_times.txt")


def haversine(lat1, lon1, lat2, lon2):
    R = 6371
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = (
        sin(dlat / 2) ** 2
        + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    )
    return R * 2 * atan2(sqrt(a), sqrt(1 - a))


def get_road_geometry(lat1, lon1, lat2, lon2):
    url = "https://api.openrouteservice.org/v2/directions/driving-car"
    params = {
        "api_key": ORS_API_KEY,
        "start": f"{lon1},{lat1}",
        "end": f"{lon2},{lat2}",
    }
    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        coords = data["features"][0]["geometry"]["coordinates"]
        # ORS returns [lon, lat] pairs — convert to [lat, lon] for Leaflet
        return [[lat, lon] for lon, lat in coords]
    except Exception as e:
        print(f"ORS error for ({lat1},{lon1}) -> ({lat2},{lon2}): {e}")
        return None


def astar_heuristic(u, v):
    return haversine(coord[u]["stop_lat"], coord[u]["stop_lon"], coord[v]["stop_lat"], coord[v]["stop_lon"])


def simplify_path(path, coord, min_gap_km=0.08):
    # collapses consecutive stops that are near-duplicates (e.g. opposite-carriageway
    # stop pairs a few meters apart) so ORS doesn't trace a doubled "there and back"
    # line for a hop that isn't a real bus movement.
    if len(path) <= 2:
        return path
    simplified = [path[0]]
    for sid in path[1:-1]:
        last = simplified[-1]
        d = haversine(
            coord[last]["stop_lat"], coord[last]["stop_lon"],
            coord[sid]["stop_lat"], coord[sid]["stop_lon"],
        )
        if d >= min_gap_km:
            simplified.append(sid)
    simplified.append(path[-1])
    return simplified


coord = stops.set_index("stop_id")[["stop_lat", "stop_lon"]].to_dict("index")
name_to_id = {
    name.lower(): sid for name, sid in zip(stops["stop_name"], stops["stop_id"])
}
id_to_name = dict(zip(stops["stop_id"], stops["stop_name"]))

# directed graph: edge a->b means a real trip travels FROM a TO b.
# keeps the pathfinder from treating a road as two-way just because SOME trip
# runs the opposite direction between two nearby stops (e.g. opposite
# carriageways of a divided road) — that was causing zigzagging routes.
G = nx.DiGraph()
for _, row in stops.iterrows():
    G.add_node(
        row["stop_id"], name=row["stop_name"], lat=row["stop_lat"], lon=row["stop_lon"]
    )

for trip_id, group in stop_times.groupby("trip_id"):
    group = group.sort_values("stop_sequence")
    stop_list = group["stop_id"].tolist()
    for i in range(len(stop_list) - 1):
        a, b = stop_list[i], stop_list[i + 1]
        if a in coord and b in coord:
            dist = haversine(
                coord[a]["stop_lat"],
                coord[a]["stop_lon"],
                coord[b]["stop_lat"],
                coord[b]["stop_lon"],
            )
            G.add_edge(a, b, weight=dist)

# fallback graph, used ONLY when the directed data has a genuine gap
# (e.g. the return-direction trip just isn't in this GTFS feed) and the
# directed search can't find a reasonably direct path.
UG = G.to_undirected()

print(
    "Graph ready →", G.number_of_nodes(), "stops,", G.number_of_edges(), "connections"
)


def find_best_path(graph, from_ids, to_ids):
    best_path = None
    best_length = float("inf")
    for src in from_ids:
        for tgt in to_ids:
            if not nx.has_path(graph, src, tgt):
                continue
            try:
                path = nx.astar_path(graph, src, tgt, heuristic=astar_heuristic, weight="weight")
                length = nx.astar_path_length(graph, src, tgt, heuristic=astar_heuristic, weight="weight")
            except nx.NetworkXNoPath:
                continue
            if length < best_length:
                best_length = length
                best_path = path
    return best_path, best_length


# endpoint
@app.get("/shortest-path")
def shortest_path(from_stop: str, to_stop: str):
    # get ALL stop IDs matching this name
    from_ids = stops[stops["stop_name"].str.lower() == from_stop.lower()][
        "stop_id"
    ].tolist()

    to_ids = stops[stops["stop_name"].str.lower() == to_stop.lower()][
        "stop_id"
    ].tolist()

    if not from_ids:
        raise HTTPException(status_code=404, detail=f"Stop '{from_stop}' not found")
    if not to_ids:
        raise HTTPException(status_code=404, detail=f"Stop '{to_stop}' not found")

    # 1. try the directed graph first — respects real travel direction
    best_path, best_length = find_best_path(G, from_ids, to_ids)

    # 2. fall back to the undirected graph if the directed graph found nothing
    #    at all, or only found a much longer detour — a sign that the
    #    directional trip data has a gap for this specific pair (e.g. the
    #    reverse-direction trip wasn't included in the GTFS feed)
    used_fallback = False
    ug_path, ug_length = find_best_path(UG, from_ids, to_ids)
    if best_path is None or (ug_path is not None and ug_length < best_length * 0.8):
        best_path, best_length = ug_path, ug_length
        used_fallback = True

    if not best_path:
        raise HTTPException(status_code=404, detail="No path found between these stops")

    best_path = simplify_path(best_path, coord)

    road_geometry = []
    for i in range(len(best_path) - 1):
        a, b = best_path[i], best_path[i + 1]
        segment = get_road_geometry(
            coord[a]["stop_lat"], coord[a]["stop_lon"],
            coord[b]["stop_lat"], coord[b]["stop_lon"],
        )
        if segment:
            road_geometry.extend(segment)
        else:
            # fallback: straight line if ORS fails for this segment
            road_geometry.append([coord[a]["stop_lat"], coord[a]["stop_lon"]])
            road_geometry.append([coord[b]["stop_lat"], coord[b]["stop_lon"]])

    path_details = [
        {
            "stop_id": sid,
            "stop_name": id_to_name[sid],
            "lat": coord[sid]["stop_lat"],
            "lon": coord[sid]["stop_lon"],
        }
        for sid in best_path
    ]

    return {
        "from": from_stop,
        "to": to_stop,
        "total_distance_km": round(best_length, 2),
        "num_stops": len(best_path),
        "path": path_details,
        "road_geometry": road_geometry,
        "used_undirected_fallback": used_fallback,
    }


@app.get("/search-stops")
def search_stops(query: str):
    # case insensitive partial match
    matches = stops[
        stops["stop_name"].str.contains(query.strip(), case=False, na=False)
    ][["stop_id", "stop_name", "stop_lat", "stop_lon"]]

    # remove duplicate stop names — same name appears for each direction of travel
    matches = matches.drop_duplicates(subset="stop_name")

    matches = matches.head(10)

    return {"results": matches.to_dict(orient="records")}


# defines what the request body looks like
class StopInput(BaseModel):
    stop_name: str
    lat: float
    lon: float


@app.post("/optimize-route")
def optimize(stops: list[StopInput]):
    if len(stops) < 2:
        raise HTTPException(status_code=400, detail="Need at least 2 stops")

    stops_list = [{"stop_name": s.stop_name, "lat": s.lat, "lon": s.lon} for s in stops]

    result = optimize_route(stops_list)

    if not result:
        raise HTTPException(status_code=500, detail="Could not find optimal route")

    return {"optimized_stops": result}


@app.get("/dead-zones")
def get_dead_zones(grid_size_km: float = 0.5, radius_km: float = 1.0):
    dead_zones = find_dead_zones(stops, grid_size_km, radius_km)
    return {
        "count": len(dead_zones),
        "grid_size_km": grid_size_km,
        "radius_km": radius_km,
        "dead_zones": dead_zones
    }