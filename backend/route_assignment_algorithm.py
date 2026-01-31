from typing import List, Dict, Tuple, Optional
import math


class Hub:
    def __init__(self, id: str, name: str, latitude: float, longitude: float, deadline_hours: float, demand_quantity: int):
        self.id = id
        self.name = name
        self.latitude = latitude
        self.longitude = longitude
        self.deadline_hours = deadline_hours
        self.demand_quantity = demand_quantity


class Truck:
    def __init__(self, id: str, speed_kmh: float, fuel_capacity: float):
        self.id = id
        self.speed_kmh = speed_kmh
        self.fuel_capacity = fuel_capacity


def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Calculate the great circle distance between two points 
    on the earth (specified in decimal degrees)
    Returns distance in kilometers
    """
    # Convert decimal degrees to radians
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])

    # Haversine formula
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = math.sin(dlat/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon/2)**2
    c = 2 * math.asin(math.sqrt(a))
    r = 6371  # Radius of earth in kilometers
    return c * r


def calculate_bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Calculate the initial bearing from point 1 to point 2
    Returns bearing in degrees (0-360)
    """
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    
    dlon = lon2 - lon1
    
    x = math.sin(dlon) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
    
    initial_bearing = math.atan2(x, y)
    bearing = math.degrees(initial_bearing)
    return (bearing + 360) % 360


def sort_hubs_by_deadline(hubs: List[Hub]) -> List[Hub]:
    """Sort hubs by ascending deadline_hours"""
    return sorted(hubs, key=lambda h: h.deadline_hours)


def spatial_clustering(depot_lat: float, depot_lon: float, hubs: List[Hub], 
                      max_cluster_distance: float = 50.0) -> List[List[Hub]]:
    """
    Cluster hubs based on spatial proximity and bearing from depot
    """
    clusters = []
    unassigned = hubs[:]
    
    while unassigned:
        seed_hub = unassigned[0]
        cluster = [seed_hub]
        unassigned.remove(seed_hub)
        
        # Find all hubs within max_cluster_distance of any hub in the current cluster
        changed = True
        while changed:
            changed = False
            to_remove = []
            
            for hub in unassigned:
                for cluster_hub in cluster:
                    dist = haversine_distance(cluster_hub.latitude, cluster_hub.longitude,
                                             hub.latitude, hub.longitude)
                    if dist <= max_cluster_distance:
                        cluster.append(hub)
                        to_remove.append(hub)
                        changed = True
                        break
            
            for hub in to_remove:
                unassigned.remove(hub)
        
        clusters.append(cluster)
    
    return clusters


def nearest_neighbor_route(depot_lat: float, depot_lon: float, hubs: List[Hub], truck_speed: float) -> Tuple[List[Hub], float, float]:
    """
    Build a route using nearest neighbor insertion, considering deadline constraints
    Returns: (ordered_hubs, total_distance, estimated_completion_time)
    """
    if not hubs:
        return [], 0.0, 0.0
    
    route = []
    remaining_hubs = hubs[:]
    current_lat, current_lon = depot_lat, depot_lon
    total_distance = 0.0
    current_time = 0.0
    
    # Start with the hub that has the earliest deadline among the available ones
    remaining_hubs.sort(key=lambda h: h.deadline_hours)
    first_hub = remaining_hubs[0]
    remaining_hubs.remove(first_hub)
    
    # Calculate distance from depot to first hub
    dist_to_first = haversine_distance(depot_lat, depot_lon, first_hub.latitude, first_hub.longitude)
    arrival_time = dist_to_first / truck_speed
    
    # Check if first hub can be reached before its deadline
    if arrival_time > first_hub.deadline_hours:
        return [], 0.0, 0.0  # Cannot serve this hub on time
    
    route.append(first_hub)
    total_distance += dist_to_first
    current_time = arrival_time
    current_lat, current_lon = first_hub.latitude, first_hub.longitude
    
    # Continue building the route with nearest neighbors that meet deadline constraints
    while remaining_hubs:
        # Find the nearest hub that can be reached before its deadline
        valid_next_hubs = []
        for hub in remaining_hubs:
            dist_to_hub = haversine_distance(current_lat, current_lon, hub.latitude, hub.longitude)
            potential_arrival_time = current_time + (dist_to_hub / truck_speed)
            
            if potential_arrival_time <= hub.deadline_hours:
                valid_next_hubs.append((hub, dist_to_hub, potential_arrival_time))
        
        if not valid_next_hubs:
            break  # No more hubs can be added without violating deadlines
        
        # Select the nearest valid hub
        valid_next_hubs.sort(key=lambda x: x[1])  # Sort by distance
        next_hub, dist_to_next, arrival_time = valid_next_hubs[0]
        
        route.append(next_hub)
        total_distance += dist_to_next
        current_time = arrival_time
        current_lat, current_lon = next_hub.latitude, next_hub.longitude
        remaining_hubs.remove(next_hub)
    
    # Add return distance to depot for total distance calculation
    return_dist_to_depot = haversine_distance(current_lat, current_lon, depot_lat, depot_lon)
    total_distance += return_dist_to_depot
    
    return route, total_distance, current_time


def validate_route_feasibility(depot_lat: float, depot_lon: float, route: List[Hub], truck_speed: float) -> Tuple[bool, List[float]]:
    """
    Validate that all hubs in the route can be reached before their deadlines
    Returns: (is_feasible, list_of_arrival_times)
    """
    if not route:
        return True, []
    
    arrival_times = []
    current_lat, current_lon = depot_lat, depot_lon
    current_time = 0.0
    
    for hub in route:
        dist_to_hub = haversine_distance(current_lat, current_lon, hub.latitude, hub.longitude)
        arrival_time = current_time + (dist_to_hub / truck_speed)
        
        if arrival_time > hub.deadline_hours:
            return False, []
        
        arrival_times.append(arrival_time)
        current_time = arrival_time
        current_lat, current_lon = hub.latitude, hub.longitude
    
    return True, arrival_times


def select_routes_for_assignment(sorted_hubs: List[Hub], trucks: List[Truck], 
                               depot_lat: float, depot_lon: float) -> Tuple[List[Dict], List[Dict]]:
    """
    Select the minimal set of routes that covers the earliest-deadline hubs first
    Returns: (assigned_routes, unassigned_hubs)
    """
    # Spatially cluster hubs
    clusters = spatial_clustering(depot_lat, depot_lon, sorted_hubs)
    
    # Generate candidate routes for each cluster
    candidate_routes = []
    for cluster in clusters:
        if not cluster:
            continue
            
        # Generate a route for this cluster using nearest neighbor approach
        for truck in trucks:
            route, distance, completion_time = nearest_neighbor_route(
                depot_lat, depot_lon, cluster[:], truck.speed_kmh
            )
            
            if route and distance > 0:  # Valid route was created
                is_feasible, arrival_times = validate_route_feasibility(
                    depot_lat, depot_lon, route, truck.speed_kmh
                )
                
                if is_feasible:
                    candidate_routes.append({
                        'route': route,
                        'truck': truck,
                        'distance': distance,
                        'completion_time': completion_time,
                        'arrival_times': arrival_times
                    })
    
    # Sort candidate routes by various criteria
    # First by number of hubs (descending), then by total distance (ascending)
    candidate_routes.sort(key=lambda r: (-len(r['route']), r['distance']))
    
    # Assign routes to trucks, preferring to reuse trucks already assigned longer routes
    assigned_routes = []
    unassigned_hub_set = set(hub.id for hub in sorted_hubs)
    
    for candidate_route in candidate_routes:
        route_hub_ids = [hub.id for hub in candidate_route['route']]
        # Check if any of these hubs have already been assigned
        if not any(hub_id in [h.id for route_dict in assigned_routes for h in route_dict['route']] 
                  for hub_id in route_hub_ids):
            # Check if adding this route reduces deadline risk or total distance
            # For simplicity, we'll assign if it covers unassigned hubs
            assigned_routes.append({
                'truck_id': candidate_route['truck'].id,
                'route': candidate_route['route'],
                'total_distance': candidate_route['distance'],
                'estimated_completion_time': candidate_route['completion_time']
            })
            
            # Remove assigned hubs from unassigned set
            for hub_id in route_hub_ids:
                unassigned_hub_set.discard(hub_id)
    
    # Identify unassigned hubs and determine reason
    unassigned_hubs = []
    for hub in sorted_hubs:
        if hub.id in unassigned_hub_set:
            # Check if this hub could potentially meet its deadline
            dist_to_hub = haversine_distance(depot_lat, depot_lon, hub.latitude, hub.longitude)
            # Assume average truck speed for assessment
            avg_speed = sum(t.speed_kmh for t in trucks) / len(trucks) if trucks else 50.0
            time_to_hub = dist_to_hub / avg_speed
            
            if time_to_hub > hub.deadline_hours:
                reason = "misses_deadline"
            else:
                reason = "inefficient_extra_truck"
                
            unassigned_hubs.append({
                'hub_id': hub.id,
                'reason': reason
            })
    
    return assigned_routes, unassigned_hubs


def fleet_route_assignment_algorithm(
    hubs: List[Hub], 
    trucks: List[Truck], 
    depot_lat: float, 
    depot_lon: float
) -> Dict:
    """
    Main algorithm to assign fleet routes based on the specified criteria
    """
    # Sort hubs by ascending deadline_hours
    sorted_hubs = sort_hubs_by_deadline(hubs)
    
    # Select routes for assignment
    assigned_routes, unassigned_hubs = select_routes_for_assignment(
        sorted_hubs, trucks, depot_lat, depot_lon
    )
    
    return {
        'routes': assigned_routes,
        'unassigned_hubs': unassigned_hubs
    }


# Example usage:
if __name__ == "__main__":
    # Example usage
    depot_lat, depot_lon = 10.7905, 78.7047  # Trichy central depot
    
    hubs = [
        Hub("H1", "Hub 1", 10.8, 78.7, 2.0, 5),
        Hub("H2", "Hub 2", 10.9, 78.8, 1.5, 3),
        Hub("H3", "Hub 3", 11.0, 78.9, 3.0, 7),
        Hub("H4", "Hub 4", 10.7, 78.6, 1.0, 2),
    ]
    
    trucks = [
        Truck("T1", 50.0, 100.0),
        Truck("T2", 50.0, 100.0),
    ]
    
    result = fleet_route_assignment_algorithm(hubs, trucks, depot_lat, depot_lon)
    
    print("Assigned Routes:")
    for route in result['routes']:
        hub_names = [h.name for h in route['route']]
        print(f"  Truck {route['truck_id']}: {hub_names}, "
              f"Distance: {route['total_distance']:.2f}km, "
              f"Completion: {route['estimated_completion_time']:.2f}h")
    
    print("\nUnassigned Hubs:")
    for hub in result['unassigned_hubs']:
        print(f"  Hub {hub['hub_id']}: {hub['reason']}")