from ortools.constraint_solver import routing_enums_pb2
from ortools.constraint_solver import pywrapcp
from math import radians, sin, cos, sqrt, atan2
import numpy as np

def haversine(lat1, lon1, lat2, lon2):
    R = 6371
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat/2)**2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon/2)**2
    return R * 2 * atan2(sqrt(a), sqrt(1 - a))

def build_distance_matrix(stops):
    # builds a table: distance from every stop to every other stop
    # stops = [{"stop_name":..., "lat":..., "lon":...}, ...]
    n = len(stops)
    matrix = []
    for i in range(n):
        row = []
        for j in range(n):
            if i == j:
                row.append(0)
            else:
                d = haversine(
                    stops[i]["lat"], stops[i]["lon"],
                    stops[j]["lat"], stops[j]["lon"]
                )
                # OR-Tools needs integers so multiply by 1000
                row.append(int(d * 1000))
        matrix.append(row)
    return matrix

def optimize_route(stops):
    # need at least 2 stops
    if len(stops) < 2:
        return stops

    dist_matrix = build_distance_matrix(stops)
    n = len(stops)

    # tell OR-Tools: n stops, 1 vehicle, start from stop index 0
    manager = pywrapcp.RoutingIndexManager(n, 1, 0)
    routing = pywrapcp.RoutingModel(manager)

    # this function tells OR-Tools the cost of going from one stop to another
    def distance_callback(from_index, to_index):
        from_node = manager.IndexToNode(from_index)
        to_node   = manager.IndexToNode(to_index)
        return dist_matrix[from_node][to_node]

    transit_callback_index = routing.RegisterTransitCallback(distance_callback)
    routing.SetArcCostEvaluatorOfAllVehicles(transit_callback_index)

    # solving strategy — start with the cheapest next step
    search_params = pywrapcp.DefaultRoutingSearchParameters()
    search_params.first_solution_strategy = (
        routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    )

    solution = routing.SolveWithParameters(search_params)

    if not solution:
        return None

    # extract the optimized order from OR-Tools solution
    index = routing.Start(0)
    ordered = []
    while not routing.IsEnd(index):
        node = manager.IndexToNode(index)
        ordered.append(stops[node])
        index = solution.Value(routing.NextVar(index))

    return ordered

def get_bounding_box(stops_df):
    """Find the rectangle that contains all bus stops."""
    min_lat = stops_df['stop_lat'].min()
    max_lat = stops_df['stop_lat'].max()
    min_lon = stops_df['stop_lon'].min()
    max_lon = stops_df['stop_lon'].max()
    return min_lat, max_lat, min_lon, max_lon

def generate_grid(min_lat, max_lat, min_lon, max_lon, grid_size_km=0.5):
    """Create a grid of lat/lon points covering the bounding box."""
    # Convert grid size from km to degrees
    lat_step = grid_size_km / 111.0  # 1 degree latitude ≈ 111 km everywhere

    # Longitude degrees shrink as latitude increases, so we adjust using cos()
    avg_lat = (min_lat + max_lat) / 2
    lon_step = grid_size_km / (111.0 * np.cos(np.radians(avg_lat)))

    lats = np.arange(min_lat, max_lat, lat_step)
    lons = np.arange(min_lon, max_lon, lon_step)

    grid_points = []
    for lat in lats:
        for lon in lons:
            grid_points.append((lat, lon))

    return grid_points


def haversine_distance(lat1, lon1, lat2, lon2):
    """Distance in km between two lat/lon points on Earth's surface."""
    R = 6371  # Earth's radius in km
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat/2)**2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon/2)**2
    c = 2 * atan2(sqrt(a), sqrt(1-a))
    return R * c


def find_dead_zones(stops_df, grid_size_km=0.5, radius_km=1.0):
    """Return grid points that have no bus stop within radius_km."""
    min_lat, max_lat, min_lon, max_lon = get_bounding_box(stops_df)
    grid_points = generate_grid(min_lat, max_lat, min_lon, max_lon, grid_size_km)

    stop_coords = list(zip(stops_df['stop_lat'], stops_df['stop_lon']))

    dead_zones = []
    for (glat, glon) in grid_points:
        nearest_dist = min(
            haversine_distance(glat, glon, slat, slon)
            for (slat, slon) in stop_coords
        )
        if nearest_dist > radius_km:
            dead_zones.append({"lat": glat, "lon": glon, "nearest_stop_km": round(nearest_dist, 2)})

    return dead_zones 