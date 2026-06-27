from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import csv, io, math, time, os
import requests
from typing import List, Dict, Optional, Any, Union
from pydantic import BaseModel
from enum import Enum
from threading import Thread
from route_assignment_algorithm import fleet_route_assignment_algorithm
app = FastAPI(title="Dynamic Route Optimization System")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:3001", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
CENTRAL_HUB = {
    "id": "CENTRAL_DEPOT",
    "name": "Trichy Central Depot",
    "latitude": 10.7905,
    "longitude": 78.7047,
    "demand_quantity": 0
}
MAX_CLUSTER_DISTANCE = 300  
MAX_HUBS_PER_TRUCK = 5
FUEL_CONSUMPTION_RATE = 0.1  
MAX_DRIVING_TIME_HRS = 7.5  
TRUCK_ACTIVATION_PENALTY_LITERS = 8.0  
ROADBLOCK_LOOKAHEAD_KM = 5.0  
RAIN_SPEED_FACTOR = 0.6
TRAFFIC_SPEED_FACTOR = 0.5
GLOBAL_SPEED_KMPH = 40.0
SIMULATION_TIME_STEP = 0.001  
class HubOwnershipState:
    UNASSIGNED = "UNASSIGNED"
    ASSIGNED = "ASSIGNED"
    COMPLETED = "COMPLETED"
class Hub(BaseModel):
    id: str
    name: str
    latitude: float
    longitude: float
    demand_quantity: int
    delivered: bool = False
    deadline_hours: float = 7.5  
    ownership_state: str = "UNASSIGNED"  
    owner_truck_id: Optional[str] = None  
    frozen_at_commit: bool = False  
    cluster_id: Optional[str] = None
    angle: float = 0.0  
    distance_from_trichy_km: float = 0.0
    estimated_arrival_hours: float = 0.0
    slack_expected_hours: float = 0.0
    demand_intensity: str = "Low"  
    severity_risk: str = "Low Risk"  
    is_late: bool = False
    replan_candidate: bool = False
class Task(BaseModel):
    """Represents a single delivery task"""
    hub_id: str
    urgency_weight: float = 0.0  
    assigned_at: float = 0.0  
class Truck(BaseModel):
    id: str
    starting_latitude: float
    starting_longitude: float
    fuel_capacity: float
    current_latitude: float
    current_longitude: float
    fuel_remaining: float
    cost_per_km: float = 2.0  
    max_deliveries: int = 100  
    active: bool = True  
    assigned_hubs: List[str] = []  
    route_plan: List[str] = []  
    completed_deliveries: List[str] = []
    current_task: Optional[Task] = None
    future_task_queue: List[Task] = [] 
    requires_recalculation: bool = False 
    route: List[Dict] = []
    full_route: List[Dict] = []
    current_route_index: int = 0
    speed: float = 50.0
    status: str = "idle"  
    max_capacity: int = 100  
    fuel_efficiency: float = 1.0  
    current_fuel_used: float = 0.0  
    last_decision_point: float = 0.0  
    instructions: Optional[str] = None  
    instruction_status: Optional[str] = "ACTIVE"  
    disaster_notifications: List[str] = []  
    blocked_status: Optional[str] = None  
    cluster_id: Optional[str] = None  
    last_distance_from_depot: float = 0.0  
    last_hub_visited: Optional[str] = None  
class SensorType(str, Enum):
    WEATHER = "weather_sensor"
    TRAFFIC = "traffic_sensor"
class WeatherSensor(BaseModel):
    sensor_id: str
    type: str = "weather_sensor"
    latitude: float
    longitude: float
    radius_km: float
    rain_intensity: float = 0.6
    timestamp: float
class TrafficSensorCreate(BaseModel):
    start_latitude: float
    start_longitude: float
    end_latitude: float
    end_longitude: float
    congestion_factor: float = 0.5

class TrafficSensor(BaseModel):
    sensor_id: str
    type: str = "traffic_sensor"
    start_latitude: float
    start_longitude: float
    end_latitude: float
    end_longitude: float
    congestion_factor: float = 0.5
    timestamp: float
class DisasterType(str, Enum):
    RAIN = "rain"
    TRAFFIC = "traffic"
    ROAD_BLOCK = "road_block"
class Disaster(BaseModel):
    id: str
    disaster_type: DisasterType
    latitude: float
    longitude: float
    radius_km: float = 5.0  
    active: bool = True
    created_at: float = 0.0
    affected_truck_id: Optional[str] = None
    affected_segment_start_idx: Optional[int] = None
    affected_segment_end_idx: Optional[int] = None
    snapped_coordinates: Optional[Dict] = None 
    traffic_severity: Optional[float] = 1.5
    def contains_point(self, lat: float, lon: float) -> bool:
        """Check if a point is within the disaster radius"""
        distance = haversine(self.latitude, self.longitude, lat, lon)
        return distance <= self.radius_km
class AIDecision(BaseModel):
    truck_id: str
    decision: str
    explanation: str
    timestamp: float
    details: Optional[Dict[str, Any]] = None
class WorldState(BaseModel):
    hubs: List[Hub] = []
    trucks: List[Truck] = []
    ai_decisions: List[AIDecision] = []
    simulation_running: bool = False
    simulation_paused: bool = False  
    simulation_speed: float = 1.0  
    simulation_time: float = 0.0
    initial_hubs_with_demand: List[str] = []  
    simulation_phase: str = "pre_start"  
    hubs_frozen: bool = False  
    disasters: List[Disaster] = []  
    active_sensors: List[Union[WeatherSensor, TrafficSensor]] = []
world_state = WorldState()
simulation_thread = None
def initialize_central_hub():
    central_hub_model = Hub(
        id=CENTRAL_HUB["id"],
        name=CENTRAL_HUB["name"],
        latitude=CENTRAL_HUB["latitude"],
        longitude=CENTRAL_HUB["longitude"],
        demand_quantity=0,
        delivered=True,  
        deadline_hours=7.5,  
        ownership_state=HubOwnershipState.COMPLETED,
        owner_truck_id=None,
        frozen_at_commit=True
    )
    world_state.hubs = [central_hub_model]
initialize_central_hub()
@app.on_event("startup")
def reset_world_state_on_startup():
    """
    Ensure a clean world state whenever the backend process starts (e.g. after rerun).
    Prevents old hubs/trucks/routes from persisting across backend restarts.
    """
    global world_state
    world_state.simulation_running = False
    world_state.simulation_paused = False
    world_state.simulation_time = 0.0
    world_state.simulation_phase = "pre_start"
    world_state.hubs_frozen = False
    world_state.trucks = []
    world_state.ai_decisions = []
    world_state.disasters = []
    world_state.active_sensors = []
    world_state.initial_hubs_with_demand = []
    initialize_central_hub()
    print("[STARTUP] World state reset to clean initial state (central hub only).")
def haversine(lat1, lon1, lat2, lon2):
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * \
        math.cos(math.radians(lat2)) * math.sin(dlon/2)**2
    return 2 * R * math.asin(math.sqrt(a))
def interpolate_route(lat1, lon1, lat2, lon2, steps=20):
    return [
        {
            "latitude": lat1 + (lat2 - lat1) * i / steps,
            "longitude": lon1 + (lon2 - lon1) * i / steps
        }
        for i in range(steps + 1)
    ]
def distance_along_route(route, start_idx, end_idx):
    dist = 0.0
    for i in range(start_idx, end_idx):
        p1 = route[i]
        p2 = route[i + 1]
        dist += haversine(
            p1["latitude"], p1["longitude"],
            p2["latitude"], p2["longitude"]
        )
    return dist
def compute_bearing_from_point(lat: float, lon: float) -> float:
    lat1 = math.radians(CENTRAL_HUB["latitude"])
    lon1 = math.radians(CENTRAL_HUB["longitude"])
    lat2 = math.radians(lat)
    lon2 = math.radians(lon)
    dlon = lon2 - lon1
    x = math.sin(dlon) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
    bearing = math.degrees(math.atan2(x, y))
    return (bearing + 360) % 360
def compute_bearing_from_trichy_coords(lat: float, lon: float) -> float:
    return compute_bearing_from_point(lat, lon)
def compute_bearing_from_trichy(hub: Hub) -> float:
    return compute_bearing_from_trichy_coords(hub.latitude, hub.longitude)
def point_to_line_distance(lat, lon, line_start_lat, line_start_lon, line_end_lat, line_end_lon):
    """
    Calculate the shortest distance from a point to a line segment.
    Args:
        lat, lon: Point coordinates
        line_start_lat, line_start_lon: Start of line segment
        line_end_lat, line_end_lon: End of line segment
    Returns:
        Tuple of (distance in km, closest_point_lat, closest_point_lon)
    """
    line_vec_x = line_end_lon - line_start_lon
    line_vec_y = line_end_lat - line_start_lat
    point_vec_x = lon - line_start_lon
    point_vec_y = lat - line_start_lat
    line_len_sq = line_vec_x * line_vec_x + line_vec_y * line_vec_y
    if line_len_sq == 0:
        closest_lat = line_start_lat
        closest_lon = line_start_lon
        distance = haversine(lat, lon, closest_lat, closest_lon)
        return distance, closest_lat, closest_lon
    t = max(0, min(1, (point_vec_x * line_vec_x + point_vec_y * line_vec_y) / line_len_sq))
    closest_lon = line_start_lon + t * line_vec_x
    closest_lat = line_start_lat + t * line_vec_y
    distance = haversine(lat, lon, closest_lat, closest_lon)
    return distance, closest_lat, closest_lon
def get_segment_time(lat1, lon1, lat2, lon2, truck_id, segment_idx):
    dist = haversine(lat1, lon1, lat2, lon2)
    truck = next((t for t in world_state.trucks if t.id == truck_id), None)
    speed = truck.speed if truck else GLOBAL_SPEED_KMPH
    if speed <= 0:
        speed = GLOBAL_SPEED_KMPH
    for sensor in world_state.active_sensors:
        if sensor.type == "weather_sensor":
            dist_to_center, _, _ = point_to_line_distance(
                sensor.latitude, sensor.longitude,
                lat1, lon1, lat2, lon2
            )
            if dist_to_center <= sensor.radius_km:
                speed *= sensor.rain_intensity
        elif sensor.type == "traffic_sensor":
            if (abs(sensor.start_latitude - lat1) < 0.0001 and
                abs(sensor.start_longitude - lon1) < 0.0001 and
                abs(sensor.end_latitude - lat2) < 0.0001 and
                abs(sensor.end_longitude - lon2) < 0.0001):
                speed *= sensor.congestion_factor
    for disaster in world_state.disasters:
        if not disaster.active: continue
        if disaster.disaster_type == DisasterType.RAIN:
            dist_to_center, _, _ = point_to_line_distance(
                disaster.latitude, disaster.longitude,
                lat1, lon1, lat2, lon2
            )
            if dist_to_center <= disaster.radius_km:
                speed *= RAIN_SPEED_FACTOR
        elif disaster.disaster_type == DisasterType.TRAFFIC:
            if disaster.affected_truck_id == truck_id and disaster.affected_segment_start_idx == segment_idx:
                speed *= TRAFFIC_SPEED_FACTOR
    return dist / speed if speed > 0 else float('inf')
OSRM_BASE_URL = "https://router.project-osrm.org"  
def fetch_road_route(lat1: float, lon1: float, lat2: float, lon2: float) -> Dict:
    """
    Fetch a road-based route from OSRM.
    Returns a dict with:
    - coordinates: List of {latitude, longitude} points along the road
    - distance_km: Total route distance in kilometers
    - duration_sec: Estimated duration in seconds
    - success: True if route was fetched successfully
    IMPORTANT: This is called ONCE at destination assignment, never while moving.
    """
    try:
        url = f"{OSRM_BASE_URL}/route/v1/driving/{lon1},{lat1};{lon2},{lat2}"
        params = {
            "overview": "full",       
            "geometries": "geojson",  
            "steps": "false"          
        }
        response = requests.get(url, params=params, timeout=10)
        if response.status_code != 200:
            print(f"[OSRM] HTTP error: {response.status_code}")
            return fallback_route(lat1, lon1, lat2, lon2)
        data = response.json()
        if data.get("code") != "Ok" or not data.get("routes"):
            print(f"[OSRM] No route found: {data.get('code')}")
            return fallback_route(lat1, lon1, lat2, lon2)
        route = data["routes"][0]
        geometry = route["geometry"]
        coordinates = []
        for coord in geometry["coordinates"]:
            coordinates.append({
                "latitude": coord[1],  
                "longitude": coord[0]  
            })
        distance_km = route["distance"] / 1000  
        duration_sec = route["duration"]  
        print(f"[OSRM] Route fetched: {len(coordinates)} points, {distance_km:.1f} km, {duration_sec/60:.1f} min")
        return {
            "coordinates": coordinates,
            "distance_km": distance_km,
            "duration_sec": duration_sec,
            "success": True
        }
    except requests.exceptions.Timeout:
        print("[OSRM] Request timeout - using fallback route")
        return fallback_route(lat1, lon1, lat2, lon2)
    except requests.exceptions.RequestException as e:
        print(f"[OSRM] Request error: {e} - using fallback route")
        return fallback_route(lat1, lon1, lat2, lon2)
    except Exception as e:
        print(f"[OSRM] Unexpected error: {e} - using fallback route")
        return fallback_route(lat1, lon1, lat2, lon2)
def fallback_route(lat1: float, lon1: float, lat2: float, lon2: float) -> Dict:
    """
    Fallback to straight-line interpolation when OSRM is unavailable.
    Uses more points for smoother visualization.
    """
    distance_km = haversine(lat1, lon1, lat2, lon2)
    steps = max(20, int(distance_km * 2))  
    coordinates = [
        {
            "latitude": lat1 + (lat2 - lat1) * i / steps,
            "longitude": lon1 + (lon2 - lon1) * i / steps
        }
        for i in range(steps + 1)
    ]
    print(f"[FALLBACK] Using straight-line route: {len(coordinates)} points, {distance_km:.1f} km")
    return {
        "coordinates": coordinates,
        "distance_km": distance_km,
        "duration_sec": distance_km / 50 * 3600,  
        "success": False  
    }
def get_road_route(lat1: float, lon1: float, lat2: float, lon2: float) -> List[Dict]:
    """
    Get road-based route coordinates.
    This is the main entry point for route fetching:
    - Called ONCE when truck is assigned a destination
    - Never called while truck is moving
    - Returns list of coordinate points to follow
    """
    route_data = fetch_road_route(lat1, lon1, lat2, lon2)
    return route_data["coordinates"]
def is_at_safe_decision_point(truck: Truck) -> bool:
    """
    Check if truck is at a safe decision point where route changes are allowed.
    SAFE DECISION POINTS:
    1. Truck is idle (status == 'idle')
    2. Truck just completed a delivery (current_task is None and status != 'moving')
    3. Truck is at the central depot
    NOT SAFE:
    - Truck is moving toward a hub (destination is LOCKED)
    - Truck has current_task and is in transit
    """
    if truck.status == "moving":
        return False
    if truck.status == "idle":
        return True
    at_depot = (abs(truck.current_latitude - CENTRAL_HUB["latitude"]) < 0.01 and
                abs(truck.current_longitude - CENTRAL_HUB["longitude"]) < 0.01)
    return at_depot
def is_decision_point(truck: Truck) -> bool:
    return is_at_safe_decision_point(truck)
def reorder_task_queue_at_decision_point(truck: Truck):
    """Re-optimize the future task queue using GA-based local search. Only considers hubs owned by this truck."""
    if not truck.future_task_queue:
        return
    remaining_hubs = []
    for t in truck.future_task_queue:
        hub = next((h for h in world_state.hubs if h.id == t.hub_id), None)
        if hub and hub.owner_truck_id == truck.id:
            remaining_hubs.append(hub)
    if remaining_hubs:
        from route_assignment_algorithm import optimize_local_queue
        optimized_hubs, _ = optimize_local_queue(truck, remaining_hubs, world_state.simulation_time)
        optimized_tasks = []
        for opt_hub in optimized_hubs:
            orig_task = next((t for t in truck.future_task_queue if t.hub_id == opt_hub.id), None)
            if orig_task:
                optimized_tasks.append(orig_task)
        truck.future_task_queue = optimized_tasks
        print(f"[REORDER] Task queue for truck {truck.id} re-ordered following urgency update.")
def is_hub_available_for_assignment(hub: Hub) -> bool:
    """
    Check if a hub can be assigned to a truck.
    Only UNASSIGNED hubs are available.
    """
    if hub.id == CENTRAL_HUB["id"]:
        return False
    if hub.delivered or hub.demand_quantity <= 0:
        return False
    return hub.ownership_state == HubOwnershipState.UNASSIGNED
def assign_hub_to_truck(hub_id: str, truck_id: str) -> bool:
    """
    Assign a hub to a truck with strict ownership.
    RULES:
    1. Hub must be UNASSIGNED
    2. After assignment, hub becomes ASSIGNED with owner_truck_id set
    3. No other truck may consider this hub
    Returns True if assignment successful, False otherwise.
    """
    hub = next((h for h in world_state.hubs if h.id == hub_id), None)
    if not hub:
        print(f"[OWNERSHIP ERROR] Hub {hub_id} not found")
        return False
    if hub.ownership_state == HubOwnershipState.ASSIGNED:
        if hub.owner_truck_id == truck_id:
            return True
        else:
            print(f"[OWNERSHIP VIOLATION] Hub {hub_id} already assigned to {hub.owner_truck_id}, cannot assign to {truck_id}")
            return False
    if hub.ownership_state == HubOwnershipState.COMPLETED:
        print(f"[OWNERSHIP ERROR] Hub {hub_id} is already COMPLETED")
        return False
    hub.ownership_state = HubOwnershipState.ASSIGNED
    hub.owner_truck_id = truck_id
    print(f"[OWNERSHIP] Hub {hub.name} ({hub_id}) assigned to Truck {truck_id}")
    return True
def release_hub_ownership(hub_id: str, mark_completed: bool = True) -> bool:
    """
    Release ownership of a hub after delivery completion.
    If mark_completed is True, hub transitions to COMPLETED state.
    If False, hub returns to UNASSIGNED (rare case, like cancellation).
    """
    hub = next((h for h in world_state.hubs if h.id == hub_id), None)
    if not hub:
        return False
    old_owner = hub.owner_truck_id
    if mark_completed:
        hub.ownership_state = HubOwnershipState.COMPLETED
        hub.delivered = True
    else:
        hub.ownership_state = HubOwnershipState.UNASSIGNED
    hub.owner_truck_id = None
    print(f"[OWNERSHIP] Hub {hub.name} ({hub_id}) ownership released by Truck {old_owner}, state={hub.ownership_state}")
    return True
def get_truck_owned_hubs(truck_id: str) -> List[str]:
    """
    Get all hub IDs that are currently owned by a specific truck.
    """
    owned = []
    for hub in world_state.hubs:
        if hub.ownership_state == HubOwnershipState.ASSIGNED and hub.owner_truck_id == truck_id:
            owned.append(hub.id)
    return owned
def get_unassigned_hubs() -> List[Hub]:
    """
    Get all hubs that are available for assignment.
    """
    return [hub for hub in world_state.hubs 
            if is_hub_available_for_assignment(hub)]
def calculate_hub_score(truck: Truck, hub: Hub) -> float:
    """
    Calculate a score for a hub from this truck's perspective.
    Higher score = more attractive to serve.
    SCORING FORMULA:
    score = urgency_weight - distance_cost
    This is a LOCAL decision - each truck evaluates independently.
    IMPORTANT: Removed any scoring term that includes:
    - distance to depot
    - fuel-to-depot preference
    - global nearest-hub selection
    """
    urgency_weight = get_urgency_weight(hub.demand_intensity)
    distance_km = haversine(truck.current_latitude, truck.current_longitude, 
                            hub.latitude, hub.longitude)
    distance_cost = distance_km * 0.5  
    score = urgency_weight - distance_cost
    return score
def handle_upcoming_roadblock(truck: Truck, disaster: Disaster):
    if not truck.current_task:
        truck.status = "blocked"
        truck.blocked_status = "BLOCKED_WAITING_OVERRIDE"
        world_state.ai_decisions.append(
            AIDecision(
                truck_id=truck.id,
                decision="ROADBLOCK_AHEAD_NO_CURRENT_TASK",
                explanation="Roadblock detected ahead but no current task to reroute to",
                timestamp=world_state.simulation_time
            )
        )
        return
    hub = next((h for h in world_state.hubs if h.id == truck.current_task.hub_id), None)
    if not hub:
        return
    new_route = get_road_route(
        truck.current_latitude,
        truck.current_longitude,
        hub.latitude,
        hub.longitude
    )
    new_distance = 0
    if len(new_route) > 1:
        for i in range(len(new_route) - 1):
            new_distance += haversine(
                new_route[i]['latitude'], new_route[i]['longitude'],
                new_route[i+1]['latitude'], new_route[i+1]['longitude']
            )
    new_time_hours = new_distance / GLOBAL_SPEED_KMPH
    new_eta = world_state.simulation_time + new_time_hours
    if new_eta > hub.deadline_hours:
        truck.status = "idle"
        truck.current_task = None
        truck.route = []
        truck.full_route = []
        hub.ownership_state = HubOwnershipState.UNASSIGNED
        hub.owner_truck_id = None
        hub.frozen_at_commit = False
        world_state.ai_decisions.append(
            AIDecision(
                truck_id=truck.id,
                decision="ABANDONED_TASK_DUE_TO_ROADBLOCK",
                explanation=f"Detour to {hub.name} would violate deadline constraint. Dropping task.",
                timestamp=world_state.simulation_time
            )
        )
        return
    truck.route = new_route
    truck.full_route = truck.route.copy()
    truck.current_route_index = 0
    world_state.ai_decisions.append(
        AIDecision(
            truck_id=truck.id,
            decision="REROUTED_AROUND_ROADBLOCK",
            explanation="Detected roadblock ahead; alternate route selected and verified feasible",
            timestamp=world_state.simulation_time
        )
    )
    return
from route_assignment_algorithm import optimize_local_queue, GLOBAL_SPEED_KMPH
def dispatch_next_committed_task(truck: Truck, set_moving_state: bool = True):
    if not truck.future_task_queue:
        truck.status = "idle"
        return
    valid_queue = []
    for t in truck.future_task_queue:
        hub = next((h for h in world_state.hubs if h.id == t.hub_id), None)
        if hub and hub.owner_truck_id == truck.id and hub.ownership_state == HubOwnershipState.ASSIGNED:
            valid_queue.append(t)
        else:
            if hub and hub.owner_truck_id != truck.id:
                print(f"[OWNERSHIP] Truck {truck.id} ignoring hub {t.hub_id} (owned by {hub.owner_truck_id})")
    truck.future_task_queue = valid_queue
    if not truck.future_task_queue:
        truck.status = "idle"
        return
    remaining_hubs = []
    for t in truck.future_task_queue:
        hub = next((h for h in world_state.hubs if h.id == t.hub_id), None)
        if hub and hub.owner_truck_id == truck.id:
            remaining_hubs.append(hub)
    if remaining_hubs and truck.requires_recalculation:
        optimized_hubs, decision_info = optimize_local_queue(truck, remaining_hubs, world_state.simulation_time)
        world_state.ai_decisions.append(
            AIDecision(
                truck_id=truck.id,
                decision="CHECKPOINT_REROUTE_EVALUATION",
                explanation=decision_info.get("decision_reason", "Re-evaluated queue order."),
                timestamp=world_state.simulation_time,
                details=decision_info
            )
        )
        optimized_tasks = []
        for opt_hub in optimized_hubs:
            orig_task = next((t for t in truck.future_task_queue if t.hub_id == opt_hub.id), None)
            if orig_task:
                optimized_tasks.append(orig_task)
        truck.future_task_queue = optimized_tasks
        truck.requires_recalculation = False
    if truck.future_task_queue:
        sim_time = world_state.simulation_time
        sim_lat, sim_lon = truck.current_latitude, truck.current_longitude
        for task in truck.future_task_queue:
            hub = next((h for h in world_state.hubs if h.id == task.hub_id), None)
            if hub:
                dist = haversine(sim_lat, sim_lon, hub.latitude, hub.longitude)
                speed = truck.speed if truck.speed > 0 else GLOBAL_SPEED_KMPH
                travel_time = dist / speed
                service_time = calculate_service_time_for_hub(hub)
                sim_time += travel_time + service_time
                slack = hub.deadline_hours - sim_time
                if slack < 0:
                    hub.severity_risk = "Not Possible"  
                    world_state.ai_decisions.append(
                        AIDecision(
                            truck_id=truck.id,
                            decision="DEADLINE_BROKEN",
                            explanation=f"Hub {hub.name} deadline cannot be met. Deadline: {hub.deadline_hours}h, ETA: {sim_time:.2f}h, Slack: {slack:.2f}h.",
                            timestamp=world_state.simulation_time,
                            details={
                                "hub_id": hub.id,
                                "deadline": hub.deadline_hours,
                                "eta": sim_time,
                                "slack": slack,
                                "service_time": service_time
                            }
                        )
                    )
                elif slack < 0.5:  
                    hub.severity_risk = "High Risk"
                    world_state.ai_decisions.append(
                        AIDecision(
                            truck_id=truck.id,
                            decision="DEADLINE_RISK",
                            explanation=f"Hub {hub.name} deadline at risk. Deadline: {hub.deadline_hours}h, ETA: {sim_time:.2f}h, Slack: {slack:.2f}h.",
                            timestamp=world_state.simulation_time,
                            details={
                                "hub_id": hub.id,
                                "deadline": hub.deadline_hours,
                                "eta": sim_time,
                                "slack": slack,
                                "service_time": service_time
                            }
                        )
                    )
                elif slack < 1.0:  
                    hub.severity_risk = "Medium Risk"
                else:
                    hub.severity_risk = "Low Risk"
                sim_lat, sim_lon = hub.latitude, hub.longitude
    next_task = truck.future_task_queue.pop(0)
    truck.current_task = next_task
    hub = next((h for h in world_state.hubs if h.id == next_task.hub_id), None)
    if not hub:
        return
    if set_moving_state:
        truck.route = get_road_route(
            truck.current_latitude,
            truck.current_longitude,
            hub.latitude,
            hub.longitude
        )
        truck.full_route = truck.route.copy()
        truck.current_route_index = 0
        truck.status = "moving"
def handle_demand_escalation(escalated_hub_id: str):
    """
    Handle when a hub's demand intensity escalates (e.g., slider moved to Emergency).
    OWNERSHIP RULES FOR EMERGENCY HANDLING:
    CASE 1: Hub is ALREADY ASSIGNED to a truck
    - The owning truck reorders its remaining hubs
    - Emergency is served next if fuel allows
    - NO reassignment to other trucks
    - NO stealing of hubs
    CASE 2: Hub is UNASSIGNED
    - Find exactly ONE nearby feasible truck
    - Assign the hub to that truck (mark as ASSIGNED)
    - Prevent any other truck from considering it
    FUEL is a HARD CONSTRAINT in all cases.
    """
    escalated_hub = next((h for h in world_state.hubs if h.id == escalated_hub_id), None)
    if not escalated_hub:
        return
    urgency = get_urgency_weight(escalated_hub.demand_intensity)
    if escalated_hub.ownership_state == HubOwnershipState.ASSIGNED:
        owner_truck_id = escalated_hub.owner_truck_id
        print(f"[DEMAND SYSTEM] Hub {escalated_hub.name} escalated. As per Checkpoint VRP rules, no immediate global re-routing. Truck {owner_truck_id} will optimize its queue at the next delivery checkpoint.")
        world_state.ai_decisions.append(
            AIDecision(
                truck_id=owner_truck_id,
                decision="URGENCY_UPDATED",
                explanation=f"Hub {escalated_hub.name} escalated. Sequence priority will be evaluated at the next local checkpoint.",
                timestamp=world_state.simulation_time
            )
        )
        return
    if escalated_hub.ownership_state != HubOwnershipState.UNASSIGNED:
        return
    if escalated_hub.frozen_at_commit:
        print(f"[EXECUTION ERROR] Frozen hub {escalated_hub.name} is UNASSIGNED - this should not happen!")
        return
    print(f"[EMERGENCY] NEW unassigned hub {escalated_hub.name} escalated to {escalated_hub.demand_intensity} - finding truck")
    best_truck = None
    best_cost = float('inf')
    for truck in world_state.trucks:
        if not truck.active:
            continue
        current_hub_ids = [t.hub_id for t in truck.future_task_queue]
        if truck.current_task:
            current_hub_ids.insert(0, truck.current_task.hub_id)
        if not is_fuel_feasible(truck, current_hub_ids + [escalated_hub_id]):
            continue
        dist_to_hub = haversine(truck.current_latitude, truck.current_longitude, 
                                escalated_hub.latitude, escalated_hub.longitude)
        cost = dist_to_hub + len(truck.future_task_queue) * 50
        if not is_at_safe_decision_point(truck):
            cost += 100  
        if cost < best_cost:
            best_cost = cost
            best_truck = truck
    if best_truck:
        if not assign_hub_to_truck(escalated_hub_id, best_truck.id):
            print(f"[EMERGENCY FAILED] Could not assign hub {escalated_hub_id} to truck {best_truck.id}")
            return
        new_task = Task(
            hub_id=escalated_hub_id,
            urgency_weight=urgency,
            assigned_at=world_state.simulation_time
        )
        if best_truck.status == "idle" and not best_truck.current_task:
            best_truck.current_task = new_task
        else:
            best_truck.future_task_queue.append(new_task)
            best_truck.requires_recalculation = True
            if is_at_safe_decision_point(best_truck):
                reorder_task_queue_at_decision_point(best_truck)
        world_state.ai_decisions.append(
            AIDecision(
                truck_id=best_truck.id,
                decision="EMERGENCY_ASSIGNED",
                explanation=f"Emergency hub {escalated_hub.name} assigned with guaranteed ownership",
                timestamp=world_state.simulation_time
            )
        )
    else:
        print(f"[EMERGENCY WARNING] No feasible truck found for hub {escalated_hub.name}")
def handle_demand_change(hub_id: str):
    """
    🔄 DEMAND CHANGE DURING EXECUTION
    When demand of hub H changes:
    STEP 1 — Update World State
    STEP 2 — Determine Affected Truck
    STEP 3 — Mark for Recalculation
    """
    hub = next((h for h in world_state.hubs if h.id == hub_id), None)
    if not hub:
        print(f"[DEMAND ERROR] Hub {hub_id} not found")
        return
    hub.last_updated_time = world_state.simulation_time
    if hub.owner_truck_id:
        affected_truck = next((t for t in world_state.trucks if t.id == hub.owner_truck_id), None)
        if affected_truck:
            affected_truck.requires_recalculation = True
            world_state.ai_decisions.append(
                AIDecision(
                    truck_id=affected_truck.id,
                    decision="DEMAND_CHANGE_DETECTED",
                    explanation=f"Hub {hub.name} demand changed. Marked for checkpoint recalculation.",
                    timestamp=world_state.simulation_time,
                    details={
                        "hub_id": hub_id,
                        "new_demand": hub.demand_quantity,
                        "service_time": calculate_service_time_for_hub(hub)
                    }
                )
            )
            print(f"[DEMAND] Hub {hub.name} demand updated to {hub.demand_quantity}. Truck {affected_truck.id} marked for recalculation.")
        else:
            print(f"[DEMAND ERROR] Truck {hub.owner_truck_id} not found for hub {hub_id}")
    else:
        print(f"[DEMAND INFO] Hub {hub_id} has no assigned truck. Demand change will be processed at next assignment.")
def calculate_service_time_for_hub(hub) -> float:
    """Calculate service time for a specific hub"""
    from route_assignment_algorithm import SERVICE_TIME_CONSTANT
    return hub.demand_quantity * SERVICE_TIME_CONSTANT
def calculate_service_time_change(old_demand: int, new_demand: int) -> float:
    """Calculate the change in service time based on demand change"""
    from route_assignment_algorithm import SERVICE_TIME_CONSTANT
    old_service_time = old_demand * SERVICE_TIME_CONSTANT
    new_service_time = new_demand * SERVICE_TIME_CONSTANT
    return new_service_time - old_service_time
def calculate_route_distance(hub_ids: List[str], start_lat: float, start_lon: float) -> float:
    """Calculate total distance for a route visiting hubs in order"""
    if not hub_ids:
        return 0.0
    total = 0.0
    current_lat, current_lon = start_lat, start_lon
    for hub_id in hub_ids:
        hub = next(h for h in world_state.hubs if h.id == hub_id)
        total += haversine(current_lat, current_lon, hub.latitude, hub.longitude)
        current_lat, current_lon = hub.latitude, hub.longitude
    return total
def assign_hubs_to_trucks():
    """
    ====================================================
    COMMIT PHASE - STRICT TWO-STAGE CONTRACT
    ====================================================
    MANDATORY REQUIREMENTS:
    1. Every hub with demand_quantity > 0 MUST be ASSIGNED to exactly one truck
    2. No hub may remain UNASSIGNED after commit
    3. If clustering fails, fallback assignment to nearest feasible truck MUST occur
    4. If any hub remains unassigned, the simulation MUST NOT proceed
    5. All initial hubs are FROZEN at commit - ownership is permanent
    This function returns True if commit was successful, False if any hub is unassigned.
    """
    return fleet_optimized_assignment_algorithm()
def get_urgency_weight(intensity: str) -> float:
    """Map demand intensity to urgency weight for scoring"""
    mapping = {
        "Low": 0.0,
        "Medium": 100.0,
        "High": 500.0,
        "Emergency": 2000.0
    }
    return mapping.get(intensity, 0.0)
def is_fuel_feasible(truck: Truck, hub_ids: List[str]) -> bool:
    """Check if truck can visit all hubs in order and return to depot"""
    if not hub_ids:
        return True
    total_dist = 0.0
    curr_lat, curr_lon = truck.current_latitude, truck.current_longitude
    for hub_id in hub_ids:
        hub = next((h for h in world_state.hubs if h.id == hub_id), None)
        if not hub: continue
        total_dist += haversine(curr_lat, curr_lon, hub.latitude, hub.longitude)
        curr_lat, curr_lon = hub.latitude, hub.longitude
    total_dist += haversine(curr_lat, curr_lon, CENTRAL_HUB["latitude"], CENTRAL_HUB["longitude"])
    fuel_needed = total_dist * FUEL_CONSUMPTION_RATE
    return fuel_needed <= truck.fuel_remaining
def is_fuel_feasible_with_return(truck: Truck, target_hub: Hub) -> bool:
    """Check if truck can reach target_hub and then return to depot"""
    dist_to_hub = haversine(truck.current_latitude, truck.current_longitude, 
                            target_hub.latitude, target_hub.longitude)
    dist_back_to_depot = haversine(target_hub.latitude, target_hub.longitude,
                                   CENTRAL_HUB["latitude"], CENTRAL_HUB["longitude"])
    total_dist = dist_to_hub + dist_back_to_depot
    fuel_needed = total_dist * FUEL_CONSUMPTION_RATE
    return fuel_needed <= truck.fuel_remaining
def simulation_loop():
    """
    CONTINUOUSLY RUNNING EXECUTION LOOP
    DESIGN PRINCIPLES:
    1. System is always active - no explicit end condition
    2. Trucks make LOCAL decisions at SAFE DECISION POINTS only
    3. While moving, destination is LOCKED - no mid-route changes
    4. Demand slider (intensity) influences decisions at next safe point
    5. Driver experience: stable, predictable, no frequent rerouting
    DECISION TIMING:
    - IDLE at depot: Select next hub using local scoring
    - After DELIVERY: Extend route if efficient, else return to depot
    - While MOVING: Destination is LOCKED, no changes allowed
    """
    while world_state.simulation_running:
        if world_state.simulation_paused:
            time.sleep(0.2)
            continue
        time.sleep(0.1 / world_state.simulation_speed)
        world_state.simulation_time += SIMULATION_TIME_STEP
        for truck in world_state.trucks:
            if not truck.active:
                continue
            if truck.status == "blocked":
                continue
            if truck.status == "idle":
                truck.last_decision_point = world_state.simulation_time
                if truck.future_task_queue or world_state.simulation_phase in ("committed", "executing"):
                    dispatch_next_committed_task(truck, set_moving_state=True)
                if truck.current_task:
                    hub = next((h for h in world_state.hubs if h.id == truck.current_task.hub_id), None)
                    if hub:
                        truck.route = get_road_route(
                            truck.current_latitude,
                            truck.current_longitude,
                            hub.latitude,
                            hub.longitude
                        )
                        truck.full_route = truck.route.copy()
                        truck.current_route_index = 0
                        truck.status = "moving"
                        world_state.ai_decisions.append(
                            AIDecision(
                                truck_id=truck.id,
                                decision="MOVING",
                                explanation=f"Moving to {hub.name} (Deadline: {hub.deadline_hours}h) - destination LOCKED",
                                timestamp=world_state.simulation_time
                            )
                        )
            elif truck.status == "moving":
                time_to_advance = SIMULATION_TIME_STEP
                while time_to_advance > 0 and truck.route and truck.current_route_index < len(truck.route):
                    next_p = truck.route[truck.current_route_index]
                    seg_time = get_segment_time(truck.current_latitude, truck.current_longitude, 
                                              next_p["latitude"], next_p["longitude"], 
                                              truck.id, truck.current_route_index)
                    if seg_time <= 0:
                        truck.current_route_index += 1
                        continue
                    if time_to_advance >= seg_time:
                        time_to_advance -= seg_time
                        segment_dist = haversine(truck.current_latitude, truck.current_longitude, 
                                               next_p["latitude"], next_p["longitude"])
                        truck.fuel_remaining -= segment_dist * FUEL_CONSUMPTION_RATE
                        truck.current_fuel_used += segment_dist * FUEL_CONSUMPTION_RATE
                        truck.current_latitude = next_p["latitude"]
                        truck.current_longitude = next_p["longitude"]
                        truck.current_route_index += 1
                    else:
                        fraction = time_to_advance / seg_time
                        full_seg_dist = haversine(truck.current_latitude, truck.current_longitude, 
                                                next_p["latitude"], next_p["longitude"])
                        moved_dist = full_seg_dist * fraction
                        truck.fuel_remaining -= moved_dist * FUEL_CONSUMPTION_RATE
                        truck.current_fuel_used += moved_dist * FUEL_CONSUMPTION_RATE
                        truck.current_latitude += (next_p["latitude"] - truck.current_latitude) * fraction
                        truck.current_longitude += (next_p["longitude"] - truck.current_longitude) * fraction
                        time_to_advance = 0
                if truck.current_route_index >= len(truck.route):
                    if truck.current_task:
                        hub = next((h for h in world_state.hubs if h.id == truck.current_task.hub_id), None)
                        if hub:
                            hub.demand_quantity = max(0, hub.demand_quantity - 1)
                            if hub.demand_quantity == 0:
                                release_hub_ownership(hub.id, mark_completed=True)
                            world_state.ai_decisions.append(
                                AIDecision(
                                    truck_id=truck.id,
                                    decision="DELIVERED",
                                    explanation=f"Delivered to {hub.name}. Fuel used: {truck.current_fuel_used:.1f}L",
                                    timestamp=world_state.simulation_time
                                )
                            )
                        completed_hub = hub
                        truck.current_task = None
                        if world_state.simulation_phase in ("committed", "executing"):
                            if truck.future_task_queue:
                                truck.status = "idle" 
                            else:
                                truck.route = get_road_route(
                                    truck.current_latitude,
                                    truck.current_longitude,
                                    CENTRAL_HUB["latitude"],
                                    CENTRAL_HUB["longitude"]
                                )
                                truck.current_route_index = 0
                                truck.status = "returning"
                        else:
                            truck.status = "idle"
                    else:
                        truck.status = "idle"
            elif truck.status == "returning":
                time_to_advance = SIMULATION_TIME_STEP
                while time_to_advance > 0 and truck.route and truck.current_route_index < len(truck.route):
                    next_p = truck.route[truck.current_route_index]
                    seg_time = get_segment_time(truck.current_latitude, truck.current_longitude, 
                                              next_p["latitude"], next_p["longitude"], 
                                              truck.id, truck.current_route_index)
                    if seg_time <= 0:
                        truck.current_route_index += 1
                        continue
                    if time_to_advance >= seg_time:
                        time_to_advance -= seg_time
                        truck.current_latitude = next_p["latitude"]
                        truck.current_longitude = next_p["longitude"]
                        truck.current_route_index += 1
                    else:
                        fraction = time_to_advance / seg_time
                        truck.current_latitude += (next_p["latitude"] - truck.current_latitude) * fraction
                        truck.current_longitude += (next_p["longitude"] - truck.current_longitude) * fraction
                        time_to_advance = 0
                if truck.current_route_index >= len(truck.route):
                    truck.current_latitude = CENTRAL_HUB["latitude"]
                    truck.current_longitude = CENTRAL_HUB["longitude"]
                    truck.fuel_remaining = truck.fuel_capacity
                    truck.current_fuel_used = 0.0
                    truck.route.clear()
                    truck.full_route.clear()
                    truck.current_route_index = 0
                    truck.status = "idle"
                    world_state.ai_decisions.append(
                        AIDecision(
                            truck_id=truck.id, 
                            decision="ARRIVED_AT_DEPOT", 
                            explanation="Truck arrived at depot and refueled", 
                            timestamp=world_state.simulation_time
                        )
                    )
@app.post("/upload/hubs")
async def upload_hubs(file: UploadFile = File(...)):
    text = (await file.read()).decode()
    reader = csv.DictReader(io.StringIO(text))
    world_state.hubs = [h for h in world_state.hubs if h.id == CENTRAL_HUB["id"]]
    for row in reader:
        distance_from_trichy = haversine(CENTRAL_HUB["latitude"], CENTRAL_HUB["longitude"], float(row["latitude"]), float(row["longitude"]))
        if distance_from_trichy > 220:
            continue  
        hub = Hub(
            id=row["id"],
            name=row["name"],
            latitude=float(row["latitude"]),
            longitude=float(row["longitude"]),
            demand_quantity=int(row["demand_quantity"]),
            availability=int(row.get("availability", 20)),
            delivered=False,
            demand_intensity=row.get("demand_intensity", "Medium"),
            deadline_hours=float(row.get("deadline_hours", 7.5)),  
            distance_from_trichy_km=distance_from_trichy
        )
        world_state.hubs.append(hub)
    return {"count": len([h for h in world_state.hubs if h.id != CENTRAL_HUB["id"]])}
@app.post("/upload/trucks")
async def upload_trucks(file: UploadFile = File(...)): 
    text = (await file.read()).decode()
    reader = csv.DictReader(io.StringIO(text))
    world_state.trucks = [
        Truck(
            id=row["id"],
            starting_latitude=CENTRAL_HUB["latitude"],
            starting_longitude=CENTRAL_HUB["longitude"],
            current_latitude=CENTRAL_HUB["latitude"],
            current_longitude=CENTRAL_HUB["longitude"],
            fuel_capacity=float(row["fuel_capacity"]),
            fuel_remaining=float(row["fuel_capacity"]),
            cost_per_km=float(row.get("cost_per_km", 2.0)),  
            max_deliveries=int(row.get("max_deliveries", 100)),  
            active=row.get("active", "true").lower() == "true",  
            max_capacity=int(row.get("max_capacity", 100)),  
            fuel_efficiency=float(row.get("fuel_efficiency", 1.0)),  
            current_fuel_used=float(row.get("current_fuel_used", 0.0)),  
            speed=float(row.get("speed", GLOBAL_SPEED_KMPH)), 
        )
        for row in reader
    ]
    return {"count": len(world_state.trucks)}
@app.post("/simulation/start")
def start_sim():
    """
    ====================================================
    COMMIT PHASE - FLEXIBLE TWO-STAGE CONTRACT
    ====================================================
    This endpoint initiates the commit phase:
    1. Freezes all hubs
    2. Assigns feasible hubs to trucks using fleet optimization
    3. Allows unassigned hubs when constraints prevent service
    4. Starts execution phase regardless
    """
    if world_state.simulation_running:
        return {"message": "Simulation is already running"}
    world_state.hubs_frozen = True
    world_state.simulation_phase = "committing"
    commit_success = assign_hubs_to_trucks()
    for truck in world_state.trucks:
        if not truck.future_task_queue:
            continue
        current_eta = world_state.simulation_time
        curr_lat, curr_lon = truck.current_latitude, truck.current_longitude
        for task in truck.future_task_queue:
            hub = next((h for h in world_state.hubs if h.id == task.hub_id), None)
            if not hub:
                continue
            dist = haversine(curr_lat, curr_lon, hub.latitude, hub.longitude)
            current_eta += (dist / GLOBAL_SPEED_KMPH)
            if current_eta > hub.deadline_hours:
                world_state.hubs_frozen = False
                world_state.simulation_phase = "pre_start"
                for h in world_state.hubs:
                    h.ownership_state = HubOwnershipState.UNASSIGNED
                    h.owner_truck_id = None
                    h.frozen_at_commit = False
                for t in world_state.trucks:
                    t.route_plan.clear()
                    t.future_task_queue = []
                    t.current_task = None
                    t.assigned_hubs.clear()
                raise HTTPException(
                    status_code=400, 
                    detail=f"Simulation aborted: Hub '{hub.name}' assigned ETA {current_eta:.2f}h violates strict deadline {hub.deadline_hours}h."
                )
            curr_lat, curr_lon = hub.latitude, hub.longitude
    if not commit_success:
        active_trucks_count = len([t for t in world_state.trucks if t.active])
        if active_trucks_count == 0:
            world_state.hubs_frozen = False
            world_state.simulation_phase = "pre_start"
            for hub in world_state.hubs:
                if hub.id != CENTRAL_HUB["id"]:
                    hub.ownership_state = HubOwnershipState.UNASSIGNED
                    hub.owner_truck_id = None
                    hub.frozen_at_commit = False
            for truck in world_state.trucks:
                truck.route_plan.clear()
                truck.future_task_queue = []
                truck.current_task = None
            raise HTTPException(
                status_code=400, 
                detail="COMMIT FAILED: No active trucks available. Please upload trucks.csv before starting simulation."
            )
        else:
            pass  
    world_state.simulation_phase = "committed"
    world_state.simulation_running = True
    world_state.simulation_phase = "executing"
    global simulation_thread
    simulation_thread = Thread(target=simulation_loop, daemon=True)
    simulation_thread.start()
    assigned_count = len([h for h in world_state.hubs if h.ownership_state == HubOwnershipState.ASSIGNED])
    unassigned_count = len([h for h in world_state.hubs if h.ownership_state == HubOwnershipState.UNASSIGNED and h.id != CENTRAL_HUB["id"]])
    return {
        "message": f"COMMIT SUCCESS: {assigned_count} hubs assigned, {unassigned_count} hubs deferred due to constraints. Execution phase started.",
        "hubs_committed": assigned_count,
        "hubs_deferred": unassigned_count,
        "trucks_active": len([t for t in world_state.trucks if t.active])
    }
@app.post("/simulation/stop")
def stop_sim():
    world_state.simulation_running = False
    world_state.simulation_paused = False  
    return {"message": "Simulation stopped"}
@app.post("/simulation/pause")
def pause_simulation():
    world_state.simulation_paused = True
    return {"status": "paused"}
@app.post("/simulation/resume")
def resume_simulation():
    world_state.simulation_paused = False
    return {"status": "resumed"}
@app.post("/simulation/speed")
def set_simulation_speed(request: dict):
    world_state.simulation_speed = float(request["speed"])
    return {"speed": world_state.simulation_speed}
@app.post("/simulation/reset")
def reset_simulation():
    """RESET TOTAL WORLD STATE"""
    global world_state, simulation_thread
    world_state.simulation_running = False
    world_state = WorldState()
    initialize_central_hub()
    world_state.simulation_phase = "pre_start"
    world_state.simulation_time = 0.0
    world_state.hubs_frozen = False
    return {"message": "System state has been fully reset to initial defaults"}
@app.get("/state")
def get_state():
    for truck in world_state.trucks:
        if not truck.active:
            continue
        sim_time = world_state.simulation_time
        sim_lat = truck.current_latitude
        sim_lon = truck.current_longitude
        if truck.current_task:
            route_points = truck.full_route if truck.full_route else truck.route
            curr_idx = truck.current_route_index
            if route_points and curr_idx < len(route_points):
                sim_time += get_segment_time(sim_lat, sim_lon, route_points[curr_idx]["latitude"], route_points[curr_idx]["longitude"], truck.id, curr_idx)
                sim_lat, sim_lon = route_points[curr_idx]["latitude"], route_points[curr_idx]["longitude"]
                for i in range(curr_idx, len(route_points) - 1):
                    sim_time += get_segment_time(route_points[i]["latitude"], route_points[i]["longitude"], route_points[i+1]["latitude"], route_points[i+1]["longitude"], truck.id, i)
                    sim_lat, sim_lon = route_points[i+1]["latitude"], route_points[i+1]["longitude"]
            curr_hub = next((h for h in world_state.hubs if h.id == truck.current_task.hub_id), None)
            if curr_hub:
                curr_hub.estimated_arrival_hours = sim_time
                curr_hub.slack_expected_hours = curr_hub.deadline_hours - sim_time
        for task in truck.future_task_queue:
            q_hub = next((h for h in world_state.hubs if h.id == task.hub_id), None)
            if q_hub:
                sim_time += get_segment_time(sim_lat, sim_lon, q_hub.latitude, q_hub.longitude, truck.id, -1)
                sim_lat, sim_lon = q_hub.latitude, q_hub.longitude
                q_hub.estimated_arrival_hours = sim_time
                q_hub.slack_expected_hours = q_hub.deadline_hours - sim_time
    for hub in world_state.hubs:
        if hub.id == CENTRAL_HUB["id"] or hub.delivered:
            continue
        if hub.owner_truck_id is None:
            distance = haversine(CENTRAL_HUB["latitude"], CENTRAL_HUB["longitude"], hub.latitude, hub.longitude)
            speed = GLOBAL_SPEED_KMPH
            for sensor in world_state.active_sensors:
                if sensor.type == "weather_sensor":
                    dist_to_center, _, _ = point_to_line_distance(sensor.latitude, sensor.longitude, CENTRAL_HUB["latitude"], CENTRAL_HUB["longitude"], hub.latitude, hub.longitude)
                    if dist_to_center <= sensor.radius_km:
                        speed *= sensor.rain_intensity
            for disaster in world_state.disasters:
                if disaster.active and disaster.disaster_type == DisasterType.RAIN:
                    dist_to_center, _, _ = point_to_line_distance(disaster.latitude, disaster.longitude, CENTRAL_HUB["latitude"], CENTRAL_HUB["longitude"], hub.latitude, hub.longitude)
                    if dist_to_center <= disaster.radius_km:
                        speed *= RAIN_SPEED_FACTOR
            hub.estimated_arrival_hours = distance / speed + world_state.simulation_time
            hub.slack_expected_hours = hub.deadline_hours - hub.estimated_arrival_hours
        slack = hub.slack_expected_hours
        if slack < 0:
            hub.severity_risk = "Not Possible"
        elif slack <= 0.5:
            hub.severity_risk = "High Risk"
        elif slack <= 2.0:
            hub.severity_risk = "Medium Risk"
        else:
            hub.severity_risk = "Low Risk"
    return world_state.model_dump()
@app.post("/disruptions/{disruption_type}")
def toggle_disruption(disruption_type: str, active: bool = True):
    """Toggle disruption (placeholder - can be extended later)"""
    return {"message": f"Disruption {disruption_type} set to {active}"}
class HubCreateRequest(BaseModel):
    name: str
    latitude: float
    longitude: float
    demand_quantity: int
    deadline_hours: Optional[float] = None
    demand_intensity: Optional[str] = "Medium"
class HubUpdateRequest(BaseModel):
    demand_quantity: int
    deadline_hours: Optional[float] = None
@app.post("/hubs/manual")
async def create_hub_manual(hub_data: HubCreateRequest):
    """Create a new hub manually at runtime"""
    existing_ids = {h.id for h in world_state.hubs}
    live_counter = 1
    hub_id = f"LIVE_{live_counter}"
    while hub_id in existing_ids:
        live_counter += 1
        hub_id = f"LIVE_{live_counter}"
    distance_from_trichy = haversine(CENTRAL_HUB["latitude"], CENTRAL_HUB["longitude"], hub_data.latitude, hub_data.longitude)
    min_time_hours = distance_from_trichy / GLOBAL_SPEED_KMPH
    assigned_deadline = hub_data.deadline_hours
    if assigned_deadline is None or assigned_deadline <= 0:
        assigned_deadline = max(15.0, min_time_hours + 3.0) 
    if assigned_deadline < min_time_hours:
        raise HTTPException(status_code=400, detail=f"Deadline impossible — minimum reachable time is {min_time_hours:.2f} hours")
    new_hub = Hub(
        id=hub_id,
        name=hub_data.name,
        latitude=hub_data.latitude,
        longitude=hub_data.longitude,
        demand_quantity=hub_data.demand_quantity,
        delivered=False,
        deadline_hours=assigned_deadline,
        demand_intensity=hub_data.demand_intensity or "Medium",
        distance_from_trichy_km=distance_from_trichy,
        frozen_at_commit=False  
    )
    if world_state.hubs and world_state.hubs[0].id == CENTRAL_HUB["id"]:
        world_state.hubs.insert(1, new_hub)
    else:
        world_state.hubs.append(new_hub)
    if world_state.simulation_running:
        handle_demand_escalation(hub_id)
    return {"message": f"Hub {hub_id} created and assignment triggered", "hub": new_hub.model_dump(), "total_hubs": len(world_state.hubs)}
@app.post("/hubs/random")
async def create_random_hubs():  
    """Create 3 fixed deterministic hubs and clear existing non-central hubs"""
    world_state.hubs = [h for h in world_state.hubs if h.id == CENTRAL_HUB["id"]]
    fixed_hubs = [
                    {
                        "id": "H1",
                        "name": "Thanjavur",
                        "latitude": 10.7867,
                        "longitude": 79.1378,
                        "demand_quantity": 1,
                        "availability": 20,
                        "demand_intensity": "High",
                        "deadline_hours": 7
                    },
                    {
                        "id": "H2",
                        "name": "Karur",
                        "latitude": 10.9601,
                        "longitude": 78.0766,
                        "demand_quantity": 1,
                        "availability": 20,
                        "demand_intensity": "Medium",
                        "deadline_hours": 7.5
                    },
                    {
                        "id": "H3",
                        "name": "Dindigul",
                        "latitude": 10.3673,
                        "longitude": 77.9803,
                        "demand_quantity": 1,
                        "availability": 20,
                        "demand_intensity": "Medium",
                        "deadline_hours": 7
                    },
                    {
                        "id": "H4",
                        "name": "Perambalur",
                        "latitude": 11.2342,
                        "longitude": 78.8803,
                        "demand_quantity": 1,
                        "availability": 20,
                        "demand_intensity": "Low",
                        "deadline_hours": 8
                    },
                    {
                        "id": "H5",
                        "name": "Ariyalur",
                        "latitude": 11.1401,
                        "longitude": 79.0787,
                        "demand_quantity": 1,
                        "availability": 20,
                        "demand_intensity": "Low",
                        "deadline_hours": 8
                    },
                    {
                        "id": "H6",
                        "name": "Pudukkottai",
                        "latitude": 10.3797,
                        "longitude": 78.8208,
                        "demand_quantity": 1,
                        "availability": 20,
                        "demand_intensity": "Medium",
                        "deadline_hours": 8
                    },
                    {
                        "id": "H7",
                        "name": "Sivaganga",
                        "latitude": 9.8470,
                        "longitude": 78.4809,
                        "demand_quantity": 1,
                        "availability": 20,
                        "demand_intensity": "Low",
                        "deadline_hours": 8
                    },
                    {
                        "id": "H8",
                        "name": "Salem",
                        "latitude": 11.6643,
                        "longitude": 78.1460,
                        "demand_quantity": 1,
                        "availability": 20,
                        "demand_intensity": "High",
                        "deadline_hours": 7
                    },
                    {
                        "id": "H9",
                        "name": "Namakkal",
                        "latitude": 11.2194,
                        "longitude": 78.1677,
                        "demand_quantity": 1,
                        "availability": 20,
                        "demand_intensity": "Medium",
                        "deadline_hours": 6.2
                    }
                ]
    for hub_data in fixed_hubs:
        distance_from_trichy = haversine(CENTRAL_HUB["latitude"], CENTRAL_HUB["longitude"], hub_data["latitude"], hub_data["longitude"])
        if distance_from_trichy > 220:
            continue  
        hub_data["distance_from_trichy_km"] = distance_from_trichy
        hub = Hub(**hub_data)
        world_state.hubs.append(hub)
    
    # Auto-seed trucks for immediate testing with fixed hubs
    if not world_state.trucks:
        print("[INFO] Seeding default trucks for testing")
        from backend.main import Truck
        world_state.trucks = [
            Truck(id="TRK1", current_latitude=CENTRAL_HUB["latitude"], current_longitude=CENTRAL_HUB["longitude"], speed_kmph=GLOBAL_SPEED_KMPH),
            Truck(id="TRK2", current_latitude=CENTRAL_HUB["latitude"], current_longitude=CENTRAL_HUB["longitude"], speed_kmph=GLOBAL_SPEED_KMPH)
        ]

    if world_state.simulation_running:
        print(f"[INFO] Fixed hubs created during simulation. Will be included in next simulation run.")
    return {"message": "Random/Fixed hubs created", "total_hubs": len(world_state.hubs), "trucks": len(world_state.trucks)}
@app.put("/hubs/{hub_id}/demand")
def update_hub_demand(hub_id: str, update_data: HubUpdateRequest):
    """Update hub demand quantity using checkpoint-based demand reaction system"""
    if hub_id == CENTRAL_HUB["id"]:
        raise HTTPException(status_code=400, detail="Cannot modify central hub")
    hub = next((h for h in world_state.hubs if h.id == hub_id), None)
    if not hub:
        raise HTTPException(status_code=404, detail="Hub not found")
    old_demand = hub.demand_quantity
    hub.demand_quantity = update_data.demand_quantity
    hub.last_updated_time = world_state.simulation_time
    if update_data.deadline_hours is not None:
        distance_from_trichy = haversine(CENTRAL_HUB["latitude"], CENTRAL_HUB["longitude"], hub.latitude, hub.longitude)
        min_time_hours = distance_from_trichy / GLOBAL_SPEED_KMPH
        if update_data.deadline_hours < min_time_hours:
            raise HTTPException(status_code=400, detail=f"Deadline impossible — minimum reachable time is {min_time_hours:.2f} hours")
        hub.deadline_hours = update_data.deadline_hours
    if old_demand != update_data.demand_quantity:
        handle_demand_change(hub_id)
    if hub.demand_quantity <= 0:
        hub.delivered = True
        release_hub_ownership(hub_id, mark_completed=True)
    return {"message": f"Hub {hub_id} updated", "hub": hub.model_dump()}
class DemandIntensityUpdate(BaseModel):
    demand_intensity: str  
@app.put("/hubs/{hub_id}/intensity")
def update_demand_intensity(hub_id: str, update_data: DemandIntensityUpdate):
    """
    Update hub demand intensity (urgency) - triggers intelligent reordering at decision points
    This is the live, mutable urgency control that allows dynamic responsiveness
    """
    if hub_id == CENTRAL_HUB["id"]:
        raise HTTPException(status_code=400, detail="Cannot modify central hub")
    if update_data.demand_intensity not in ["Low", "Medium", "High", "Emergency"]:
        raise HTTPException(status_code=400, detail="Invalid intensity. Must be: Low, Medium, High, Emergency")
    hub = next((h for h in world_state.hubs if h.id == hub_id), None)
    if not hub:
        raise HTTPException(status_code=404, detail="Hub not found")
    old_intensity = hub.demand_intensity
    hub.demand_intensity = update_data.demand_intensity
    if world_state.simulation_running:
        old_weight = get_urgency_weight(old_intensity)
        new_weight = get_urgency_weight(update_data.demand_intensity)
        if new_weight > old_weight:
            handle_demand_escalation(hub_id)
        for truck in world_state.trucks:
            for task in truck.future_task_queue:
                if task.hub_id == hub_id:
                    task.urgency_weight = new_weight
            if is_decision_point(truck):
                reorder_task_queue_at_decision_point(truck)
    return {
        "message": f"Hub {hub_id} intensity updated from {old_intensity} to {update_data.demand_intensity}",
        "hub": hub.model_dump()
    }
class InstructionRequest(BaseModel):
    instruction: str
class DisasterCreateRequest(BaseModel):
    disaster_type: str
    latitude: float
    longitude: float
    radius_km: float = 5.0
    affected_truck_id: Optional[str] = None
    affected_segment_start_idx: Optional[int] = None
    affected_segment_end_idx: Optional[int] = None
@app.post("/trucks/{truck_id}/instruction")
def send_instruction(truck_id: str, instruction_data: InstructionRequest):
    """
    Send a manual instruction to a specific truck.
    This instruction will be displayed in the driver's instruction panel.
    """
    truck = next((t for t in world_state.trucks if t.id == truck_id), None)
    if not truck:
        raise HTTPException(status_code=404, detail="Truck not found")
    truck.instructions = instruction_data.instruction
    truck.instruction_status = "ACTIVE"  
    world_state.ai_decisions.append(
        AIDecision(
            truck_id=truck_id,
            decision="INSTRUCTION_SENT",
            explanation=f"Manager sent instruction: {instruction_data.instruction}",
            timestamp=world_state.simulation_time
        )
    )
    return {
        "message": f"Instruction sent to truck {truck_id}",
        "instruction": instruction_data.instruction
    }
@app.post("/trucks/{truck_id}/acknowledge-instruction")
def acknowledge_instruction(truck_id: str):
    """
    Acknowledge the current instruction for a specific truck.
    This updates the instruction status to ACKNOWLEDGED.
    """
    truck = next((t for t in world_state.trucks if t.id == truck_id), None)
    if not truck:
        raise HTTPException(status_code=404, detail="Truck not found")
    if truck.instruction_status == "ACTIVE":
        truck.instruction_status = "ACKNOWLEDGED"
        truck.instructions = None
    return {
        "message": f"Instruction acknowledged for truck {truck_id}",
        "status": truck.instruction_status
    }
@app.delete("/hubs/{hub_id}")
def delete_hub(hub_id: str):
    """Delete a hub"""
    if hub_id == CENTRAL_HUB["id"]:
        raise HTTPException(status_code=400, detail="Central hub cannot be deleted")
    if world_state.simulation_running:
        raise HTTPException(status_code=400, detail="Cannot delete hubs after simulation start")
    hub = next((h for h in world_state.hubs if h.id == hub_id), None)
    if not hub:
        raise HTTPException(status_code=404, detail="Hub not found")
    for truck in world_state.trucks:
        if hub_id in truck.assigned_hubs:
            truck.assigned_hubs.remove(hub_id)
        if truck.assigned_hubs and truck.assigned_hubs[0] == hub_id:
            if len(truck.assigned_hubs) > 1:
                truck.assigned_hubs.pop(0)
            else:
                truck.assigned_hubs.clear()
                truck.status = "idle"
                truck.route.clear()
                truck.full_route.clear()
        if truck.current_task and truck.current_task.hub_id == hub_id:
            truck.current_task = None
        truck.future_task_queue = [task for task in truck.future_task_queue if task.hub_id != hub_id]
    world_state.hubs = [h for h in world_state.hubs if h.id != hub_id]
    return {"message": f"Hub {hub_id} deleted"}
@app.post("/disasters")
def create_disaster(request: DisasterCreateRequest):
    """
    Create a disaster at the specified location
    """
    if request.disaster_type not in ["rain", "traffic", "road_block"]:
        raise HTTPException(status_code=400, detail="Invalid disaster type. Use 'rain', 'traffic', or 'road_block'")
    if not world_state.simulation_running:
        raise HTTPException(status_code=400, detail="Simulation must be running to create disasters")
    disaster_id = f"{request.disaster_type}_{len(world_state.disasters) + 1}"
    snapped_lat = request.latitude
    snapped_lon = request.longitude
    affected_truck_id = request.affected_truck_id
    affected_segment_start_idx = request.affected_segment_start_idx
    affected_segment_end_idx = request.affected_segment_end_idx
    snapped_coordinates = None
    if request.disaster_type in ["traffic", "road_block"]:
        if (affected_truck_id is None or 
            affected_segment_start_idx is None or 
            affected_segment_end_idx is None):
            nearest_point = None
            min_distance = float('inf')
            nearest_truck_id = None
            nearest_segment_start_idx = None
            nearest_segment_end_idx = None
            for truck in world_state.trucks:
                route_points = truck.full_route if truck.full_route else truck.route
                if not route_points or len(route_points) < 2:
                    continue
                for i in range(len(route_points) - 1):
                    start_point = route_points[i]
                    end_point = route_points[i + 1]
                    distance, closest_lat, closest_lon = point_to_line_distance(
                        request.latitude, request.longitude,
                        start_point["latitude"], start_point["longitude"],
                        end_point["latitude"], end_point["longitude"]
                    )
                    if distance < min_distance:
                        min_distance = distance
                        nearest_point = (closest_lat, closest_lon)
                        nearest_truck_id = truck.id
                        nearest_segment_start_idx = i
                        nearest_segment_end_idx = i + 1
            threshold = 0.5  
            if nearest_point and min_distance <= threshold:
                snapped_lat, snapped_lon = nearest_point
                affected_truck_id = nearest_truck_id
                affected_segment_start_idx = nearest_segment_start_idx
                affected_segment_end_idx = nearest_segment_end_idx
                snapped_coordinates = {"latitude": snapped_lat, "longitude": snapped_lon}
            else:
                raise HTTPException(status_code=400, detail="Click directly on an active route (within 0.5km)")
    disaster = Disaster(
        id=disaster_id,
        disaster_type=request.disaster_type,
        latitude=request.latitude,
        longitude=request.longitude,
        radius_km=request.radius_km,
        created_at=world_state.simulation_time,
        affected_truck_id=affected_truck_id,
        affected_segment_start_idx=affected_segment_start_idx,
        affected_segment_end_idx=affected_segment_end_idx,
        snapped_coordinates=snapped_coordinates
    )
    world_state.disasters.append(disaster)
    if disaster.affected_truck_id:
        affected_truck = next((t for t in world_state.trucks if t.id == disaster.affected_truck_id), None)
        if affected_truck:
            affected_truck.requires_recalculation = True
    if disaster.disaster_type == DisasterType.RAIN:
        for truck in world_state.trucks:
            if truck.active:
                truck.requires_recalculation = True
    eta_impact_msg = ""
    if disaster.affected_truck_id:
        affected_truck = next((t for t in world_state.trucks if t.id == disaster.affected_truck_id), None)
        if affected_truck and affected_truck.current_task:
            hub = next((h for h in world_state.hubs if h.id == affected_truck.current_task.hub_id), None)
            if hub:
                route_points = affected_truck.full_route if affected_truck.full_route else affected_truck.route
                if route_points:
                    sim_time = world_state.simulation_time
                    sim_lat, sim_lon = affected_truck.current_latitude, affected_truck.current_longitude
                    curr_idx = affected_truck.current_route_index
                    for i in range(curr_idx, len(route_points) - 1):
                        sim_time += get_segment_time(
                            route_points[i]["latitude"], route_points[i]["longitude"],
                            route_points[i+1]["latitude"], route_points[i+1]["longitude"],
                            affected_truck.id, i
                        )
                    old_eta = hub.estimated_arrival_hours if hasattr(hub, 'estimated_arrival_hours') else sim_time
                    new_eta = sim_time
                    eta_increase = new_eta - old_eta
                    if eta_increase > 0.01:  
                        eta_impact_msg = f" ETA increased by {eta_increase:.2f}h (from {old_eta:.2f}h to {new_eta:.2f}h)."
    world_state.ai_decisions.append(
        AIDecision(
            truck_id="SYSTEM",
            decision=f"DISASTER_CREATED",
            explanation=f"{request.disaster_type.title()} disaster created at ({request.latitude}, {request.longitude}).{eta_impact_msg}",
            timestamp=world_state.simulation_time
        )
    )
    return {
        "message": f"{request.disaster_type} disaster created",
        "disaster": disaster.model_dump()
    }
@app.delete("/disasters/{disaster_id}")
def remove_disaster(disaster_id: str):
    """
    Remove a disaster by ID
    """
    initial_count = len(world_state.disasters)
    world_state.disasters = [d for d in world_state.disasters if d.id != disaster_id]
    if len(world_state.disasters) == initial_count:
        raise HTTPException(status_code=404, detail="Disaster not found")
    world_state.ai_decisions.append(
        AIDecision(
            truck_id="SYSTEM",
            decision="DISASTER_REMOVED",
            explanation=f"Disaster {disaster_id} removed",
            timestamp=world_state.simulation_time
        )
    )
    return {"message": f"Disaster {disaster_id} removed"}
class WeatherSensorCreate(BaseModel):
    latitude: float
    longitude: float
    radius_km: float = 10.0
    rain_intensity: float = 0.6
class TrafficSensorCreate(BaseModel):
    affected_truck_id: str
    segment_index: int
    congestion_factor: float = 0.5
@app.post("/sensors/weather")
def create_weather_sensor(request: WeatherSensorCreate):
    sensor_id = f"WS_{int(time.time())}"
    new_sensor = WeatherSensor(
        sensor_id=sensor_id,
        latitude=request.latitude,
        longitude=request.longitude,
        radius_km=request.radius_km,
        rain_intensity=request.rain_intensity,
        timestamp=world_state.simulation_time
    )
    world_state.active_sensors.append(new_sensor)
    for truck in world_state.trucks:
        if truck.active:
            truck.requires_recalculation = True
    world_state.ai_decisions.append(AIDecision(
        truck_id="SYSTEM",
        decision="WEATHER_SENSOR_ACTIVATED",
        explanation=f"Weather Sensor {sensor_id} deployed at ({request.latitude:.4f}, {request.longitude:.4f}). Radius: {request.radius_km}km, Intensity: {request.rain_intensity}",
        timestamp=world_state.simulation_time
    ))
    return {"message": "Weather sensor activated", "sensor": new_sensor}
@app.post("/sensors/traffic")
def create_traffic_sensor(request: TrafficSensorCreate):
    sensor_id = f"TS_{int(time.time())}"
    new_sensor = TrafficSensor(
        sensor_id=sensor_id,
        start_latitude=request.start_latitude,
        start_longitude=request.start_longitude,
        end_latitude=request.end_latitude,
        end_longitude=request.end_longitude,
        congestion_factor=request.congestion_factor,
        timestamp=world_state.simulation_time
    )
    world_state.active_sensors.append(new_sensor)
    
    # Recalculate routes for all active trucks since this is a global condition
    for truck in world_state.trucks:
        if truck.active:
            truck.requires_recalculation = True
            
    world_state.ai_decisions.append(AIDecision(
        truck_id="SYSTEM",
        decision="TRAFFIC_IMPACT_ADDED",
        explanation=f"Traffic Impact {sensor_id} detected on road segment. Congestion factor: {request.congestion_factor}",
        timestamp=world_state.simulation_time
    ))
    return {"message": "Traffic sensor activated", "sensor": new_sensor}
@app.delete("/sensors/{sensor_id}")
def remove_sensor(sensor_id: str):
    initial_count = len(world_state.active_sensors)
    world_state.active_sensors = [s for s in world_state.active_sensors if s.sensor_id != sensor_id]
    if len(world_state.active_sensors) < initial_count:
        for truck in world_state.trucks:
            truck.requires_recalculation = True
        return {"message": f"Sensor {sensor_id} removed"}
    raise HTTPException(status_code=404, detail="Sensor not found")
@app.get("/v1/models")
async def get_models():
    """Dummy endpoint to silence editor extensions"""
    return {"data": []}
@app.post("/trucks/{truck_id}/override-block")
def override_truck_block(truck_id: str, action: str):
    """
    Override a blocked truck's status
    Actions: 'clear_road', 'return_to_depot'
    """
    truck = next((t for t in world_state.trucks if t.id == truck_id), None)
    if not truck:
        return {"error": "Truck not found"}
    if truck.blocked_status != "BLOCKED_WAITING_OVERRIDE":
        return {"error": "Truck is not currently blocked"}
    if action == "clear_road":
        truck.blocked_status = None
        truck.status = "idle"  
        world_state.ai_decisions.append(
            AIDecision(
                truck_id=truck_id,
                decision="BLOCK_OVERRIDE_CLEAR_ROAD",
                explanation=f"Manager cleared road block for truck {truck_id}",
                timestamp=world_state.simulation_time
            )
        )
        return {"message": f"Road block cleared for truck {truck_id}"}
    elif action == "return_to_depot":
        truck.blocked_status = None
        truck.status = "returning"
        truck.route = get_road_route(
            truck.current_latitude,
            truck.current_longitude,
            CENTRAL_HUB["latitude"],
            CENTRAL_HUB["longitude"]
        )
        truck.full_route = truck.route.copy()
        truck.current_route_index = 0
        world_state.ai_decisions.append(
            AIDecision(
                truck_id=truck_id,
                decision="BLOCK_OVERRIDE_RETURN_TO_DEPOT",
                explanation=f"Manager forced truck {truck_id} to return to depot",
                timestamp=world_state.simulation_time
            )
        )
        return {"message": f"Truck {truck_id} returning to depot"}
    else:
        return {"error": "Invalid action. Use 'clear_road' or 'return_to_depot'"}
def fleet_optimized_assignment_algorithm():
    hubs_requiring_assignment = []
    for hub in world_state.hubs:
        if hub.id != CENTRAL_HUB["id"] and hub.demand_quantity > 0:
            hubs_requiring_assignment.append(hub)
    if not hubs_requiring_assignment:
        for truck in world_state.trucks:
            truck.route_plan.clear()
            truck.assigned_hubs.clear()
            truck.status = "idle"
            truck.future_task_queue = []
        world_state.simulation_phase = "committed"
        return True
    active_trucks = [t for t in world_state.trucks if t.active]
    if not active_trucks:
        return False
    for truck in world_state.trucks:
        if truck.active:
            truck.route_plan.clear()
            truck.assigned_hubs.clear()
            truck.completed_deliveries.clear()
            truck.status = "idle"
            truck.future_task_queue = []
    result = fleet_route_assignment_algorithm(
        hubs_requiring_assignment, 
        active_trucks, 
        CENTRAL_HUB["latitude"], 
        CENTRAL_HUB["longitude"]
    )
    assigned_routes = result["routes"]
    unassigned_hubs = result["unassigned_hubs"]
    for route_info in assigned_routes:
        truck_id = route_info["truck_id"]
        truck = next((t for t in active_trucks if t.id == truck_id), None)
        if truck:
            truck.active = True
            truck.future_task_queue = []
            for hub in route_info["route"]:
                task = Task(hub_id=hub.id, urgency_weight=0.0, assigned_at=world_state.simulation_time)
                truck.future_task_queue.append(task)
            for hub in route_info["route"]:
                hub_obj = next((h for h in world_state.hubs if h.id == hub.id), None)
                if hub_obj:
                    hub_obj.owner_truck_id = truck.id
                    hub_obj.ownership_state = HubOwnershipState.ASSIGNED
                    hub_obj.frozen_at_commit = True
    for unassign_info in unassigned_hubs:
        hub_obj = next((h for h in world_state.hubs if h.id == unassign_info["hub_id"]), None)
        if hub_obj:
            hub_obj.ownership_state = HubOwnershipState.UNASSIGNED
            hub_obj.owner_truck_id = None
            hub_obj.frozen_at_commit = False
    if not assigned_routes and hubs_requiring_assignment:
        return False
    world_state.initial_hubs_with_demand = [h.id for h in hubs_requiring_assignment]
    world_state.simulation_phase = "committed"
    return True
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
