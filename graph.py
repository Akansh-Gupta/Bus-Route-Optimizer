import pandas as pd
import networkx as nx
from math import radians, sin, cos, sqrt, atan2

# ---- imports stops.txt and show column and data ----
stops = pd.read_csv("data/stops.txt")
# print(stops.columns.tolist())
# print(stops[["stop_id", "stop_name", "stop_lat", "stop_lon"]])  

# ---- imports stop_time.txt and show column with data ----
stop_times = pd.read_csv("data/stop_times.txt")
# print(stop_times.columns.tolist())
# print(stop_times.head())


# distance between two GPS points in km
def haversine(lat1, lon1, lat2, lon2):
    R = 6371
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat/2)**2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon/2)**2
    return R * 2 * atan2(sqrt(a), sqrt(1 - a))

# build coordinate lookup: stop_id → lat/lon
coord = stops.set_index("stop_id")[["stop_lat", "stop_lon"]].to_dict("index")

# creates an empty undirected graph
G = nx.Graph()  

# add every bus stop as a node
for _,row in stops.iterrows():
    G.add_node(row["stop_id"], name=row["stop_name"], lat=row["stop_lat"], lon=row["stop_lon"])
    
# connect consecutive stops on each trip
for trip_id, group in stop_times.groupby("trip_id"):
    group = group.sort_values("stop_sequence")
    stop_list = group["stop_id"].tolist()

    for i in range(len(stop_list) - 1):
        a = stop_list[i]
        b = stop_list[i + 1]

        if a in coord and b in coord:
            dist = haversine(
                coord[a]["stop_lat"], coord[a]["stop_lon"],
                coord[b]["stop_lat"], coord[b]["stop_lon"]
            )
            G.add_edge(a, b, weight=dist)

print("Stops:", G.number_of_nodes())
print("Connections:", G.number_of_edges())

# print("Total stops added:", G.number_of_nodes())  # prints no. of nodes

# name → stop_id lookup
name_to_id = dict(zip(stops["stop_name"], stops["stop_id"]))

# pick two stops — use names from your stops.txt
source = name_to_id["Laxmi Nagar"]
target = name_to_id["ITO"]

path = nx.dijkstra_path(G, source, target, weight="weight")
length = nx.dijkstra_path_length(G, source, target, weight="weight")

print(f"\nPath found: {len(path)} stops")
print(f"Total distance: {round(length, 2)} km")

# add this right after the path print

id_to_name = dict(zip(stops["stop_id"], stops["stop_name"]))

print("\nRoute:")
for i, stop_id in enumerate(path):
    print(f"  {i+1}. {id_to_name[stop_id]}")