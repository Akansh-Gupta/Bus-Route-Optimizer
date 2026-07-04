from ortools.constraint_solver import routing_enums_pb2
from ortools.constraint_solver import pywrapcp
from math import radians, sin, cos, sqrt, atan2

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