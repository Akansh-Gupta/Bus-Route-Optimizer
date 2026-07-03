# to run the server:- python -m uvicorn main:app --reload

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import networkx as nx
import pandas as pd
from math import radians, sin, cos, sqrt, atan2

app = FastAPI()

# allows your map (Step 7) to talk to this API without browser errors
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── load data once when server starts ───────────────────────────
stops = pd.read_csv("data/stops.txt")
stop_times = pd.read_csv("data/stop_times.txt")

def haversine(lat1, lon1, lat2, lon2):
    R = 6371
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat/2)**2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon/2)**2
    return R * 2 * atan2(sqrt(a), sqrt(1 - a))

coord = stops.set_index("stop_id")[["stop_lat", "stop_lon"]].to_dict("index")
name_to_id = dict(zip(stops["stop_name"], stops["stop_id"]))
id_to_name = dict(zip(stops["stop_id"], stops["stop_name"]))

G = nx.Graph()
for _, row in stops.iterrows():
    G.add_node(row["stop_id"], name=row["stop_name"], lat=row["stop_lat"], lon=row["stop_lon"])

for trip_id, group in stop_times.groupby("trip_id"):
    group = group.sort_values("stop_sequence")
    stop_list = group["stop_id"].tolist()
    for i in range(len(stop_list) - 1):
        a, b = stop_list[i], stop_list[i + 1]
        if a in coord and b in coord:
            dist = haversine(
                coord[a]["stop_lat"], coord[a]["stop_lon"],
                coord[b]["stop_lat"], coord[b]["stop_lon"]
            )
            G.add_edge(a, b, weight=dist)

print("Graph ready →", G.number_of_nodes(), "stops,", G.number_of_edges(), "connections")

# ── endpoint ─────────────────────────────────────────────────────
@app.get("/shortest-path")
def shortest_path(from_stop: str, to_stop: str):
    # check both stops exist
    if from_stop not in name_to_id:
        raise HTTPException(status_code=404, detail=f"Stop '{from_stop}' not found")
    if to_stop not in name_to_id:
        raise HTTPException(status_code=404, detail=f"Stop '{to_stop}' not found")

    source = name_to_id[from_stop]
    target = name_to_id[to_stop]

    # check if a path actually exists
    if not nx.has_path(G, source, target):
        raise HTTPException(status_code=404, detail="No path found between these stops")

    path_ids = nx.dijkstra_path(G, source, target, weight="weight")
    distance = nx.dijkstra_path_length(G, source, target, weight="weight")

    # convert IDs to readable stop details
    path_details = [
        {
            "stop_id": sid,
            "stop_name": id_to_name[sid],
            "lat": coord[sid]["stop_lat"],
            "lon": coord[sid]["stop_lon"]
        }
        for sid in path_ids
    ]

    return {
        "from": from_stop,
        "to": to_stop,
        "total_distance_km": round(distance, 2),
        "num_stops": len(path_ids),
        "path": path_details
    }
    
@app.get("/search-stops")
def search_stops(query: str):
    # find all stops where name contains the query (case insensitive)
    matches = stops[
        stops["stop_name"].str.contains(query, case=False, na=False)
    ][["stop_id", "stop_name"]].head(10)

    return {"results": matches.to_dict(orient="records")}