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
    Handles "from X to Y", "to Y from X" (including filler like
    "I want to go to Y from X"), and the plain fallback "X to Y".
    """
    msg = message.strip().rstrip(" ?.!")
    filler = r"^(take me|i want to go|i want to|how do i get|please|route me)\s*"

    lower = msg.lower()
    from_idx = lower.rfind(" from ")

    if from_idx != -1:
        # everything after the LAST "from" is the origin
        from_raw = msg[from_idx + len(" from "):].strip()
        before = msg[:from_idx]

        # within the part before "from", the destination is whatever
        # follows the LAST "to" — this skips filler like "want to go to X"
        before_lower = before.lower()
        to_idx = before_lower.rfind(" to ")
        to_raw = before[to_idx + len(" to "):].strip() if to_idx != -1 else before.strip()

        from_raw = re.sub(filler, "", from_raw, flags=re.IGNORECASE).strip()
        to_raw = re.sub(filler, "", to_raw, flags=re.IGNORECASE).strip()
        if from_raw and to_raw:
            return from_raw, to_raw

    # no "from" in the message — fall back to plain "X to Y"
    match = re.search(r"^(.+?)\s+to\s+(.+)$", msg, re.IGNORECASE)
    if match:
        from_raw = re.sub(filler, "", match.group(1).strip(), flags=re.IGNORECASE).strip()
        to_raw = match.group(2).strip()
        if from_raw and to_raw:
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


def find_redundant_routes(stop_times_df, stops_df, threshold=0.7, max_pairs=20, sample_trips=300):
    """
    Groups stop_times by ROUTE (the part of trip_id before the first "_" —
    e.g. trip "10001_08_10" belongs to route "10001"), takes one
    representative trip per route, and flags ROUTE pairs whose stop sets
    overlap heavily (Jaccard similarity above `threshold`).

    Trips belonging to the SAME route at different times of day (e.g.
    "10001_08_10" vs "10001_08_30") are intentionally NOT compared against
    each other — that's just normal schedule frequency (a bus running the
    same route every 20 minutes), not redundant service. Only genuinely
    different routes that happen to cover almost the same stops are
    surfaced here, since that's the actionable "these two routes could
    probably be merged/trimmed" signal a planner cares about.

    Capped to `sample_trips` routes for performance on large datasets.
    """
    id_to_name = dict(zip(stops_df["stop_id"], stops_df["stop_name"]))

    # one representative trip (in stop order) per route
    route_stop_seq = {}
    for trip_id, group in stop_times_df.groupby("trip_id"):
        route_id = str(trip_id).split("_")[0]
        if route_id in route_stop_seq:
            continue  # already have a representative trip for this route
        ordered = (
            group.sort_values("stop_sequence")
            if "stop_sequence" in group.columns
            else group
        )
        route_stop_seq[route_id] = ordered["stop_id"].tolist()

    route_ids = list(route_stop_seq.keys())[:sample_trips]

    redundant = []
    for i in range(len(route_ids)):
        for j in range(i + 1, len(route_ids)):
            r1, r2 = route_ids[i], route_ids[j]
            seq_a, seq_b = route_stop_seq[r1], route_stop_seq[r2]
            a, b = set(seq_a), set(seq_b)
            if not a or not b:
                continue
            intersection = len(a & b)
            union = len(a | b)
            similarity = intersection / union if union else 0
            if similarity >= threshold:
                redundant.append({
                    "route_a": r1,
                    "route_b": r2,
                    "route_a_from": id_to_name.get(seq_a[0], "Unknown"),
                    "route_a_to": id_to_name.get(seq_a[-1], "Unknown"),
                    "route_b_from": id_to_name.get(seq_b[0], "Unknown"),
                    "route_b_to": id_to_name.get(seq_b[-1], "Unknown"),
                    "overlap": round(similarity, 2),
                    "shared_stops": intersection,
                })

    redundant.sort(key=lambda x: x["overlap"], reverse=True)
    return redundant[:max_pairs]

def remove_loops(path, coord, proximity_km=0.05):
    """
    Collapses any point in the path that revisits a location very close to
    an earlier point in the same path — not just an exact stop_id repeat.
    Delhi's GTFS gives opposite carriageways of the same road separate
    stop_ids only a few meters apart, so a pure ID-equality check misses
    those loops; this checks real distance instead.
    """
    cleaned = []
    visited_coords = []  # (lat, lon) parallel to `cleaned`
    for stop_id in path:
        lat, lon = coord[stop_id]["stop_lat"], coord[stop_id]["stop_lon"]
        loop_start = None
        for idx, (vlat, vlon) in enumerate(visited_coords):
            if haversine(lat, lon, vlat, vlon) <= proximity_km:
                loop_start = idx
                break
        if loop_start is not None:
            cleaned = cleaned[:loop_start + 1]
            visited_coords = visited_coords[:loop_start + 1]
        else:
            cleaned.append(stop_id)
            visited_coords.append((lat, lon))
    return cleaned

def remove_geometry_loops(geometry, proximity_km=0.03, min_gap_points=6):
    """
    Same idea as remove_loops(), applied to the dense ORS road polyline
    instead of the stop list. Needed because a loop can appear WITHIN the
    road path between two stops that are themselves far enough apart to
    pass the stop-level check.
    min_gap_points skips comparing against the last few points, so a
    normal smooth curve (where nearby points are naturally close) doesn't
    get falsely flagged as a loop.
    """
    cleaned = []
    for point in geometry:
        loop_start = None
        search_limit = max(0, len(cleaned) - min_gap_points)
        for idx in range(search_limit):
            if haversine(point[0], point[1], cleaned[idx][0], cleaned[idx][1]) <= proximity_km:
                loop_start = idx
                break
        if loop_start is not None:
            cleaned = cleaned[:loop_start + 1]
        else:
            cleaned.append(point)
    return cleaned

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

    best_path = remove_loops(best_path, coord)
    best_path = simplify_path(best_path, coord)

    road_geometry = []
    for i in range(len(best_path) - 1):
        a, b = best_path[i], best_path[i + 1]
        segment = get_road_geometry(
            coord[a]["stop_lat"], coord[a]["stop_lon"],
            coord[b]["stop_lat"], coord[b]["stop_lon"],
        )
        if not segment:
            segment = [
                [coord[a]["stop_lat"], coord[a]["stop_lon"]],
                [coord[b]["stop_lat"], coord[b]["stop_lon"]],
            ]
        road_geometry.extend(remove_geometry_loops(segment))

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
        if not segment:
            segment = [[a["lat"], a["lon"]], [b["lat"], b["lon"]]]
        road_geometry.extend(remove_geometry_loops(segment))

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
    result = find_redundant_routes(stop_times, stops, threshold=threshold)
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