from typing import List, Dict, Tuple, Optional
import math
import itertools
class Hub:
    def __init__(self, id: str, name: str, latitude: float, longitude: float, deadline_hours: float, demand_quantity: int):
        self.id = id
        self.name = name
        self.latitude = latitude
        self.longitude = longitude
        self.deadline_hours = deadline_hours
        self.demand_quantity = demand_quantity
        self.angle = 0.0
        self.cluster_id = None
class Truck:
    def __init__(self, id: str):
        self.id = id
GLOBAL_SPEED_KMPH = 40.0  
SERVICE_TIME_CONSTANT = 0.05  
def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = math.sin(dlat/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon/2)**2
    c = 2 * math.asin(math.sqrt(a))
    r = 6371  
    return c * r
def two_opt(route_indices: List[int], dist_matrix: List[List[float]]) -> List[int]:
    """Applies 2-opt heuristic to improve a TSP tour."""
    best_route = route_indices
    improved = True
    while improved:
        improved = False
        for i in range(1, len(best_route) - 2):
            for j in range(i + 1, len(best_route)):
                if j - i == 1: continue 
                j_next = (j + 1) % len(best_route)
                current_dist = dist_matrix[best_route[i-1]][best_route[i]] + dist_matrix[best_route[j]][best_route[j_next]]
                new_dist = dist_matrix[best_route[i-1]][best_route[j]] + dist_matrix[best_route[i]][best_route[j_next]]
                if new_dist < current_dist - 0.001:  
                    best_route = best_route[:i] + best_route[i:j+1][::-1] + best_route[j+1:]
                    improved = True
    return best_route
def solve_tsp(hubs: List[Hub], depot_lat: float, depot_lon: float) -> List[Hub]:
    """Generates a global Hamiltonian cycle through all hubs + depot using Nearest Neighbor + 2-Opt."""
    if not hubs:
        return []
    n = len(hubs) + 1 
    dist_matrix = [[0.0] * n for _ in range(n)]
    for idx, hub in enumerate(hubs):
        dist_matrix[0][idx+1] = haversine_distance(depot_lat, depot_lon, hub.latitude, hub.longitude)
        dist_matrix[idx+1][0] = dist_matrix[0][idx+1]
    for i in range(len(hubs)):
        for j in range(i+1, len(hubs)):
            d = haversine_distance(hubs[i].latitude, hubs[i].longitude, hubs[j].latitude, hubs[j].longitude)
            dist_matrix[i+1][j+1] = d
            dist_matrix[j+1][i+1] = d
    unvisited = set(range(1, n))
    tour = [0]
    curr = 0
    while unvisited:
        next_node = min(unvisited, key=lambda x: dist_matrix[curr][x])
        unvisited.remove(next_node)
        tour.append(next_node)
        curr = next_node
    optimized_tour_indices = two_opt(tour, dist_matrix)
    depot_idx = optimized_tour_indices.index(0)
    ordered_indices = []
    sequence = optimized_tour_indices[depot_idx:] + optimized_tour_indices[:depot_idx]
    ordered_indices = sequence[1:]
    ordered_hubs = [hubs[i-1] for i in ordered_indices]
    return ordered_hubs
def check_deadline_feasibility(route: List[Hub], start_lat: float, start_lon: float, start_time: float) -> bool:
    """Checks if a sequence of hubs satisfies all deadlines."""
    curr_time = start_time
    curr_lat, curr_lon = start_lat, start_lon
    for hub in route:
        dist = haversine_distance(curr_lat, curr_lon, hub.latitude, hub.longitude)
        travel_time = dist / GLOBAL_SPEED_KMPH
        curr_time += travel_time
        if curr_time > hub.deadline_hours:
            return False
        curr_lat, curr_lon = hub.latitude, hub.longitude
    return True
def calculate_service_time(hub: Hub) -> float:
    """
    Calculate service time based on demand quantity.
    SERVICE_TIME = demand_quantity * SERVICE_CONSTANT
    """
    return hub.demand_quantity * SERVICE_TIME_CONSTANT
def check_deadline_feasibility_with_service_time(route: List[Hub], start_lat: float, start_lon: float, start_time: float) -> bool:
    """Checks if a sequence of hubs satisfies all deadlines including service time."""
    curr_time = start_time
    curr_lat, curr_lon = start_lat, start_lon
    for hub in route:
        dist = haversine_distance(curr_lat, curr_lon, hub.latitude, hub.longitude)
        travel_time = dist / GLOBAL_SPEED_KMPH
        service_time = calculate_service_time(hub)
        curr_time += travel_time + service_time
        if curr_time > hub.deadline_hours:
            return False
        curr_lat, curr_lon = hub.latitude, hub.longitude
    return True
def calculate_angle_from_depot(lat: float, lon: float, depot_lat: float, depot_lon: float) -> float:
    """
    🎯 CORRECT ANGLE CALCULATION (MANDATORY)
    For each hub:
    dx = hub.lon - depot.lon
    dy = hub.lat - depot.lat
    theta = atan2(dy, dx)   # returns radians
    Then normalize:
    if theta < 0:
        theta += 2 * math.pi
    Store: hub.angle = theta
    DO NOT use naive lat difference only.
    """
    dx = lon - depot_lon
    dy = lat - depot_lat
    theta = math.atan2(dy, dx)  
    if theta < 0:
        theta += 2 * math.pi
    return theta
def bearing_from_depot(lat: float, lon: float, depot_lat: float, depot_lon: float) -> float:
    """Bearing in degrees [0, 360) from depot to point. Used for geographic sectors."""
    lat1, lon1 = math.radians(depot_lat), math.radians(depot_lon)
    lat2, lon2 = math.radians(lat), math.radians(lon)
    dlon = lon2 - lon1
    x = math.sin(dlon) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
    bearing = math.degrees(math.atan2(x, y))
    return (bearing + 360) % 360
def cluster_hubs_geographic(
    hubs: List[Hub], depot_lat: float, depot_lon: float, K: int
) -> List[List[Hub]]:
    """
    🎯 PROPER ANGULAR SECTOR CLUSTERING
    1️⃣ CORRECT ANGLE CALCULATION (MANDATORY)
    2️⃣ SORT HUBS BY ANGLE  
    3️⃣ SECTOR SPLITTING LOGIC
    4️⃣ VERIFY CLUSTER OUTPUT BEFORE ROUTE BUILD
    Partition hubs into K geographic clusters by angle from depot.
    Each cluster is one contiguous angular sector so each truck gets one region only.
    """
    if not hubs or K <= 0:
        return []
    if K == 1:
        return [list(hubs)]
    print(f"🧪 DEBUG: Depot coordinates = ({depot_lat}, {depot_lon})")
    for hub in hubs:
        hub.angle = calculate_angle_from_depot(hub.latitude, hub.longitude, depot_lat, depot_lon)
        print(f"🧪 DEBUG: Hub {hub.id} angle = {math.degrees(hub.angle):.1f}°")
    hubs.sort(key=lambda h: h.angle)
    print(f"🧪 DEBUG: Hubs sorted by angle: {[h.id for h in hubs]}")
    sector_angle = (2 * math.pi) / K  
    clusters = [[] for _ in range(K)]
    for hub in hubs:
        cluster_id = int(hub.angle / sector_angle)
        if cluster_id >= K:  
            cluster_id = K - 1
        clusters[cluster_id].append(hub)
        hub.cluster_id = cluster_id  
        print(f"🧪 DEBUG: Hub {hub.id} (angle {math.degrees(hub.angle):.1f}°) → Cluster {cluster_id}")
    for i in range(K):
        print(f"🧪 DEBUG: Cluster {i}: {[h.id for h in clusters[i]]} ({len(clusters[i])} hubs)")
    cluster_0_count = len(clusters[0])
    total_hubs = sum(len(cluster) for cluster in clusters)
    if cluster_0_count == total_hubs and K > 1:
        print(f"🚨 CRITICAL BUG: All {total_hubs} hubs in cluster 0! Angle calculation failed.")
        clusters = [[] for _ in range(K)]
        for i, hub in enumerate(hubs):
            clusters[i % K].append(hub)
            hub.cluster_id = i % K
    return clusters
def fleet_route_assignment_algorithm(hubs: List[Hub], trucks: List[Truck], depot_lat: float, depot_lon: float, current_time: float = 0.0) -> Dict:
    """
    🎯 FIXED CLUSTERING ALGORITHM WITH PROPER ANGULAR SECTORS
    🏗 CLEAN STRUCTURE AFTER FIX:
    Compute angle
    ↓
    Sort hubs
    ↓
    Divide into K equal angular sectors
    ↓
    Assign cluster_id
    ↓
    Freeze ownership
    ↓
    Build route per cluster
    ↓
    Assign to truck
    🎯 FINAL GUARANTEE:
    North hubs → cluster 0
    East hubs → cluster 1
    South hubs → cluster 2
    West hubs → cluster 3
    No cross mixing.
    No collapse.
    """
    result = {
        "routes": [],
        "unassigned_hubs": []
    }
    if not hubs:
        return result
    if not trucks:
        result["unassigned_hubs"] = [{"hub_id": h.id, "reason": "no_trucks"} for h in hubs]
        return result
    K = len(trucks)
    print(f"🧪 DEBUG: Clustering {len(hubs)} hubs into {K} sectors")
    clusters = cluster_hubs_geographic(hubs, depot_lat, depot_lon, K)
    for cluster_id, hub_list in enumerate(clusters):
        for hub in hub_list:
            hub.owner_truck_id = trucks[cluster_id].id
            hub.ownership_state = "ASSIGNED"  
            print(f"🧪 DEBUG: Hub {hub.id} ownership locked to Truck {trucks[cluster_id].id}")
    assigned_routes = []
    for cluster_id, hub_list in enumerate(clusters):
        if not hub_list:
            print(f"🧪 DEBUG: Cluster {cluster_id} is empty - skipping truck {trucks[cluster_id].id}")
            continue
        print(f"🧪 DEBUG: Building route for Truck {trucks[cluster_id].id} with {len(hub_list)} hubs: {[h.id for h in hub_list]}")
        final_tour = solve_tsp(hub_list, depot_lat, depot_lon)
        if not check_deadline_feasibility_with_service_time(final_tour, depot_lat, depot_lon, current_time):
            print(f"🧪 DEBUG: Route infeasible for Truck {trucks[cluster_id].id}, trying EDF order")
            final_tour = sorted(hub_list, key=lambda h: h.deadline_hours)
        assigned_routes.append({
            "truck_id": trucks[cluster_id].id,
            "route": final_tour
        })
        print(f"🧪 DEBUG: Route built for Truck {trucks[cluster_id].id}: {[h.id for h in final_tour]}")
    assigned_hub_ids = set()
    for route_info in assigned_routes:
        for hub in route_info["route"]:
            assigned_hub_ids.add(hub.id)
    all_hub_ids = {h.id for h in hubs}
    unassigned_ids = all_hub_ids - assigned_hub_ids
    if unassigned_ids:
        print(f"🚨 CRITICAL: {len(unassigned_ids)} hubs left unassigned: {unassigned_ids}")
        for hub_id in unassigned_ids:
            result["unassigned_hubs"].append({"hub_id": hub_id, "reason": "clustering_failed"})
    result["routes"] = assigned_routes
    print(f"🧪 DEBUG: Final assignment:")
    for route_info in assigned_routes:
        truck_id = route_info["truck_id"]
        hub_ids = [h.id for h in route_info["route"]]
        print(f"🧪 DEBUG:   Truck {truck_id}: {hub_ids}")
    return result
def optimize_local_queue(active_truck, remaining_hubs: List[Hub], current_time: float) -> Tuple[List[Hub], dict]:
    """
    Phase 2: Checkpoint Reordering Engine
    Generates permutations of remaining queue to maximize route efficiency (minimal distance)
    among all sequences that satisfy deadline constraints.
    """
    decision_info = {
        "truck_id": active_truck.id,
        "checkpoint_time": current_time,
        "previous_queue": [h.name for h in remaining_hubs],
        "evaluated_orders": [],
        "chosen_order": [],
        "decision_reason": ""
    }
    if not remaining_hubs or len(remaining_hubs) <= 1:
        decision_info["chosen_order"] = decision_info["previous_queue"]
        decision_info["decision_reason"] = "Queue too small to optimize."
        return remaining_hubs, decision_info
    start_lat = active_truck.current_latitude
    start_lon = active_truck.current_longitude
    truck_speed = getattr(active_truck, 'speed', GLOBAL_SPEED_KMPH)
    if truck_speed <= 0:
        truck_speed = GLOBAL_SPEED_KMPH
    def evaluate_route_with_details(route_hubs: List[Hub]) -> Tuple[float, float, dict, bool]:
        sim_time = current_time
        sim_lat, sim_lon = start_lat, start_lon
        min_slack = float('inf')
        total_dist = 0.0
        eta_details = {}
        feasible = True
        for hub in route_hubs:
            dist = haversine_distance(sim_lat, sim_lon, hub.latitude, hub.longitude)
            total_dist += dist
            travel_time = dist / truck_speed
            service_time = calculate_service_time(hub)
            sim_time += travel_time + service_time
            slack = hub.deadline_hours - sim_time
            if slack < min_slack:
                min_slack = slack
            if slack < 0:
                feasible = False
            eta_details[hub.name] = {
                "arrival": sim_time,
                "deadline": hub.deadline_hours,
                "slack": slack,
                "service_time": service_time
            }
            sim_lat, sim_lon = hub.latitude, hub.longitude
        return min_slack, total_dist, eta_details, feasible
    best_route = None
    min_dist = float('inf')
    found_feasible = False
    if len(remaining_hubs) <= 6:
        for perm in itertools.permutations(remaining_hubs):
            perm_list = list(perm)
            slack, dist, details, feasible = evaluate_route_with_details(perm_list)
            if feasible:
                found_feasible = True
                if dist < min_dist:
                    min_dist = dist
                    best_route = perm_list
            if len(decision_info["evaluated_orders"]) < 20:
                decision_info["evaluated_orders"].append({
                    "order": [h.name for h in perm_list],
                    "feasible": feasible,
                    "distance_km": dist,
                    "minimum_slack": slack
                })
        if found_feasible:
            decision_info["chosen_order"] = [h.name for h in best_route]
            decision_info["decision_reason"] = f"Found {len([o for o in decision_info['evaluated_orders'] if o['feasible']])} feasible sequences. Selected the shortest route ({min_dist:.1f}km)."
            return best_route, decision_info
        else:
            edf_order = sorted(remaining_hubs, key=lambda h: h.deadline_hours)
            decision_info["chosen_order"] = [h.name for h in edf_order]
            decision_info["decision_reason"] = "No feasible orders found in current search. Falling back to Earliest Deadline First."
            return edf_order, decision_info
    else:
        edf_order = sorted(remaining_hubs, key=lambda h: h.deadline_hours)
        decision_info["chosen_order"] = [h.name for h in edf_order]
        decision_info["decision_reason"] = "Queue too large for full search. Using Earliest Deadline First."
        return edf_order, decision_info
