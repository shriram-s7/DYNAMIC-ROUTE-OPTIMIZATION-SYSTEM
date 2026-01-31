from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import csv, io, math, time, os
import requests
from typing import List, Dict, Optional
from pydantic import BaseModel
from enum import Enum
from threading import Thread

app = FastAPI(title="Dynamic Route Optimization System")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =========================
# CONSTANT CENTRAL HUB
# =========================
CENTRAL_HUB = {
    "id": "CENTRAL_DEPOT",
    "name": "Trichy Central Depot",
    "latitude": 10.7905,
    "longitude": 78.7047,
    "demand_quantity": 0,
    "availability": 10000  # Effectively infinite availability
}

MAX_CLUSTER_DISTANCE = 300  # km
MAX_HUBS_PER_TRUCK = 5
FUEL_CONSUMPTION_RATE = 0.1  # L/km
MAX_DRIVING_TIME_HRS = 7.5  # Maximum driving hours until last delivery (return trip not counted)
TRUCK_ACTIVATION_PENALTY_LITERS = 8.0  # Represents depot → short route → depot overhead
ROADBLOCK_LOOKAHEAD_KM = 5.0  # driver sees roadblock ~5km ahead

# =========================
# HUB OWNERSHIP STATES
# =========================
# Each hub must be in exactly one state:
# - UNASSIGNED: No truck owns this hub, available for assignment
# - ASSIGNED: Owned by exactly one truck, guaranteed to be visited
# - COMPLETED: Delivery completed, no longer available

class HubOwnershipState:
    UNASSIGNED = "UNASSIGNED"
    ASSIGNED = "ASSIGNED"
    COMPLETED = "COMPLETED"

# =========================
# MODELS
# =========================
class Hub(BaseModel):
    id: str
    name: str
    latitude: float
    longitude: float
    demand_quantity: int
    availability: int = 100  # How much supply it can receive or send
    delivered: bool = False
    demand_intensity: str = "Medium"  # Low, Medium, High, Emergency - live mutable urgency
    distance_from_trichy_km: float = 0.0  # Distance from central hub in km
    deadline_hours: float = 7.5  # Deadline in hours from shift start
    
    # HUB OWNERSHIP MODEL (TWO-STAGE CONTRACT)
    ownership_state: str = "UNASSIGNED"  # UNASSIGNED, ASSIGNED, COMPLETED
    owner_truck_id: Optional[str] = None  # The truck that owns this hub (if ASSIGNED)
    
    # COMMIT PHASE TRACKING
    frozen_at_commit: bool = False  # True for hubs that existed at commit time
    # Frozen hubs CANNOT be claimed during execution - ownership was decided at commit
    
    # CLUSTER IDENTIFICATION
    cluster_id: Optional[str] = None  # Used for sector identification

class Task(BaseModel):
    """Represents a single delivery task"""
    hub_id: str
    urgency_weight: float = 0.0  # Calculated from demand_intensity
    assigned_at: float = 0.0  # Timestamp when task was assigned

class Truck(BaseModel):
    id: str
    starting_latitude: float
    starting_longitude: float
    fuel_capacity: float
    current_latitude: float
    current_longitude: float
    fuel_remaining: float
    cost_per_km: float = 2.0  # Cost per km default value
    max_deliveries: int = 100  # Maximum deliveries per route
    active: bool = True  # Whether this truck is available for assignment
    assigned_hubs: List[str] = []  # Legacy - kept for compatibility
    route_plan: List[str] = []  # Legacy - kept for compatibility
    completed_deliveries: List[str] = []
    
    # NEW: Task Queue System
    current_task: Optional[Task] = None
    future_task_queue: List[Task] = [] 
    
    route: List[Dict] = []
    full_route: List[Dict] = []
    current_route_index: int = 0
    speed: float = 50.0
    status: str = "idle"  # idle, moving, returning
    max_capacity: int = 100  # Maximum number of items the truck can carry
    fuel_efficiency: float = 1.0  # Fuel per km (L/km or whatever unit)
    current_fuel_used: float = 0.0  # Current fuel used in the trip
    last_decision_point: float = 0.0  # Timestamp of last decision point
    instructions: Optional[str] = None  # Manual instructions from manager
    instruction_status: Optional[str] = "ACTIVE"  # Instruction status: ACTIVE, ACKNOWLEDGED, CLEARED
    # Disaster-related fields
    disaster_notifications: List[str] = []  # Notifications about disasters
    blocked_status: Optional[str] = None  # Status when blocked by road block (BLOCKED_WAITING_OVERRIDE)
    
    # CLUSTER IDENTIFICATION
    cluster_id: Optional[str] = None  # Used for sector identification
    
    # MONOTONIC PATH TRACKING
    last_distance_from_depot: float = 0.0  # Track distance from depot to validate monotonic progression
    last_hub_visited: Optional[str] = None  # Track last hub visited for validation

class DisasterType(str, Enum):
    RAIN = "rain"
    TRAFFIC = "traffic"
    ROAD_BLOCK = "road_block"

class Disaster(BaseModel):
    id: str
    disaster_type: DisasterType
    latitude: float
    longitude: float
    radius_km: float = 5.0  # Default radius in km
    active: bool = True
    created_at: float = 0.0
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

class WorldState(BaseModel):
    hubs: List[Hub] = []
    trucks: List[Truck] = []
    ai_decisions: List[AIDecision] = []
    simulation_running: bool = False
    simulation_paused: bool = False  # New: Track paused state
    simulation_speed: float = 1.0  # New: Track simulation speed
    simulation_time: float = 0.0
    initial_hubs_with_demand: List[str] = []  # Hubs that existed at simulation start for completion tracking
    simulation_phase: str = "pre_start"  # pre_start, committed, executing
    hubs_frozen: bool = False  # True after simulation starts
    disasters: List[Disaster] = []  # Active disasters on the map

world_state = WorldState()
simulation_thread = None
# =========================
# INITIALIZE CENTRAL HUB IN WORLD STATE
# =========================
def initialize_central_hub():
    central_hub_model = Hub(
        id=CENTRAL_HUB["id"],
        name=CENTRAL_HUB["name"],
        latitude=CENTRAL_HUB["latitude"],
        longitude=CENTRAL_HUB["longitude"],
        demand_quantity=0,
        availability=CENTRAL_HUB["availability"],
        delivered=True,  # Always treated as completed
        demand_intensity="Low",
        deadline_hours=7.5,  # Central hub doesn't have delivery deadlines
        ownership_state=HubOwnershipState.COMPLETED,
        owner_truck_id=None,
        frozen_at_commit=True
    )
    world_state.hubs = [central_hub_model]

initialize_central_hub()

# =========================
# UTILS
# ========================= 
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
        # Line segment is actually a point
        closest_lat = line_start_lat
        closest_lon = line_start_lon
        distance = haversine(lat, lon, closest_lat, closest_lon)
        return distance, closest_lat, closest_lon
    
    # Calculate projection of point onto line
    t = max(0, min(1, (point_vec_x * line_vec_x + point_vec_y * line_vec_y) / line_len_sq))
    
    # Calculate closest point on the line segment
    closest_lon = line_start_lon + t * line_vec_x
    closest_lat = line_start_lat + t * line_vec_y
    
    # Calculate distance from point to closest point on line
    distance = haversine(lat, lon, closest_lat, closest_lon)
    
    return distance, closest_lat, closest_lon

# =========================
# OSRM ROAD-BASED ROUTING
# =========================
# Uses OSRM (Open Source Routing Machine) for real road-based routes
# Routes are fetched ONCE per destination assignment and NEVER recomputed while moving

OSRM_BASE_URL = "https://router.project-osrm.org"  # Public OSRM server

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
        # OSRM expects coordinates as longitude,latitude
        url = f"{OSRM_BASE_URL}/route/v1/driving/{lon1},{lat1};{lon2},{lat2}"
        params = {
            "overview": "full",       # Get full route geometry
            "geometries": "geojson",  # Return as GeoJSON
            "steps": "false"          # Don't need turn-by-turn instructions
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
        
        # Convert GeoJSON coordinates [lon, lat] to our format {latitude, longitude}
        coordinates = []
        for coord in geometry["coordinates"]:
            coordinates.append({
                "latitude": coord[1],  # lat is second in GeoJSON
                "longitude": coord[0]  # lon is first in GeoJSON
            })
        
        # Get route metrics
        distance_km = route["distance"] / 1000  # Convert meters to km
        duration_sec = route["duration"]  # Already in seconds
        
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
    # Calculate distance for fuel estimation
    distance_km = haversine(lat1, lon1, lat2, lon2)
    
    # Create interpolated route with more steps for smoother movement
    steps = max(20, int(distance_km * 2))  # More points for longer routes
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
        "duration_sec": distance_km / 50 * 3600,  # Assume 50 km/h average speed
        "success": False  # Indicate this is a fallback route
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

# =========================
# DECISION POINT SYSTEM (DEMAND-PRESSURE DRIVEN)
# =========================
# 
# DESIGN PRINCIPLES:
# 1. System is always active once initialized - no start/stop
# 2. Hubs are fixed infrastructure - cannot be added after initialization  
# 3. Demand slider (intensity) is the ONLY user interaction during runtime
# 4. Decisions happen ONLY at safe decision points:
#    - When truck completes a delivery
#    - When truck is idle at depot
# 5. While moving, truck destination is LOCKED - no mid-route changes
# 6. Local decisions per truck - no global replanning
# 7. Driver experience: stable, calm, predictable behavior
#
# DEMAND PRESSURE MODEL:
# - Urgency influences priority but does not force immediate response
# - Changes propagate at next safe decision point
# - Emergency increases urgency weight but does not override stability

def get_urgency_weight(intensity: str) -> float:
    """Convert demand intensity to numeric urgency weight"""
    weights = {
        "Low": 1.0,
        "Medium": 2.0,
        "High": 4.0,
        "Emergency": 10.0
    }
    return weights.get(intensity, 2.0)

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
    # While moving, destination is LOCKED - never a decision point
    if truck.status == "moving":
        return False
    
    if truck.status == "idle":
        return True
    
    # At central depot - safe decision point
    at_depot = (abs(truck.current_latitude - CENTRAL_HUB["latitude"]) < 0.01 and
                abs(truck.current_longitude - CENTRAL_HUB["longitude"]) < 0.01)
    return at_depot

# Legacy alias for compatibility
def is_decision_point(truck: Truck) -> bool:
    return is_at_safe_decision_point(truck)

def calculate_route_fuel_cost(truck: Truck, hub_ids: List[str]) -> float:
    """Calculate total fuel cost for a route sequence"""
    if not hub_ids:
        return 0.0
    
    total_distance = 0.0
    current_lat = truck.current_latitude
    current_lon = truck.current_longitude
    
    for hub_id in hub_ids:
        hub = next((h for h in world_state.hubs if h.id == hub_id), None)
        if hub:
            dist = haversine(current_lat, current_lon, hub.latitude, hub.longitude)
            total_distance += dist
            current_lat, current_lon = hub.latitude, hub.longitude
    
    return total_distance * FUEL_CONSUMPTION_RATE

def is_fuel_feasible(truck: Truck, additional_hub_ids: List[str]) -> bool:
    """Check if truck has enough fuel for additional route"""
    # Calculate fuel needed for current task + future queue + additional hubs
    all_hubs = []
    if truck.current_task:
        all_hubs.append(truck.current_task.hub_id)
    all_hubs.extend([task.hub_id for task in truck.future_task_queue])
    all_hubs.extend(additional_hub_ids)
    
    total_fuel_needed = calculate_route_fuel_cost(truck, all_hubs)
    return total_fuel_needed <= truck.fuel_remaining

# =========================
# HUB OWNERSHIP MANAGEMENT
# =========================
# These functions implement strict hub ownership rules:
# 1. Once a hub is ASSIGNED, only the owning truck may serve it
# 2. No hub stealing between trucks
# 3. Assignment represents a guaranteed commitment

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
    
    # Check if hub is available
    if hub.ownership_state == HubOwnershipState.ASSIGNED:
        if hub.owner_truck_id == truck_id:
            # Already owned by this truck - OK
            return True
        else:
            # Owned by another truck - VIOLATION
            print(f"[OWNERSHIP VIOLATION] Hub {hub_id} already assigned to {hub.owner_truck_id}, cannot assign to {truck_id}")
            return False
    
    if hub.ownership_state == HubOwnershipState.COMPLETED:
        print(f"[OWNERSHIP ERROR] Hub {hub_id} is already COMPLETED")
        return False
    
    # Assign the hub
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

def is_fuel_feasible_with_return(truck: Truck, hub: Hub) -> bool:
    """
    Check if truck has enough fuel to reach a hub AND return to depot.
    This is a HARD CONSTRAINT - no assignment may violate this.
    
    Fuel feasibility during route construction must be evaluated as:
      fuel_needed = sum(inter-hub distances) + distance(last_hub → depot)
    BUT depot return must be used ONLY as a feasibility check,
    NOT as a routing preference or scoring term.
    """
    dist_to_hub = haversine(truck.current_latitude, truck.current_longitude,
                            hub.latitude, hub.longitude)
    dist_to_depot = haversine(hub.latitude, hub.longitude,
                              CENTRAL_HUB["latitude"], CENTRAL_HUB["longitude"])
    total_fuel_needed = (dist_to_hub + dist_to_depot) * FUEL_CONSUMPTION_RATE
    
    return truck.fuel_remaining >= total_fuel_needed

def reorder_task_queue_at_decision_point(truck: Truck):
    """
    Safely reorder future_task_queue based on current urgency - only at decision points.
    
    OWNERSHIP RULE: Only reorders hubs that this truck OWNS.
    Demand changes may promote an assigned hub to be served earlier,
    but cannot cancel assignments or steal hubs.
    """
    if not is_at_safe_decision_point(truck):
        return  # Not at decision point - do nothing
    
    if not truck.future_task_queue:
        return  # No tasks to reorder
    
    # Verify all tasks are for hubs this truck owns
    valid_tasks = []
    for task in truck.future_task_queue:
        hub = next((h for h in world_state.hubs if h.id == task.hub_id), None)
        if hub and hub.ownership_state == HubOwnershipState.ASSIGNED and hub.owner_truck_id == truck.id:
            task.urgency_weight = get_urgency_weight(hub.demand_intensity)
            valid_tasks.append(task)
        else:
            # This task is for a hub we don't own - remove it
            print(f"[OWNERSHIP] Removing task for hub {task.hub_id} from truck {truck.id} queue - not owned")
    
    truck.future_task_queue = valid_tasks
    
    # Sort by urgency (descending) - Emergency first, then High, Medium, Low
    truck.future_task_queue.sort(key=lambda t: t.urgency_weight, reverse=True)
    
    # Verify fuel feasibility after reordering - this is a HARD CONSTRAINT
    if truck.future_task_queue:
        # Simulate route to check fuel
        hub_ids = [t.hub_id for t in truck.future_task_queue]
        if not is_fuel_feasible(truck, hub_ids):
            print(f"[FUEL WARNING] Truck {truck.id} route may exceed fuel capacity after reordering")

# =========================
# LOCAL DECISION MAKING (PER-TRUCK)
# =========================

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
    
    # Get urgency weight from demand_intensity (live slider value)
    urgency_weight = get_urgency_weight(hub.demand_intensity)
    
    # Calculate distance from current truck position to hub
    # This is a local distance cost, not related to depot
    distance_km = haversine(truck.current_latitude, truck.current_longitude, 
                            hub.latitude, hub.longitude)
    
    # Local distance penalty (per km) - this is acceptable as it's relative to truck position
    distance_cost = distance_km * 0.5  # 0.5 penalty per km
    
    # Final score calculation
    # Removed fuel_cost to comply with requirement to remove depot-related terms
    score = urgency_weight - distance_cost
    
    return score



def handle_upcoming_roadblock(truck: Truck, disaster: Disaster):
    # Try alternate route to SAME destination
    if not truck.current_task:
        # No current task, so just stop the truck
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

    hub = next(h for h in world_state.hubs if h.id == truck.current_task.hub_id)

    # Get a new route to the same destination (which should avoid the known roadblocks)
    new_route = get_road_route(
        truck.current_latitude,
        truck.current_longitude,
        hub.latitude,
        hub.longitude
    )
    
    # For now, we'll assume the new route is valid and use it
    truck.route = new_route
    truck.full_route = truck.route.copy()
    truck.current_route_index = 0

    world_state.ai_decisions.append(
        AIDecision(
            truck_id=truck.id,
            decision="REROUTED_AROUND_ROADBLOCK",
            explanation="Detected roadblock ahead; alternate route selected",
            timestamp=world_state.simulation_time
        )
    )
    return

def dispatch_next_committed_task(truck: Truck, set_moving_state: bool = True):
    if not truck.future_task_queue:
        truck.status = "idle"
        return

    next_task = truck.future_task_queue.pop(0)
    truck.current_task = next_task

    hub = next(h for h in world_state.hubs if h.id == next_task.hub_id)

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
    
    # CASE 1: Hub is already ASSIGNED
    if escalated_hub.ownership_state == HubOwnershipState.ASSIGNED:
        owner_truck_id = escalated_hub.owner_truck_id
        owner_truck = next((t for t in world_state.trucks if t.id == owner_truck_id), None)
        
        if owner_truck:
            print(f"[EMERGENCY] Hub {escalated_hub.name} escalated to {escalated_hub.demand_intensity}, "
                  f"owned by Truck {owner_truck_id} - reordering queue")
            
            # Reorder the owner's task queue to prioritize this hub
            # Only happens at decision points, otherwise just update urgency weight
            for task in owner_truck.future_task_queue:
                if task.hub_id == escalated_hub_id:
                    task.urgency_weight = urgency
            
            if is_at_safe_decision_point(owner_truck):
                reorder_task_queue_at_decision_point(owner_truck)
            
            world_state.ai_decisions.append(
                AIDecision(
                    truck_id=owner_truck_id,
                    decision="URGENCY_UPDATED",
                    explanation=f"Owned hub {escalated_hub.name} escalated to {escalated_hub.demand_intensity} - will be prioritized",
                    timestamp=world_state.simulation_time
                )
            )
        return
    
    # CASE 2: Hub is UNASSIGNED - find one truck to assign it to
    if escalated_hub.ownership_state != HubOwnershipState.UNASSIGNED:
        # Hub is COMPLETED or in invalid state
        return
    
    # EXECUTION RULE: Only NEW hubs (not frozen_at_commit) can be assigned during execution
    # Frozen hubs should have been assigned at commit - this is an error condition
    if escalated_hub.frozen_at_commit:
        print(f"[EXECUTION ERROR] Frozen hub {escalated_hub.name} is UNASSIGNED - this should not happen!")
        return
    
    print(f"[EMERGENCY] NEW unassigned hub {escalated_hub.name} escalated to {escalated_hub.demand_intensity} - finding truck")
    
    # Find the best eligible truck
    best_truck = None
    best_cost = float('inf')
    
    for truck in world_state.trucks:
        if not truck.active:
            continue
        
        # FUEL CONSTRAINT: Must be able to reach hub and return to depot
        if not is_fuel_feasible_with_return(truck, escalated_hub):
            continue
        
        # Calculate cost (distance + queue length penalty)
        dist_to_hub = haversine(truck.current_latitude, truck.current_longitude, 
                                escalated_hub.latitude, escalated_hub.longitude)
        cost = dist_to_hub + len(truck.future_task_queue) * 50
        
        # Prefer trucks at decision points (can act immediately)
        if not is_at_safe_decision_point(truck):
            cost += 100  # Penalty for moving trucks
        
        if cost < best_cost:
            best_cost = cost
            best_truck = truck
    
    # Assign to best truck with strict ownership
    if best_truck:
        # OWNERSHIP: Mark hub as ASSIGNED to this truck
        if not assign_hub_to_truck(escalated_hub_id, best_truck.id):
            print(f"[EMERGENCY FAILED] Could not assign hub {escalated_hub_id} to truck {best_truck.id}")
            return
        
        # Create task for the hub
        new_task = Task(
            hub_id=escalated_hub_id,
            urgency_weight=urgency,
            assigned_at=world_state.simulation_time
        )
        
        if best_truck.status == "idle" and not best_truck.current_task:
            # Truck is idle - make this the current task
            best_truck.current_task = new_task
        else:
            # Add to future queue and reorder (at decision point)
            best_truck.future_task_queue.append(new_task)
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

# =========================
# AI ASSIGNMENT (ENHANCED)
# =========================
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
    
    # Use the fleet-optimized assignment algorithm instead of corridor-based clustering
    return fleet_optimized_assignment_algorithm()

# =========================
# SIMULATION LOOP (DEMAND-PRESSURE DRIVEN)
# =========================
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
            time.sleep(0.2)  # Small sleep to prevent busy waiting when paused
            continue
        
        time.sleep(1 / world_state.simulation_speed)
        world_state.simulation_time += 1

        for truck in world_state.trucks:
            if not truck.active:
                continue
            
            # Add guard to skip blocked trucks in decision logic
            if truck.status == "blocked":
                continue

            # ========================================
            # STATE: IDLE (SAFE DECISION POINT)
            # ========================================
            if truck.status == "idle":
                truck.last_decision_point = world_state.simulation_time
                

                
                # AFTER COMMIT PHASE: Use pre-computed routes from fleet optimization
                # STRICT ROUTE FOLLOWING — NO LOCAL DECISIONS
                next_hub_id = None
                
                if world_state.simulation_phase in ("committed", "executing"):
                    # Only execute precomputed routes - no local hub selection allowed
                    if truck.future_task_queue:
                        # STRICT ROUTE FOLLOWING — NO LOCAL DECISIONS
                        # Use dispatcher to handle task assignment
                        dispatch_next_committed_task(truck, set_moving_state=True)
                        # After dispatch, get the hub ID from current task
                        if truck.current_task:
                            next_hub_id = truck.current_task.hub_id
                    # If no tasks in queue, truck will return to depot
                else:
                    # Before commit phase, allow local hub selection
                    if truck.future_task_queue:
                        # Pre-commit phase - use dispatcher but don't set moving state immediately
                        dispatch_next_committed_task(truck, set_moving_state=False)
                        # After dispatch, get the hub ID from current task
                        if truck.current_task:
                            next_hub_id = truck.current_task.hub_id
                    else:
                        # LOCAL DECISION: Pre-commit phase still needs hub selection
                        # However, we should follow similar principles to committed phase
                        # Look for available hubs in truck's cluster
                        available_hub_found = False
                        for hub in world_state.hubs:
                            if hub.id == CENTRAL_HUB["id"]:
                                continue
                            
                            # Check if hub is available for assignment
                            if not is_hub_available_for_assignment(hub):
                                continue
                            
                            # Skip frozen hubs - they should have been assigned at commit
                            if hub.frozen_at_commit:
                                continue
                            
                            # CLUSTER ALIGNMENT: Only consider hubs in the same cluster as the truck
                            if truck.cluster_id and hub.cluster_id and truck.cluster_id != hub.cluster_id:
                                continue
                            
                            # Check fuel feasibility
                            if not is_fuel_feasible_with_return(truck, hub):
                                continue
                            
                            # Assign this hub to the truck
                            if assign_hub_to_truck(hub.id, truck.id):
                                truck.current_task = Task(
                                    hub_id=hub.id,
                                    urgency_weight=0.0,
                                    assigned_at=world_state.simulation_time
                                )
                                available_hub_found = True
                                break
                        
                        # If no suitable hub found, truck remains idle
                
                # Start moving to selected hub
                if truck.current_task:
                    hub = next((h for h in world_state.hubs if h.id == truck.current_task.hub_id), None)
                    
                    if not hub or hub.demand_quantity <= 0:
                        truck.current_task = None
                        continue
                    
                    # LOCK destination - cannot be changed while moving
                    # FETCH ROAD ROUTE FROM OSRM (computed ONCE at destination assignment)
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
                            explanation=(
                                f"Moving to {hub.name} "
                                f"(Deadline: {hub.deadline_hours}h, "
                                f"Demand: {hub.demand_quantity}) - destination LOCKED"
                            ),
                            timestamp=world_state.simulation_time
                        )
                    )

            # ========================================
            # STATE: MOVING (DESTINATION LOCKED)
            # ========================================
            elif truck.status == "moving":
                # CRITICAL: Destination is LOCKED - no mid-route changes allowed
                if truck.current_route_index < len(truck.route):
                    p = truck.route[truck.current_route_index]
                    prev_lat = truck.current_latitude
                    prev_lon = truck.current_longitude
                    
                    truck.current_latitude = p["latitude"]
                    truck.current_longitude = p["longitude"]
                    truck.current_route_index += 1
                    
                    # Update fuel consumption
                    segment_dist = haversine(prev_lat, prev_lon, truck.current_latitude, truck.current_longitude)
                                
                    # Apply disaster effects to fuel consumption and speed
                    disaster_multiplier = 1.0
                    has_roadblock = False
                                        
                    # Check for upcoming roadblocks on the route
                    for disaster in world_state.disasters:
                        if not disaster.active:
                            continue
                        if disaster.disaster_type != DisasterType.ROAD_BLOCK:
                            continue

                        # Is this block on this truck's route?
                        if disaster.affected_segment_start_idx >= len(truck.full_route):
                            continue

                        # Is truck before or inside the blocked segment?
                        if truck.current_route_index <= disaster.affected_segment_end_idx:
                            dist_to_block = distance_along_route(
                                truck.full_route,
                                truck.current_route_index,
                                disaster.affected_segment_start_idx
                            )

                            if dist_to_block <= ROADBLOCK_LOOKAHEAD_KM:
                                handle_upcoming_roadblock(truck, disaster)
                                return

                        if disaster.active and disaster.contains_point(truck.current_latitude, truck.current_longitude):
                            if disaster.disaster_type == DisasterType.RAIN:
                                # RAIN (SOFT CONSTRAINT):
                                # - NEVER reroute
                                # - ONLY:
                                #     - increase ETA
                                #     - increase fuel consumption
                                # - Route geometry must remain unchanged
                                disaster_multiplier = 1.1  # ~10% slower
                                
                                # Add notification for rain
                                if "Rain zone ahead" not in (truck.disaster_notifications or []):
                                    truck.disaster_notifications.append("Rain zone ahead — ETA may increase")
                            elif disaster.disaster_type == DisasterType.TRAFFIC:
                                # TRAFFIC (SOFT-OPTIONAL CONSTRAINT):
                                # - Evaluate alternate OSRM route ONLY IF:
                                #     alt_eta <= current_eta * 1.05
                                # - If no such alternate exists:
                                #     - stay on current route
                                #     - increase ETA
                                # - Traffic must NEVER cause cluster change or depot return
                                if disaster.traffic_severity > 1.05:  # Only significant traffic
                                    # Check if alternate route is significantly better
                                    # In current implementation, we continue on current route but with reduced speed
                                    # For real implementation, we would calculate alt_eta using OSRM
                                    disaster_multiplier = disaster.traffic_severity
                                else:
                                    # Traffic not severe enough to justify rerouting
                                    disaster_multiplier = max(disaster_multiplier, disaster.traffic_severity)
                                
                                # Add notification for traffic
                                if "Traffic ahead" not in (truck.disaster_notifications or []):
                                    truck.disaster_notifications.append("Traffic ahead — continuing on current route")
                                        
                    # Only apply fuel consumption if not blocked by roadblock
                    if not has_roadblock:
                        fuel_used = segment_dist * FUEL_CONSUMPTION_RATE * disaster_multiplier
                        truck.fuel_remaining = max(0, truck.fuel_remaining - fuel_used)
                        truck.current_fuel_used += fuel_used
                        
                        # Check if fuel is critically low for next segment
                        # Depot return is allowed ONLY if:
                        # - fuel_remaining < fuel_needed_to_next_hub + safety_margin
                        if truck.fuel_remaining <= 0:
                            # Truck is out of fuel, must return to depot
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
                                    truck_id=truck.id,
                                    decision="FUEL_VIOLATION_RETURN",
                                    explanation="Out of fuel, returning to depot due to fuel hard constraint",
                                    timestamp=world_state.simulation_time
                                )
                            )
                                            
                        # Adjust speed based on disasters
                        effective_speed = truck.speed
                        if disaster_multiplier > 1.0:
                            effective_speed = truck.speed / disaster_multiplier
                else:
                    # ========================================
                    # ARRIVED AT HUB (SAFE DECISION POINT)
                    # ========================================
                    if not truck.current_task:
                        truck.status = "idle"
                        continue
                    
                    hub = next((h for h in world_state.hubs if h.id == truck.current_task.hub_id), None)
                    
                    if hub and hub.demand_quantity > 0:
                        # DELIVERY: Decrement demand
                        hub.demand_quantity = max(0, hub.demand_quantity - 1)
                        
                        # Mark as delivered and RELEASE OWNERSHIP if demand reaches 0
                        if hub.demand_quantity == 0:
                            release_hub_ownership(hub.id, mark_completed=True)
                        
                        world_state.ai_decisions.append(
                            AIDecision(
                                truck_id=truck.id,
                                decision="DELIVERED",
                                explanation=f"Delivered to {hub.name}. Remaining: {hub.demand_quantity}. Fuel: {truck.current_fuel_used:.1f}L",
                                timestamp=world_state.simulation_time
                            )
                        )
                    
                    # Unlock current task - now at decision point
                    completed_hub = hub
                    truck.current_task = None
                    
                    # Update monotonic path tracking
                    if completed_hub:
                        current_distance_from_depot = haversine(CENTRAL_HUB["latitude"], CENTRAL_HUB["longitude"], 
                                                              completed_hub.latitude, completed_hub.longitude)
                        # Validate monotonic progression: distance from depot should be non-decreasing
                        if truck.last_distance_from_depot > 0 and current_distance_from_depot < truck.last_distance_from_depot:
                            # Add validation log for non-monotonic movement
                            world_state.ai_decisions.append(
                                AIDecision(
                                    truck_id=truck.id,
                                    decision="MONOTONIC_VIOLATION",
                                    explanation=f"Non-monotonic movement detected: distance decreased from {truck.last_distance_from_depot:.2f}km to {current_distance_from_depot:.2f}km from depot",
                                    timestamp=world_state.simulation_time
                                )
                            )
                        
                        # Update tracking variables
                        truck.last_distance_from_depot = current_distance_from_depot
                        truck.last_hub_visited = completed_hub.id
                        
                        # SANITY ASSERTION: After delivery, current task should be None
                        # and all tasks in future queue should belong to this truck
                        if world_state.simulation_phase in ("committed", "executing"):
                            assert truck.current_task is None
                            assert all(
                                next((h for h in world_state.hubs if h.id == t.hub_id), None).owner_truck_id == truck.id
                                for t in truck.future_task_queue
                            )
                    
                    # AFTER COMMIT PHASE: Only execute pre-computed routes from fleet optimization
                    # DISABLE: any logic that compares marginal_cost vs depot_cost
                    # LOCAL DECISION: No route extension allowed after commit
                    next_hub_id = None
                    
                    if world_state.simulation_phase in ("committed", "executing"):
                        # AFTER DELIVERY — COMMITTED MODE
                        dispatch_next_committed_task(truck)
                        continue
                    else:
                            # Before commit phase, allow route extension
                            if completed_hub:
                                # EXTENSION LOGIC: Check if we can efficiently extend route after delivery
                                # Only consider hubs in the same cluster as the truck
                                next_hub_id = None
                                
                                # Check if we own any other hubs first
                                owned_hubs = get_truck_owned_hubs(truck.id)
                                if owned_hubs:
                                    # Find the best owned hub to extend to
                                    best_owned = None
                                    best_score = float('-inf')
                                    
                                    for hub_id in owned_hubs:
                                        hub = next((h for h in world_state.hubs if h.id == hub_id), None)
                                        if hub and hub.demand_quantity > 0 and not hub.delivered:
                                            if is_fuel_feasible_with_return(truck, hub):
                                                score = calculate_hub_score(truck, hub)
                                                if score > best_score:
                                                    best_score = score
                                                    best_owned = hub_id
                                    
                                    if best_owned:
                                        next_hub_id = best_owned
                                
                                # If no owned hubs suitable, check for nearby UNASSIGNED hubs
                                if not next_hub_id:
                                    # Find nearby UNASSIGNED hubs for efficient extension
                                    nearby_hubs = []
                                    
                                    for hub in world_state.hubs:
                                        # Only consider UNASSIGNED hubs
                                        if not is_hub_available_for_assignment(hub):
                                            continue
                                        
                                        # Skip frozen hubs - they should have been assigned at commit
                                        if hub.frozen_at_commit:
                                            continue
                                        
                                        # CLUSTER ALIGNMENT: Only consider hubs in the same cluster as the truck
                                        if truck.cluster_id and hub.cluster_id and truck.cluster_id != hub.cluster_id:
                                            continue
                                        
                                        # Check fuel feasibility
                                        if not is_fuel_feasible_with_return(truck, hub):
                                            continue
                                        
                                        dist_to_hub = haversine(truck.current_latitude, truck.current_longitude,
                                                                hub.latitude, hub.longitude)
                                        dist_hub_to_depot = haversine(hub.latitude, hub.longitude,
                                                                      CENTRAL_HUB["latitude"], CENTRAL_HUB["longitude"])
                                        
                                        # Prefer extending route if marginal cost is less than new truck cost
                                        marginal_cost = dist_to_hub
                                        new_truck_cost = dist_hub_to_depot
                                        
                                        if marginal_cost < new_truck_cost * 0.8:  # 20% margin for preference
                                            score = calculate_hub_score(truck, hub)
                                            nearby_hubs.append((hub.id, score, dist_to_hub))
                                    
                                    if nearby_hubs:
                                        # Sort by score and select best nearby hub
                                        nearby_hubs.sort(key=lambda x: x[1], reverse=True)
                                        best_hub_id, _, _ = nearby_hubs[0]
                                        
                                        # Claim the hub before returning
                                        if assign_hub_to_truck(best_hub_id, truck.id):
                                            next_hub_id = best_hub_id
                            
                            if next_hub_id:
                                # Extend route to nearby hub
                                next_hub = next((h for h in world_state.hubs if h.id == next_hub_id), None)
                                if next_hub:
                                    truck.current_task = Task(
                                        hub_id=next_hub_id,
                                        urgency_weight=get_urgency_weight(next_hub.demand_intensity),
                                        assigned_at=world_state.simulation_time
                                    )
                                    truck.status = "idle"  # Will process in next tick
                                    world_state.ai_decisions.append(
                                        AIDecision(
                                            truck_id=truck.id,
                                            decision="EXTEND_ROUTE",
                                            explanation=f"Extending route to {next_hub.name} (efficient extension)",
                                            timestamp=world_state.simulation_time
                                        )
                                    )
                            elif truck.future_task_queue:
                                # More tasks in queue - continue
                                truck.status = "idle"
                            else:
                                # No efficient extension, no more tasks - truck becomes idle
                                truck.status = "idle"
                                
                                world_state.ai_decisions.append(
                                    AIDecision(
                                        truck_id=truck.id,
                                        decision="ROUTE_COMPLETED",
                                        explanation="No more tasks in queue, awaiting manager instructions",
                                        timestamp=world_state.simulation_time
                                    )
                                )
            
            # ========================================
            # STATE: RETURNING TO DEPOT
            # ========================================
            elif truck.status == "returning":
                if truck.current_route_index < len(truck.route):
                    p = truck.route[truck.current_route_index]
                    prev_lat = truck.current_latitude
                    prev_lon = truck.current_longitude
                                
                    truck.current_latitude = p["latitude"]
                    truck.current_longitude = p["longitude"]
                    truck.current_route_index += 1
                                
                    # Update fuel consumption
                    segment_dist = haversine(prev_lat, prev_lon, truck.current_latitude, truck.current_longitude)
                                
                    # Apply disaster effects to fuel consumption and speed
                    disaster_multiplier = 1.0
                    has_roadblock = False
                    
                    for disaster in world_state.disasters:
                        if disaster.active:
                            # For route-based disasters, check if truck is on the affected route segment
                            if disaster.disaster_type in [DisasterType.TRAFFIC, DisasterType.ROAD_BLOCK]:
                                # Check if this truck is on the affected route
                                if disaster.affected_route_id == truck.id:
                                    # Check if the truck is currently on the affected segment
                                    if (disaster.affected_segment_start_idx is not None and 
                                        disaster.affected_segment_end_idx is not None and
                                        len(truck.full_route) > disaster.affected_segment_end_idx):
            
                                        # Get the start and end points of the affected segment
                                        start_point = truck.full_route[disaster.affected_segment_start_idx]
                                        end_point = truck.full_route[disaster.affected_segment_end_idx]
            
                                        # Check if truck is between these two points on the route
                                        # For now, we'll use the contains_point method which checks if the truck is within radius of the disaster center
                                        # But for route-based disasters, we can also check if truck is on the route segment
                                        is_on_affected_segment = disaster.contains_point(truck.current_latitude, truck.current_longitude)
            
                                        if is_on_affected_segment:
                                            if disaster.disaster_type == DisasterType.RAIN:
                                                # RAIN (SOFT CONSTRAINT):
                                                # - NEVER reroute
                                                # - ONLY:
                                                #     - increase ETA
                                                #     - increase fuel consumption
                                                # - Route geometry must remain unchanged
                                                disaster_multiplier = 1.1  # ~10% slower

                                                # Add notification for rain
                                                if "Rain zone ahead" not in (truck.disaster_notifications or []):
                                                    truck.disaster_notifications.append("Rain zone ahead — ETA may increase")
                                            elif disaster.disaster_type == DisasterType.TRAFFIC:
                                                # TRAFFIC (SOFT-OPTIONAL CONSTRAINT):
                                                # - Evaluate alternate OSRM route ONLY IF:
                                                #     alt_eta <= current_eta * 1.05
                                                # - If no such alternate exists:
                                                #     - stay on current route
                                                #     - increase ETA
                                                # - Traffic must NEVER cause cluster change or depot return
                                                if disaster.traffic_severity > 1.05:  # Only significant traffic
                                                    # Check if alternate route is significantly better
                                                    # In current implementation, we continue on current route but with reduced speed
                                                    # For real implementation, we would calculate alt_eta using OSRM
                                                    disaster_multiplier = disaster.traffic_severity
                                                else:
                                                    # Traffic not severe enough to justify rerouting
                                                    disaster_multiplier = max(disaster_multiplier, disaster.traffic_severity)

                                                # Validate that traffic does not cause cluster change
                                                # Traffic must NEVER cause cluster change
                                                if truck.current_task:
                                                    next_hub = next((h for h in world_state.hubs if h.id == truck.current_task.hub_id), None)
                                                    if next_hub and truck.cluster_id and next_hub.cluster_id and truck.cluster_id != next_hub.cluster_id:
                                                        # Add validation log for cluster violation caused by traffic
                                                        world_state.ai_decisions.append(
                                                            AIDecision(
                                                                truck_id=truck.id,
                                                                decision="TRAFFIC_CLUSTER_VIOLATION",
                                                                explanation=f"Traffic causing movement to different cluster (truck: {truck.cluster_id}, next_hub: {next_hub.cluster_id})",
                                                                timestamp=world_state.simulation_time
                                                            )
                                                        )

                                                # Add notification for traffic
                                                if "Traffic ahead" not in (truck.disaster_notifications or []):
                                                    truck.disaster_notifications.append("Traffic ahead — continuing on current route")
                                            elif disaster.disaster_type == DisasterType.ROAD_BLOCK:
                                                # ROAD BLOCK (HARD CONSTRAINT):
                                                # - If roadblock intersects current route:
                                                #     - attempt reroute to SAME target hub via OSRM
                                                #     - IF reroute fails:
                                                #          stop truck
                                                #          set status = BLOCKED_WAITING_OVERRIDE
                                                #          preserve current_task and route index
                                                # - NEVER auto-return to depot on roadblock
                                                has_roadblock = True

                                                # Add notification for road block
                                                if "Road blocked" not in (truck.disaster_notifications or []):
                                                    truck.disaster_notifications.append("Road blocked — waiting for instructions")

                                                # Set truck to blocked status but preserve route and task
                                                truck.blocked_status = "BLOCKED_WAITING_OVERRIDE"
                                                truck.status = "blocked"

                                                # Add AI decision to notify manager
                                                world_state.ai_decisions.append(
                                                    AIDecision(
                                                        truck_id=truck.id,
                                                        decision="TRUCK_BLOCKED_BY_ROAD_BLOCK",
                                                        explanation=f"Truck {truck.id} blocked by road block at ({disaster.latitude}, {disaster.longitude}). Awaiting manager override.",
                                                        timestamp=world_state.simulation_time
                                                    )
                                                )

                                                # Break the loop since we need to stop
                                                break
                            else:
                                # For non-route disasters (like rain), check if point is within radius
                                if disaster.contains_point(truck.current_latitude, truck.current_longitude):
                                    if disaster.disaster_type == DisasterType.RAIN:
                                        # RAIN (SOFT CONSTRAINT):
                                        # - NEVER reroute
                                        # - ONLY:
                                        #     - increase ETA
                                        #     - increase fuel consumption
                                        # - Route geometry must remain unchanged
                                        disaster_multiplier = 1.1  # ~10% slower

                                        # Validate that rain does not cause cluster change
                                        # Rain must NEVER cause cluster change
                                        if truck.current_task:
                                            next_hub = next((h for h in world_state.hubs if h.id == truck.current_task.hub_id), None)
                                            if next_hub and truck.cluster_id and next_hub.cluster_id and truck.cluster_id != next_hub.cluster_id:
                                                # Add validation log for cluster violation caused by rain
                                                world_state.ai_decisions.append(
                                                    AIDecision(
                                                        truck_id=truck.id,
                                                        decision="RAIN_CLUSTER_VIOLATION",
                                                        explanation=f"Rain causing movement to different cluster (truck: {truck.cluster_id}, next_hub: {next_hub.cluster_id})",
                                                        timestamp=world_state.simulation_time
                                                    )
                                                )

                                        # Add notification for rain
                                        if "Rain zone ahead" not in (truck.disaster_notifications or []):
                                            truck.disaster_notifications.append("Rain zone ahead — ETA may increase")
                    
                    # Only apply fuel consumption if not blocked by roadblock
                    if not has_roadblock:
                        fuel_used = segment_dist * FUEL_CONSUMPTION_RATE * disaster_multiplier
                        truck.fuel_remaining = max(0, truck.fuel_remaining - fuel_used)
                        
                        # Check if fuel is critically low for next segment
                        # Depot return is allowed ONLY if:
                        # - fuel_remaining < fuel_needed_to_next_hub + safety_margin
                        if truck.fuel_remaining <= 0:
                            # Truck is out of fuel, must return to depot
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
                                    truck_id=truck.id,
                                    decision="FUEL_VIOLATION_RETURN",
                                    explanation="Out of fuel, returning to depot due to fuel hard constraint",
                                    timestamp=world_state.simulation_time
                                )
                            )
                else:
                    # ARRIVED AT DEPOT (SAFE DECISION POINT)
                    truck.current_latitude = CENTRAL_HUB["latitude"]
                    truck.current_longitude = CENTRAL_HUB["longitude"]
                    
                    # Refuel and reset
                    truck.fuel_remaining = truck.fuel_capacity
                    truck.current_fuel_used = 0.0
                    
                    truck.route.clear()
                    truck.full_route.clear()
                    truck.current_route_index = 0
                    
                    # Preserve cluster assignment - only change status after processing
                    truck.status = "idle"
                    
                    # Log truck arrival at depot
                    world_state.ai_decisions.append(
                        AIDecision(
                            truck_id=truck.id,
                            decision="ARRIVED_AT_DEPOT",
                            explanation="Truck arrived at depot and is now idle, awaiting instructions",
                            timestamp=world_state.simulation_time
                        )
                    )

# =========================
# API
# =========================


@app.post("/upload/hubs")
async def upload_hubs(file: UploadFile = File(...)):
    text = (await file.read()).decode()
    reader = csv.DictReader(io.StringIO(text))

    # Clear existing non-central hubs
    world_state.hubs = [h for h in world_state.hubs if h.id == CENTRAL_HUB["id"]]

    for row in reader:
        # Compute haversine distance from Trichy (central hub)
        distance_from_trichy = haversine(CENTRAL_HUB["latitude"], CENTRAL_HUB["longitude"], float(row["latitude"]), float(row["longitude"]))
        
        # If distance > 220 km, skip this hub
        if distance_from_trichy > 220:
            continue  # Skip this hub if outside radius
        
        hub = Hub(
            id=row["id"],
            name=row["name"],
            latitude=float(row["latitude"]),
            longitude=float(row["longitude"]),
            demand_quantity=int(row["demand_quantity"]),
            availability=int(row.get("availability", 20)),
            delivered=False,
            demand_intensity=row.get("demand_intensity", "Medium"),
            deadline_hours=float(row.get("deadline_hours", 7.5)),  # Default to 7.5 if not provided
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
            cost_per_km=float(row.get("cost_per_km", 2.0)),  # Use value from CSV or default
            max_deliveries=int(row.get("max_deliveries", 100)),  # Optional, default high
            active=row.get("active", "true").lower() == "true",  # Convert string to boolean
            max_capacity=int(row.get("max_capacity", 100)),  # New field from CSV or default
            fuel_efficiency=float(row.get("fuel_efficiency", 1.0)),  # New field from CSV or default
            current_fuel_used=float(row.get("current_fuel_used", 0.0)),  # New field from CSV or default
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
    # Freeze hubs - no new hubs can be added after this
    world_state.hubs_frozen = True
    world_state.simulation_phase = "committing"
    
    # ===========================================
    # COMMIT PHASE: Assign feasible hubs to trucks
    # ===========================================
    commit_success = assign_hubs_to_trucks()
    
    if not commit_success:
        # COMMIT FAILED: Check if it's due to no trucks
        active_trucks_count = len([t for t in world_state.trucks if t.active])
        if active_trucks_count == 0:
            # Revert to pre_start state and block simulation
            world_state.hubs_frozen = False
            world_state.simulation_phase = "pre_start"
            
            # Clear any partial assignments
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
            # COMMIT SUCCEEDED: Even if some hubs are unassigned due to constraints
            # This is allowed according to the optimization goal
            # Unassigned hubs are marked with a clear reason
            pass  # Continue with execution since some routes were created
    
    # COMMIT SUCCESS: All feasible hubs are assigned and frozen
    world_state.simulation_phase = "committed"
    


    world_state.simulation_running = True
    world_state.simulation_phase = "executing"
    
    global simulation_thread
    simulation_thread = Thread(target=simulation_loop, daemon=True)
    simulation_thread.start()
    
    # Count assigned and unassigned hubs
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
    world_state.simulation_paused = False  # Ensure paused state is reset
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

@app.get("/state")
def get_state():
    return world_state.model_dump()

@app.post("/disruptions/{disruption_type}")
def toggle_disruption(disruption_type: str, active: bool = True):
    """Toggle disruption (placeholder - can be extended later)"""
    # For now, just acknowledge - can add disruption logic later
    return {"message": f"Disruption {disruption_type} set to {active}"}

# =========================
# LIVE HUB MANAGEMENT
# =========================
class HubCreateRequest(BaseModel):
    name: str
    latitude: float
    longitude: float
    demand_quantity: int
    availability: int = 20

class HubUpdateRequest(BaseModel):
    demand_quantity: int

@app.post("/hubs/manual")
async def create_hub_manual(hub_data: HubCreateRequest):
    """Create a new hub manually at runtime"""
    # Generate unique hub ID (LIVE_1, LIVE_2, etc.)
    existing_ids = {h.id for h in world_state.hubs}
    live_counter = 1
    hub_id = f"LIVE_{live_counter}"
    while hub_id in existing_ids:
        live_counter += 1
        hub_id = f"LIVE_{live_counter}"
    
    # Check if hubs are frozen (simulation has started)
    if world_state.hubs_frozen:
        raise HTTPException(status_code=400, detail="Cannot add hubs after simulation has started. Hubs are frozen.")
    
    # Compute haversine distance from Trichy (central hub)
    distance_from_trichy = haversine(CENTRAL_HUB["latitude"], CENTRAL_HUB["longitude"], hub_data.latitude, hub_data.longitude)
    
    # If distance > 220 km, reject creation
    if distance_from_trichy > 220:
        raise HTTPException(status_code=400, detail="Hub outside 220 km service radius")
    
    # Create new hub
    new_hub = Hub(
        id=hub_id,
        name=hub_data.name,
        latitude=hub_data.latitude,
        longitude=hub_data.longitude,
        demand_quantity=hub_data.demand_quantity,
        availability=hub_data.availability if hasattr(hub_data, 'availability') else 20,
        delivered=False,
        demand_intensity="Medium",  # Default intensity
        deadline_hours=7.5,  # Default deadline
        distance_from_trichy_km=distance_from_trichy  # Store distance from Trichy
    )
    
    # Add to hubs list (after central hub if it exists)
    if world_state.hubs and world_state.hubs[0].id == CENTRAL_HUB["id"]:
        world_state.hubs.insert(1, new_hub)
    else:
        world_state.hubs.append(new_hub)
    
    return {"message": f"Hub {hub_id} created", "hub": new_hub.model_dump(), "total_hubs": len(world_state.hubs)}

@app.post("/hubs/random")
async def create_random_hubs():  # Name kept for compatibility but creates fixed hubs
    """Create 3 fixed deterministic hubs and clear existing non-central hubs"""
    # Clear all non-central hubs
    world_state.hubs = [h for h in world_state.hubs if h.id == CENTRAL_HUB["id"]]
    
    # Create fixed, deterministic hubs for testing
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
                        "name": "Virudhunagar",
                        "latitude": 9.5851,
                        "longitude": 77.9579,
                        "demand_quantity": 1,
                        "availability": 20,
                        "demand_intensity": "Medium",
                        "deadline_hours": 7
                    },
                    {
                        "id": "H9",
                        "name": "Salem",
                        "latitude": 11.6643,
                        "longitude": 78.1460,
                        "demand_quantity": 1,
                        "availability": 20,
                        "demand_intensity": "High",
                        "deadline_hours": 7
                    },
                    {
                        "id": "H10",
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
        # Compute haversine distance from Trichy (central hub)
        distance_from_trichy = haversine(CENTRAL_HUB["latitude"], CENTRAL_HUB["longitude"], hub_data["latitude"], hub_data["longitude"])
        
        # If distance > 220 km, reject creation
        if distance_from_trichy > 220:
            continue  # Skip this hub if outside radius
        
        # Add the distance to the hub data
        hub_data["distance_from_trichy_km"] = distance_from_trichy
        hub = Hub(**hub_data)
        world_state.hubs.append(hub)
    
    # If simulation is running, do NOT reassign routes
    # New hubs are added to pending queue for next simulation run
    if world_state.simulation_running:
        print(f"[INFO] Fixed hubs created during simulation. Will be included in next simulation run.")
    
    return {"message": "4 fixed hubs created", "total_hubs": len(world_state.hubs)}

@app.put("/hubs/{hub_id}/demand")
def update_hub_demand(hub_id: str, update_data: HubUpdateRequest):
    """Update hub demand quantity"""
    if hub_id == CENTRAL_HUB["id"]:
        raise HTTPException(status_code=400, detail="Cannot modify central hub")
    
    hub = next((h for h in world_state.hubs if h.id == hub_id), None)
    if not hub:
        raise HTTPException(status_code=404, detail="Hub not found")
    
    hub.demand_quantity = update_data.demand_quantity
    
    # If simulation is running, trucks will pick up changes in next assignment cycle
    # Remove hub from truck assignments if it's no longer needed
    if hub.demand_quantity <= 0:
        hub.delivered = True
        # Remove from any truck's assigned_hubs list
        for truck in world_state.trucks:
            if hub_id in truck.assigned_hubs:
                truck.assigned_hubs.remove(hub_id)
    
    return {"message": f"Hub {hub_id} updated", "hub": hub.model_dump()}

class DemandIntensityUpdate(BaseModel):
    demand_intensity: str  # Low, Medium, High, Emergency

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
    
    # If intensity escalated and simulation is running, handle escalation
    if world_state.simulation_running:
        old_weight = get_urgency_weight(old_intensity)
        new_weight = get_urgency_weight(update_data.demand_intensity)
        
        if new_weight > old_weight:
            # Demand escalated - trigger intelligent assignment
            handle_demand_escalation(hub_id)
        
        # Update urgency weights in all task queues
        for truck in world_state.trucks:
            # Update urgency in future queue
            for task in truck.future_task_queue:
                if task.hub_id == hub_id:
                    task.urgency_weight = new_weight
            
            # Reorder at decision points only
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
    # For route-based disasters
    # NOTE: affected_route_id has been removed as roadblocks affect route geometry, not truck assignment
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
    
    # Add the instruction to the truck's data for display in the driver view
    # We'll store it in a temporary field that will be included in the state
    truck.instructions = instruction_data.instruction
    truck.instruction_status = "ACTIVE"  # Set status to ACTIVE when sending
    
    # Add to AI decisions for visibility in the UI
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
    
    # Update the instruction status to ACKNOWLEDGED
    if truck.instruction_status == "ACTIVE":
        truck.instruction_status = "ACKNOWLEDGED"
        # Clear the instruction text as it's been acknowledged
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
    
    # Check if simulation has started
    if world_state.simulation_running:
        raise HTTPException(status_code=400, detail="Cannot delete hubs after simulation start")
    
    hub = next((h for h in world_state.hubs if h.id == hub_id), None)
    if not hub:
        raise HTTPException(status_code=404, detail="Hub not found")
    
    # Remove from truck assignments
    for truck in world_state.trucks:
        if hub_id in truck.assigned_hubs:
            truck.assigned_hubs.remove(hub_id)
        # If truck is currently moving to this hub, stop and reset
        if truck.assigned_hubs and truck.assigned_hubs[0] == hub_id:
            # Skip to next hub or go idle
            if len(truck.assigned_hubs) > 1:
                truck.assigned_hubs.pop(0)
            else:
                truck.assigned_hubs.clear()
                truck.status = "idle"
                truck.route.clear()
                truck.full_route.clear()
        
        # Clean up any references in task queues
        if truck.current_task and truck.current_task.hub_id == hub_id:
            truck.current_task = None
        
        # Remove hub from future task queue
        truck.future_task_queue = [task for task in truck.future_task_queue if task.hub_id != hub_id]
    
    # Remove hub from list
    world_state.hubs = [h for h in world_state.hubs if h.id != hub_id]
    
    return {"message": f"Hub {hub_id} deleted"}


@app.post("/disasters")
def create_disaster(request: DisasterCreateRequest):
    """
    Create a disaster at the specified location
    """
    if request.disaster_type not in ["rain", "traffic", "road_block"]:
        raise HTTPException(status_code=400, detail="Invalid disaster type. Use 'rain', 'traffic', or 'road_block'")
    
    # Check if simulation has started
    if not world_state.simulation_running:
        raise HTTPException(status_code=400, detail="Simulation must be running to create disasters")
    
    disaster_id = f"{request.disaster_type}_{len(world_state.disasters) + 1}"
    
    # For traffic and roadblock disasters, implement snapping logic
    snapped_lat = request.latitude
    snapped_lon = request.longitude
    affected_segment_start_idx = None
    affected_segment_end_idx = None
    snapped_coordinates = None
    
    if request.disaster_type in ["traffic", "road_block"]:
        # If route segment information is provided, use it directly
        if (request.affected_segment_start_idx is not None and 
            request.affected_segment_end_idx is not None):
            # Use provided route segment information
            affected_segment_start_idx = request.affected_segment_start_idx
            affected_segment_end_idx = request.affected_segment_end_idx
            snapped_coordinates = {"latitude": snapped_lat, "longitude": snapped_lon}
        else:
            # Find nearest active route segment
            nearest_point = None
            min_distance = float('inf')
            nearest_segment_start_idx = None
            nearest_segment_end_idx = None
            
            for truck in world_state.trucks:
                # Prefer full_route over route when available
                route_points = truck.full_route if truck.full_route else truck.route
                
                if not route_points or len(route_points) < 2:
                    continue
                
                # Check each segment of the route
                for i in range(len(route_points) - 1):
                    start_point = route_points[i]
                    end_point = route_points[i + 1]
                    
                    # Calculate distance from clicked point to this segment
                    distance, closest_lat, closest_lon = point_to_line_distance(
                        request.latitude, request.longitude,
                        start_point["latitude"], start_point["longitude"],
                        end_point["latitude"], end_point["longitude"]
                    )
                    
                    if distance < min_distance:
                        min_distance = distance
                        nearest_point = (closest_lat, closest_lon)
                        nearest_segment_start_idx = i
                        nearest_segment_end_idx = i + 1
            
            # Distance threshold for snapping (in km)
            threshold = 1.0  # 1.0 km
            
            if nearest_point and min_distance <= threshold:
                snapped_lat, snapped_lon = nearest_point
                affected_segment_start_idx = nearest_segment_start_idx
                affected_segment_end_idx = nearest_segment_end_idx
                snapped_coordinates = {"latitude": snapped_lat, "longitude": snapped_lon}
            else:
                # No route within threshold - reject placement
                raise HTTPException(status_code=400, detail="Click directly on an active route")
    
    disaster = Disaster(
        id=disaster_id,
        disaster_type=request.disaster_type,
        latitude=request.latitude,
        longitude=request.longitude,
        radius_km=request.radius_km,
        created_at=world_state.simulation_time,
        affected_segment_start_idx=affected_segment_start_idx,
        affected_segment_end_idx=affected_segment_end_idx,
        snapped_coordinates=snapped_coordinates
    )
    
    world_state.disasters.append(disaster)
    
    # Add AI decision to notify managers
    world_state.ai_decisions.append(
        AIDecision(
            truck_id="SYSTEM",
            decision=f"DISASTER_CREATED",
            explanation=f"{request.disaster_type.title()} disaster created at ({request.latitude}, {request.longitude})",
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
        # Clear the block status and allow truck to continue
        truck.blocked_status = None
        truck.status = "idle"  # Reset to idle to allow new route assignment
        
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
        
# FLEET-LEVEL DIRECTIONAL LOGISTICS OPTIMIZATION ALGORITHM
# Implementation of the sector-based routing algorithm to eliminate zig-zag patterns
# and optimize fleet-wide fuel consumption

def compute_polar_coordinates():
    """
    Canonical transformation: Convert hubs to polar space.
    
    For each hub i:
    r_i  = distance(depot → hub)   [km]
    θ_i  = bearing angle (0–360°)
    t_i  = r_i / speed             [hours]
    """
    polar_coords = {}
    for hub in world_state.hubs:
        if hub.id == CENTRAL_HUB["id"]:
            continue
        
        bearing = compute_bearing_from_trichy(hub)
        distance = haversine(CENTRAL_HUB["latitude"], CENTRAL_HUB["longitude"], 
                            hub.latitude, hub.longitude)
        # Using the fastest truck's speed as a conservative estimate
        fastest_truck = max(world_state.trucks, key=lambda t: t.speed) if world_state.trucks else None
        speed = fastest_truck.speed if fastest_truck else 50.0
        time_hours = distance / speed
        
        polar_coords[hub.id] = {
            'hub': hub,
            'bearing': bearing,
            'distance': distance,
            'time_hours': time_hours
        }
    return polar_coords


def filter_hard_feasibility(polar_coords):
    """
    HARD FEASIBILITY FILTER: Discard hubs that are physically impossible.
    
    Remove hub i if any of these hold:
    - t_i > 7.5
    - t_i > deadline_i
    - No truck has fuel for (depot → hub → depot)
    """
    feasible_coords = {}
    
    for hub_id, coords in polar_coords.items():
        hub = coords['hub']
        
        # Check time constraint: time to hub > 7.5
        if coords['time_hours'] > MAX_DRIVING_TIME_HRS:
            print(f"[DROPPED] {hub.name} deadline={hub.deadline_hours}, time={coords['time_hours']:.2f}")
            continue
        
        # Check fuel constraint: depot -> hub -> depot
        # Calculate fuel needed for round trip: depot -> hub -> depot
        depot_to_hub_dist = coords['distance']
        hub_to_depot_dist = coords['distance']  # Same distance back to depot
        total_distance = depot_to_hub_dist + hub_to_depot_dist
        fuel_needed = total_distance * FUEL_CONSUMPTION_RATE
        
        can_any_truck_reach = False
        for truck in world_state.trucks:
            if truck.fuel_remaining >= fuel_needed:
                can_any_truck_reach = True
                break
        
        if not can_any_truck_reach:
            print(f"[DROPPED] {hub.name} deadline={hub.deadline_hours}, time={coords['time_hours']:.2f}")
            continue
        
        feasible_coords[hub_id] = coords
    
    return feasible_coords


def create_directional_sectors(polar_coords, sector_width=30):
    """
    Directional sectorization: Divide 360° around depot into fixed angular sectors.
    Recommended: 30° sectors → 12 sectors
    """
    sectors = {}
    num_sectors = int(360 / sector_width)
    
    for hub_id, coords in polar_coords.items():
        # Calculate which sector this hub belongs to
        sector_idx = int(coords['bearing'] / sector_width) % num_sectors
        if sector_idx not in sectors:
            sectors[sector_idx] = []
        sectors[sector_idx].append(coords)
    
    return sectors


def order_sector_hubs(sector_hubs):
    """
    Sector-local hub ordering: Inside each sector independently sort by:
    1. deadline (earliest first)
    2. distance r_i (nearest first) - prevents zig-zag by building routes radially outward
    """
    # Sort by deadline first (earliest first), then by distance (nearest first for same deadline)
    # This ensures radial progression and prevents zig-zag routing
    ordered_hubs = sorted(sector_hubs, key=lambda x: (x['hub'].deadline_hours, x['distance']))
    return ordered_hubs


def construct_sector_routes(ordered_hubs, truck_speed):
    """
    Sector route construction: Pack hubs into routes respecting 7.5h time limit and fuel constraints separately.
    Time constraint: depot -> last hub in route <= 7.5h (return trip not counted)
    Fuel constraint: depot -> route -> depot must fit in truck fuel capacity
    Route construction is greedy, monotonic, and radial to prevent zig-zag:
    - Start at depot
    - Append nearest feasible hub
    - Distance from depot must be non-decreasing OR lateral-only
    - NEVER go inward after going outward
    """
    routes = []
    current_route = []
    current_time = 0
    current_position = {'latitude': CENTRAL_HUB["latitude"], 'longitude': CENTRAL_HUB["longitude"]}
    
    # Track the maximum distance from depot reached so far to enforce radial constraint
    max_distance_so_far = 0
    
    for hub_data in ordered_hubs:
        hub = hub_data['hub']
        
        # Calculate distance from depot to this hub
        distance_from_depot = hub_data['distance']
        
        # Radial constraint: never go inward after going outward
        # Enforce: next_hub.distance >= last_hub.distance − epsilon
        epsilon = 0.05  # Small tolerance to account for floating point precision
        
        # Calculate angular difference to prevent unnecessary route splitting
        current_bearing = compute_bearing_from_point(current_position["latitude"], current_position["longitude"])
        hub_bearing = compute_bearing_from_point(hub.latitude, hub.longitude)
        angular_diff = abs(current_bearing - hub_bearing)
        
        # Use a threshold of 30 degrees (in radians, approximately 0.524)
        theta_threshold = 30.0  # degrees
        
        if distance_from_depot < max_distance_so_far - epsilon and angular_diff > theta_threshold:
            # This hub violates the radial constraint, so we need to start a new route
            # Close current route if it has hubs
            if current_route:
                routes.append({
                    'hubs': [hd['hub'] for hd in current_route],
                    'hub_data': current_route,
                    'time': current_time,
                    'distance': sum(haversine(CENTRAL_HUB["latitude"], CENTRAL_HUB["longitude"], hd['hub'].latitude, hd['hub'].longitude) for hd in current_route)  # Use actual total distance for envelope cost
                })
            
            # Start new route with this hub
            current_route = [hub_data]
            
            # Calculate time to this hub from depot
            arrival_time = hub_data['time_hours']
            current_time = arrival_time
            current_position = {'latitude': hub.latitude, 'longitude': hub.longitude}
            max_distance_so_far = distance_from_depot
            
            continue
        
        # Calculate time to this hub from current position
        if len(current_route) == 0:
            # First hub in route: depot -> hub
            delta_time = hub_data['time_hours']
        else:
            # Time from last hub in route to this hub
            dist_to_hub = haversine(current_position['latitude'], current_position['longitude'],
                                  hub.latitude, hub.longitude)
            delta_time = dist_to_hub / truck_speed
        
        # Calculate arrival time at this hub
        arrival_time = current_time + delta_time
        
        # Check time constraint: total time to this hub from depot <= 7.5h (deadline is soft constraint)
        time_constraint_ok = arrival_time <= MAX_DRIVING_TIME_HRS
        
        # Check if we can add this hub to current route
        if time_constraint_ok:
            # HARD deadline constraint - check if arrival time exceeds hub deadline
            if arrival_time > hub.deadline_hours:
                # Close current route if it has hubs
                if current_route:
                    routes.append({
                        'hubs': [hd['hub'] for hd in current_route],
                        'hub_data': current_route,
                        'time': current_time,
                        'distance': sum(haversine(CENTRAL_HUB["latitude"], CENTRAL_HUB["longitude"], hd['hub'].latitude, hd['hub'].longitude) for hd in current_route)  # Use actual total distance for envelope cost
                    })
                
                # Start new route with this hub
                current_route = [hub_data]
                current_time = hub_data['time_hours']  # Time from depot to this hub
                current_position = {'latitude': hub.latitude, 'longitude': hub.longitude}
                max_distance_so_far = distance_from_depot
                continue
            
            # Temporarily add hub to current route to check fuel feasibility
            temp_route = current_route + [hub_data]
            
            # Check fuel feasibility for the entire route (depot -> all hubs -> depot)
            # Calculate total fuel needed for round trip using actual route distances
            # fuel_needed = sum(inter-hub distances) + distance(last_hub → depot)
            fuel_check_ok = True
            if world_state.trucks:  # Only check if trucks exist
                # Calculate fuel needed for depot -> route -> depot using actual path distances
                # Fuel = sum(distances between consecutive hubs) + distance(last_hub -> depot)
                total_fuel_needed = 0
                
                # Calculate fuel for depot to first hub
                if len(temp_route) > 0:
                    first_hub_dist = temp_route[0]['distance']  # Distance from depot to first hub
                    total_fuel_needed += first_hub_dist
                    
                    # Add distances between consecutive hubs
                    for i in range(1, len(temp_route)):
                        prev_hub = temp_route[i-1]['hub']
                        curr_hub = temp_route[i]['hub']
                        inter_hub_dist = haversine(prev_hub.latitude, prev_hub.longitude,
                                                   curr_hub.latitude, curr_hub.longitude)
                        total_fuel_needed += inter_hub_dist
                    
                    # Add distance from last hub back to depot
                    last_hub = temp_route[-1]['hub']
                    depot_return_dist = haversine(last_hub.latitude, last_hub.longitude,
                                                  CENTRAL_HUB["latitude"], CENTRAL_HUB["longitude"])
                    total_fuel_needed += depot_return_dist
                    
                    # Convert to fuel requirement
                    total_fuel_needed *= FUEL_CONSUMPTION_RATE
                    
                # Check if any truck has enough fuel capacity for this round trip
                fuel_check_ok = any(truck.fuel_capacity >= total_fuel_needed for truck in world_state.trucks)
            
            if fuel_check_ok:
                # Add hub to current route
                current_route.append(hub_data)
                current_time = arrival_time  # Update to the arrival time at this hub
                current_position = {'latitude': hub.latitude, 'longitude': hub.longitude}
                
                # Update the maximum distance reached if this hub is farther
                if distance_from_depot > max_distance_so_far:
                    max_distance_so_far = distance_from_depot
            else:
                # Close current route if it has hubs
                if current_route:
                    routes.append({
                        'hubs': [hd['hub'] for hd in current_route],
                        'hub_data': current_route,
                        'time': current_time,
                        'distance': sum(haversine(CENTRAL_HUB["latitude"], CENTRAL_HUB["longitude"], hd['hub'].latitude, hd['hub'].longitude) for hd in current_route)  # Use actual total distance for envelope cost
                    })
                
                # Start new route with this hub
                current_route = [hub_data]
                current_time = hub_data['time_hours']  # Time from depot to this hub
                current_position = {'latitude': hub.latitude, 'longitude': hub.longitude}
                max_distance_so_far = distance_from_depot
        else:
            # Close current route if it has hubs
            if current_route:
                routes.append({
                    'hubs': [hd['hub'] for hd in current_route],
                    'hub_data': current_route,
                    'time': current_time,
                    'distance': sum(haversine(CENTRAL_HUB["latitude"], CENTRAL_HUB["longitude"], hd['hub'].latitude, hd['hub'].longitude) for hd in current_route)  # Use actual total distance for envelope cost
                })
            
            # Start new route with this hub
            current_route = [hub_data]
            current_time = hub_data['time_hours']  # Time from depot to this hub
            current_position = {'latitude': hub.latitude, 'longitude': hub.longitude}
            max_distance_so_far = hub_data['distance']  # Distance from depot to this hub
    
    # Add the final route if it has hubs
    if current_route:
        routes.append({
            'hubs': [hd['hub'] for hd in current_route],
            'hub_data': current_route,
            'time': current_time,
            'distance': sum(haversine(CENTRAL_HUB["latitude"], CENTRAL_HUB["longitude"], hd['hub'].latitude, hd['hub'].longitude) for hd in current_route)  # Use actual total distance for envelope cost
        })
    
    return routes


def compute_route_envelope_cost(route_hub_data_list):
    """
    Route envelope cost: fuel_cost(R) = actual route distance + return distance
    This computes the fuel needed for depot -> route -> depot using actual distances
    """
    if not route_hub_data_list:
        return 0.0
    
    # Calculate total distance for depot -> route -> depot
    total_distance = 0.0
    
    if route_hub_data_list:
        # Add distance from depot to first hub
        total_distance += route_hub_data_list[0]['distance']
        
        # Add distances between consecutive hubs in the route
        for i in range(1, len(route_hub_data_list)):
            prev_hub = route_hub_data_list[i-1]['hub']
            curr_hub = route_hub_data_list[i]['hub']
            inter_hub_dist = haversine(prev_hub.latitude, prev_hub.longitude,
                                       curr_hub.latitude, curr_hub.longitude)
            total_distance += inter_hub_dist
        
        # Add distance from last hub back to depot
        last_hub = route_hub_data_list[-1]['hub']
        depot_return_dist = haversine(last_hub.latitude, last_hub.longitude,
                                      CENTRAL_HUB["latitude"], CENTRAL_HUB["longitude"])
        total_distance += depot_return_dist
    
    return total_distance * FUEL_CONSUMPTION_RATE  # Actual fuel requirement


def compute_sector_summary(sectors_routes):
    """
    Sector demand summary: compute metrics for each sector.
    """
    sector_summaries = {}
    
    for sector_idx, routes in sectors_routes.items():
        total_routes = len(routes)
        total_hubs = sum(len(route['hubs']) for route in routes)
        total_demand = sum(sum(h.demand_quantity for h in route['hubs']) for route in routes)
        total_fuel = sum(compute_route_envelope_cost(route['hub_data']) for route in routes)
        
        sector_summaries[sector_idx] = {
            'routes': total_routes,
            'hubs_served': total_hubs,
            'total_demand': total_demand,
            'total_fuel': total_fuel
        }
    
    return sector_summaries


def select_global_routes(sectors_routes, available_trucks):
    """
    Global truck & fuel optimization: Select routes by priority:
    1) earliest deadline coverage
    2) more hubs served
    3) lower total distance
    """
    # Flatten all routes from all sectors
    all_routes = []
    for sector_idx, routes in sectors_routes.items():
        for route in routes:
            envelope_cost = compute_route_envelope_cost(route['hub_data'])
            num_hubs = len(route['hubs'])
            total_demand = sum(h.demand_quantity for h in route['hubs'])
            
            # Find the earliest deadline in this route
            earliest_deadline = min(h.deadline_hours for h in route['hubs']) if route['hubs'] else float('inf')
            
            all_routes.append({
                'sector_idx': sector_idx,
                'route': route,
                'envelope_cost': envelope_cost,
                'num_hubs': num_hubs,
                'total_demand': total_demand,
                'earliest_deadline': earliest_deadline,
                # Score prioritizing: 1) earliest deadline, 2) more hubs, 3) lower effective cost (envelope + activation penalty)
                'score': (
                    -earliest_deadline,
                    num_hubs,
                    -(envelope_cost + TRUCK_ACTIVATION_PENALTY_LITERS)  # Effective cost includes activation penalty
                )  # Negative deadline for ascending order, negative fuel for descending efficiency
            })
    
    # Sort routes by score (highest first) - Python sorts tuples lexicographically
    all_routes.sort(key=lambda r: r['score'], reverse=True)
    
    # Greedily select routes until we run out of trucks
    selected_routes = []
    assigned_hub_ids = set()
    
    for route_info in all_routes:
        # Check if any hub in this route is already assigned
        route_hub_ids = set(hub.id for hub in route_info['route']['hubs'])
        if not assigned_hub_ids.intersection(route_hub_ids) and len(selected_routes) < len(available_trucks):
            selected_routes.append(route_info)
            assigned_hub_ids.update(route_hub_ids)
    
    return selected_routes


def assign_trucks_to_routes(selected_routes):
    """
    Truck assignment: Assign physical trucks to routes.
    """
    # Sort trucks by fuel capacity (descending) for efficient assignment
    sorted_trucks = sorted(world_state.trucks, key=lambda t: t.fuel_remaining, reverse=True)
    
    for i, route_info in enumerate(selected_routes):
        if i < len(sorted_trucks):
            truck = sorted_trucks[i]
            route = route_info['route']
            
            # Assign the route to the truck
            truck.route_plan = [hub.id for hub in route['hubs']]
            truck.active = True
            truck.cluster_id = f"SECTOR_{route_info['sector_idx']}"
            
            # Clear future task queue and populate with the assigned route
            truck.future_task_queue = []
            for hub in route['hubs']:
                # Create task without urgency (using default urgency_weight of 0.0)
                task = Task(hub_id=hub.id, urgency_weight=0.0, assigned_at=world_state.simulation_time)
                truck.future_task_queue.append(task)
            
            # Assign hubs to this truck with ownership
            for hub in route['hubs']:
                hub_obj = next((h for h in world_state.hubs if h.id == hub.id), None)
                if hub_obj:
                    hub_obj.owner_truck_id = truck.id
                    hub_obj.ownership_state = HubOwnershipState.ASSIGNED
                    hub_obj.frozen_at_commit = True
                    hub_obj.cluster_id = truck.cluster_id
    
    # Keep all trucks active but clear their plans
    for i in range(len(selected_routes), len(sorted_trucks)):
        sorted_trucks[i].active = True
        sorted_trucks[i].route_plan = []
        sorted_trucks[i].future_task_queue = []


def fleet_optimized_assignment_algorithm():
    """
    Main fleet-level directional logistics optimization algorithm.
    
    Implements the complete workflow:
    1. Canonical transformation to polar coordinates
    2. Hard feasibility filtering
    3. Directional sectorization
    4. Sector-local hub ordering
    5. Sector route construction
    6. Route envelope cost computation
    7. Sector demand summary
    8. Global route selection
    9. Truck assignment
    
    Returns True if commit was successful, False if any hub is unassigned.
    """
    # Get all hubs with demand (excluding central hub)
    hubs_requiring_assignment = []
    for hub in world_state.hubs:
        if hub.id != CENTRAL_HUB["id"] and hub.demand_quantity > 0:
            hubs_requiring_assignment.append(hub)
    
    print(f"[FLEET OPTIMIZATION] {len(hubs_requiring_assignment)} hubs require assignment")
    
    # If no hubs need service, commit is successful
    if not hubs_requiring_assignment:
        for truck in world_state.trucks:
            truck.route_plan.clear()
            truck.assigned_hubs.clear()
            truck.status = "idle"
            truck.future_task_queue = []
        print("[FLEET OPTIMIZATION] No hubs to assign - commit successful")
        # Set simulation phase to committed
        world_state.simulation_phase = "committed"
        return True
    
    # Get active trucks
    active_trucks = [t for t in world_state.trucks if t.active]
    if not active_trucks:
        print("[FLEET OPTIMIZATION] No active trucks available - commit failed")
        return False
    
    # Reset all truck states
    for truck in world_state.trucks:
        if truck.active:
            truck.route_plan.clear()
            truck.assigned_hubs.clear()
            truck.completed_deliveries.clear()
            truck.status = "idle"
            truck.future_task_queue = []
    
    # Step 1: Transform to polar coordinates
    polar_coords = compute_polar_coordinates()
    
    # Step 2: Filter hard feasibility
    feasible_coords = filter_hard_feasibility(polar_coords)
    
    # Step 3: Create directional sectors
    sectors = create_directional_sectors(feasible_coords, sector_width=30)
    
    # Step 4: Order hubs within each sector
    sectors_ordered = {}
    for sector_idx, hub_list in sectors.items():
        sectors_ordered[sector_idx] = order_sector_hubs(hub_list)
    
    # Step 5: Construct routes within each sector
    sectors_routes = {}
    # Use the speed of the fastest truck for time calculations
    fastest_truck = max(world_state.trucks, key=lambda t: t.speed) if world_state.trucks else None
    truck_speed = fastest_truck.speed if fastest_truck else 50.0
    
    for sector_idx, ordered_hubs in sectors_ordered.items():
        routes = construct_sector_routes(ordered_hubs, truck_speed)
        sectors_routes[sector_idx] = routes
    
    # Step 6 & 7: Compute sector summaries
    sector_summaries = compute_sector_summary(sectors_routes)
    
    # Step 8: Global route selection
    selected_routes = select_global_routes(sectors_routes, active_trucks)
    
    # Step 9: Assign trucks to routes
    assign_trucks_to_routes(selected_routes)
    
    # ===========================================
    # COMMIT VALIDATION (UPDATED FOR OPTIMIZATION)
    # ===========================================
    # Allow unassigned hubs - only fail if no routes were selected at all
    assigned_hub_ids = set()
    for route_info in selected_routes:
        for hub in route_info['route']['hubs']:
            assigned_hub_ids.add(hub.id)
    
    # Check if any hubs remain unassigned
    final_unassigned = []
    for hub in hubs_requiring_assignment:
        if hub.id not in assigned_hub_ids:
            final_unassigned.append(hub)
    
    # Mark unassigned hubs appropriately
    for hub in final_unassigned:
        hub.ownership_state = HubOwnershipState.UNASSIGNED
        hub.owner_truck_id = None
        hub.cluster_id = None  # Clear cluster assignment
        print(f"[FLEET OPTIMIZATION] Hub {hub.name} ({hub.id}) left unassigned due to constraints")
    
    # Only fail if no routes were selected at all (no feasible solution)
    if not selected_routes and hubs_requiring_assignment:
        print(f"[FLEET OPTIMIZATION FAILED] No feasible routes could be created for {len(hubs_requiring_assignment)} hubs")
        return False
    
    # ===========================================
    # FREEZE ASSIGNED HUBS ONLY
    # ===========================================
    # Mark only assigned hubs as frozen - unassigned hubs remain available
    # DO NOT refreeze old hubs that are already frozen
    for hub in hubs_requiring_assignment:
        if hub.id in assigned_hub_ids and not hub.frozen_at_commit:
            hub.frozen_at_commit = True
    
    # Store initial hub list for reference
    world_state.initial_hubs_with_demand = [h.id for h in hubs_requiring_assignment]
    
    # Set simulation phase to committed
    world_state.simulation_phase = "committed"
    
    # Log results
    active_trucks = [t for t in world_state.trucks if t.active]
    total_hubs_assigned = sum(len(route_info['route']['hubs']) for route_info in selected_routes)
    total_fuel_estimate = sum(route_info['envelope_cost'] for route_info in selected_routes)
    
    print(f"[FLEET OPTIMIZATION] Routes selected: {len(selected_routes)}, Trucks used: {len(active_trucks)}, Hubs assigned: {total_hubs_assigned}, Hubs unassigned: {len(final_unassigned)}, Estimated fuel: {total_fuel_estimate:.2f}L")
    
    return True


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
