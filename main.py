# to run the server:- python -m uvicorn main:app --reload

import networkx as nx
import pandas as pd
import os
import requests
import re

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from math import radians, sin, cos, sqrt, atan2
from optimizer import optimize_route, find_dead_zones
from pydantic import BaseModel

load_dotenv()
ORS_API_KEY = os.environ.get("ORS_API_KEY")

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

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
        return [[lat, lon] for lon, lat in coords]
    except Exception as e:
        print(f"ORS error for ({lat1},{lon1}) -> ({lat2},{lon2}): {e}")
        return None


def astar_heuristic(u, v):
    return haversine(coord[u]["stop_lat"], coord[u]["stop_lon"], coord[v]["stop_lat"], coord[v]["stop_lon"])


def simplify_path(path, coord, min_gap_km=0.08):
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

def extract_stops_rule_based(message):
    """
    Zero-cost intent parser: no external API, no cost, works offline.
    Handles phrasings like "take me from X to Y", "route from X to Y", "X to Y".
    """
    msg = message.strip()

    patterns = [
        r"from\s+(.+?)\s+to\s+(.+)",   # "... from X to Y ..."
        r"^(.+?)\s+to\s+(.+)$",        # fallback: "X to Y"
    ]

    for pattern in patterns:
        match = re.search(pattern, msg, re.IGNORECASE)
        if match:
            from_raw = match.group(1).strip(" ?.!")
            to_raw = match.group(2).strip(" ?.!")
            from_raw = re.sub(
                r"^(take me|i want to go|how do i get|please|route me)\s*",
                "", from_raw, flags=re.IGNORECASE
            ).strip()
            return from_raw, to_raw

    return None, None


def match_stop_name(raw_text, stops_df):
    """
    Fuzzy-matches free text against real GTFS stop names — same substring
    approach as /search-stops — and returns the closest match.
    """
    if not raw_text:
        return None
    matches = stops_df[stops_df["stop_name"].str.contains(raw_text.strip(), case=False, na=False)]
    if matches.empty:
        return None
    # prefer the shortest matching name — usually the closest/cleanest match
    return matches.sort_values("stop_name", key=lambda col: col.str.len()).iloc[0]["stop_name"]

coord = stops.set_index("stop_id")[["stop_lat", "stop_lon"]].to_dict("index")
name_to_id = {
    name.lower(): sid for name, sid in zip(stops["stop_name"], stops["stop_id"])
}
id_to_name = dict(zip(stops["stop_id"], stops["stop_name"]))

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
                coord[a]["stop_lat"], coord[a]["stop_lon"],
                coord[b]["stop_lat"], coord[b]["stop_lon"],
            )
            G.add_edge(a, b, weight=dist)

UG = G.to_undirected()

print("Graph ready →", G.number_of_nodes(), "stops,", G.number_of_edges(), "connections")


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


def find_critical_stops(graph, top_n=15, sample_size=500):
    """
    Approximates 'critical' stops using betweenness centrality: how often a
    stop sits on the shortest path between other stop pairs. High-centrality
    stops are the ones many routes funnel through — removing them would
    force many trips onto much longer detours.
    Exact betweenness centrality is O(V*E), too slow for 10k+ nodes, so this
    approximates using a random sample of source nodes (k=sample_size).
    """
    k = min(sample_size, graph.number_of_nodes())
    centrality = nx.betweenness_centrality(graph, k=k, weight="weight", seed=42)
    ranked = sorted(centrality.items(), key=lambda x: x[1], reverse=True)[:top_n]
    return [
        {
            "stop_id": sid,
            "stop_name": id_to_name.get(sid, "Unknown"),
            "lat": coord[sid]["stop_lat"],
            "lon": coord[sid]["stop_lon"],
            "centrality_score": round(score, 5),
        }
        for sid, score in ranked
    ]


def find_redundant_routes(stop_times_df, threshold=0.7, max_pairs=20, sample_trips=300):
    """
    Groups stop_times by trip_id, treats each trip as a set of stop_ids, and
    flags trip pairs whose stop sets overlap heavily (Jaccard similarity
    above `threshold`) — candidate redundant services covering the same ground.
    Capped to `sample_trips` trips for performance on large datasets.
    """
    trip_stop_sets = {
        trip_id: set(group["stop_id"])
        for trip_id, group in stop_times_df.groupby("trip_id")
    }
    trip_ids = list(trip_stop_sets.keys())[:sample_trips]

    redundant = []
    for i in range(len(trip_ids)):
        for j in range(i + 1, len(trip_ids)):
            a, b = trip_stop_sets[trip_ids[i]], trip_stop_sets[trip_ids[j]]
            if not a or not b:
                continue
            intersection = len(a & b)
            union = len(a | b)
            similarity = intersection / union if union else 0
            if similarity >= threshold:
                redundant.append({
                    "trip_a": trip_ids[i],
                    "trip_b": trip_ids[j],
                    "overlap": round(similarity, 2),
                    "shared_stops": intersection,
                })

    redundant.sort(key=lambda x: x["overlap"], reverse=True)
    return redundant[:max_pairs]


@app.get("/shortest-path")
def shortest_path(from_stop: str, to_stop: str):
    from_ids = stops[stops["stop_name"].str.lower() == from_stop.lower()]["stop_id"].tolist()
    to_ids = stops[stops["stop_name"].str.lower() == to_stop.lower()]["stop_id"].tolist()

    if not from_ids:
        raise HTTPException(status_code=404, detail=f"Stop '{from_stop}' not found")
    if not to_ids:
        raise HTTPException(status_code=404, detail=f"Stop '{to_stop}' not found")

    best_path, best_length = find_best_path(G, from_ids, to_ids)

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
    matches = stops[
        stops["stop_name"].str.contains(query.strip(), case=False, na=False)
    ][["stop_id", "stop_name", "stop_lat", "stop_lon"]]
    matches = matches.drop_duplicates(subset="stop_name")
    matches = matches.head(10)
    return {"results": matches.to_dict(orient="records")}


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

    # trace real road geometry between each consecutive pair in the optimized order,
    # same approach as /shortest-path, and sum up the actual distance travelled
    road_geometry = []
    total_distance_km = 0
    for i in range(len(result) - 1):
        a, b = result[i], result[i + 1]
        total_distance_km += haversine(a["lat"], a["lon"], b["lat"], b["lon"])
        segment = get_road_geometry(a["lat"], a["lon"], b["lat"], b["lon"])
        if segment:
            road_geometry.extend(segment)
        else:
            road_geometry.append([a["lat"], a["lon"]])
            road_geometry.append([b["lat"], b["lon"]])

    return {
        "optimized_stops": result,
        "road_geometry": road_geometry,
        "total_distance_km": round(total_distance_km, 2),
    }

@app.get("/dead-zones")
def get_dead_zones(grid_size_km: float = 0.5, radius_km: float = 1.0):
    dead_zones = find_dead_zones(stops, grid_size_km, radius_km)
    return {
        "count": len(dead_zones),
        "grid_size_km": grid_size_km,
        "radius_km": radius_km,
        "dead_zones": dead_zones
    }


@app.get("/all-stops")
def all_stops():
    # lightweight endpoint for heatmap / bulk visualization — coordinates only
    df = stops[["stop_lat", "stop_lon"]].rename(columns={"stop_lat": "lat", "stop_lon": "lon"})
    return {"stops": df.to_dict(orient="records")}


@app.get("/critical-stops")
def critical_stops(top_n: int = 15):
    result = find_critical_stops(G, top_n=top_n)
    return {"count": len(result), "critical_stops": result}


@app.get("/route-redundancy")
def route_redundancy(threshold: float = 0.7):
    result = find_redundant_routes(stop_times, threshold=threshold)
    return {"count": len(result), "threshold": threshold, "redundant_pairs": result}


class ChatInput(BaseModel):
    message: str


@app.post("/chat")
def chat(input: ChatInput):
    """
    Free, zero-dependency natural-language interface: extracts FROM/TO stop
    names from plain English using regex + fuzzy matching against the real
    GTFS stop list, then reuses the existing /shortest-path logic.
    """
    from_raw, to_raw = extract_stops_rule_based(input.message)

    if not from_raw or not to_raw:
        raise HTTPException(
            status_code=400,
            detail="Couldn't understand that. Try: 'Route from Laxmi Nagar to ITO'",
        )

    from_stop = match_stop_name(from_raw, stops)
    to_stop = match_stop_name(to_raw, stops)

    if not from_stop or not to_stop:
        raise HTTPException(
            status_code=404,
            detail=f"Couldn't find matching stops for '{from_raw}' and/or '{to_raw}'",
        )

    return shortest_path(from_stop, to_stop)