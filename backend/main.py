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
    "demand_priority": "High",
    "availability": 10000  # Effectively infinite availability
}

MAX_CLUSTER_DISTANCE = 300  # km
MAX_HUBS_PER_TRUCK = 5
FUEL_CONSUMPTION_RATE = 0.1  # L/km

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
    demand_priority: str
    availability: int = 100  # How much supply it can receive or send
    priority_cost: float = 0.0  # Numeric weight derived from priority
    delivered: bool = False
    demand_intensity: str = "Medium"  # Low, Medium, High, Emergency - live mutable urgency
    distance_from_trichy_km: float = 0.0  # Distance from central hub in km
    
    # HUB OWNERSHIP MODEL (TWO-STAGE CONTRACT)
    ownership_state: str = "UNASSIGNED"  # UNASSIGNED, ASSIGNED, COMPLETED
    owner_truck_id: Optional[str] = None  # The truck that owns this hub (if ASSIGNED)
    
    # COMMIT PHASE TRACKING
    frozen_at_commit: bool = False  # True for hubs that existed at commit time
    # Frozen hubs CANNOT be claimed during execution - ownership was decided at commit

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
    # For route-based disasters (traffic and roadblock), store the affected route segment
    affected_route_id: Optional[str] = None
    affected_segment_start_idx: Optional[int] = None
    affected_segment_end_idx: Optional[int] = None
    snapped_coordinates: Optional[Dict] = None  # Snapped coordinates {latitude: float, longitude: float}
    # For traffic, store the affected road segment info
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
        demand_priority="High",
        availability=CENTRAL_HUB["availability"],
        delivered=True,  # Always treated as completed
        demand_intensity="Low",
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
    # Convert to Cartesian coordinates for accurate calculation
    # This is a simplified version using haversine distance
    # For more accurate calculation, we'd need to use proper projection
    
    # Vector from start to end of line segment
    line_vec_x = line_end_lon - line_start_lon
    line_vec_y = line_end_lat - line_start_lat
    
    # Vector from start of line to point
    point_vec_x = lon - line_start_lon
    point_vec_y = lat - line_start_lat
    
    # Calculate line length squared
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
    score = (priority_weight × demand_intensity_weight) - distance_cost - fuel_cost
    
    This is a LOCAL decision - each truck evaluates independently.
    """
    # Priority weights for demand_priority
    priority_weights = {
        "Emergency": 5.0,
        "High": 3.0,
        "Medium": 2.0,
        "Low": 1.0
    }
    
    # Get base priority weight
    priority_weight = priority_weights.get(hub.demand_priority, 2.0)
    
    # Get urgency weight from demand_intensity (live slider value)
    urgency_weight = get_urgency_weight(hub.demand_intensity)
    
    # Calculate distance from current truck position to hub
    distance_km = haversine(truck.current_latitude, truck.current_longitude, 
                            hub.latitude, hub.longitude)
    
    # Fuel cost proportional to distance
    fuel_cost = distance_km * FUEL_CONSUMPTION_RATE * truck.fuel_efficiency
    
    # Distance penalty (per km)
    distance_cost = distance_km * 0.5  # 0.5 penalty per km
    
    # Final score calculation
    score = (priority_weight * urgency_weight) - distance_cost - fuel_cost
    
    return score

def select_next_hub_locally(truck: Truck) -> Optional[str]:
    """
    LOCAL DECISION: Select the best next hub for this truck.
    Called only at safe decision points.
    
    OWNERSHIP MODEL:
    1. First, check if truck owns any hubs (already assigned) - serve those first
    2. If no owned hubs, select from UNASSIGNED hubs only
    3. Assign the selected hub to this truck (mark as ASSIGNED)
    4. No truck may consider hubs owned by another truck
    
    CONSTRAINTS:
    1. Must have remaining demand (demand_quantity > 0)
    2. Must be fuel-feasible (enough fuel to reach hub and return to depot)
    3. Only consider UNASSIGNED hubs OR hubs already ASSIGNED to this truck
    
    PREFERENCES:
    1. Higher urgency (demand_intensity) hubs are preferred
    2. Closer hubs preferred when urgency is similar
    3. Emergencies get strong weight boost but don't force dispatch
    """
    if not is_at_safe_decision_point(truck):
        return None
    
    # PRIORITY 1: Check if we already own any hubs - serve those first
    owned_hubs = get_truck_owned_hubs(truck.id)
    if owned_hubs:
        # Find the highest-priority owned hub
        best_owned_hub = None
        best_score = float('-inf')
        
        for hub_id in owned_hubs:
            hub = next((h for h in world_state.hubs if h.id == hub_id), None)
            if hub and hub.demand_quantity > 0 and not hub.delivered:
                # Check fuel feasibility
                if is_fuel_feasible_with_return(truck, hub):
                    score = calculate_hub_score(truck, hub)
                    if score > best_score:
                        best_score = score
                        best_owned_hub = hub_id
        
        if best_owned_hub:
            print(f"[OWNERSHIP] Truck {truck.id} selecting owned hub {best_owned_hub}")
            return best_owned_hub
    
    # PRIORITY 2: Select from UNASSIGNED hubs
    # EXECUTION RULE: Only consider NEW hubs (not frozen_at_commit)
    # Initial hubs were assigned at commit - trucks cannot "discover" them during execution
    candidate_hubs = []
    
    for hub in world_state.hubs:
        # Skip central hub
        if hub.id == CENTRAL_HUB["id"]:
            continue
        
        # OWNERSHIP CHECK: Only consider UNASSIGNED hubs
        if not is_hub_available_for_assignment(hub):
            continue
        
        # EXECUTION RULE: Skip frozen hubs - they should have been assigned at commit
        # Only NEW hubs (created after commit) can be claimed during execution
        if hub.frozen_at_commit:
            print(f"[EXECUTION RULE] Skipping frozen hub {hub.id} - should have been assigned at commit")
            continue
        
        # Check fuel feasibility (enough to reach hub and return to depot) - HARD CONSTRAINT
        if not is_fuel_feasible_with_return(truck, hub):
            continue
        
        # Calculate score for this hub
        score = calculate_hub_score(truck, hub)
        candidate_hubs.append((hub.id, score, hub))
    
    if not candidate_hubs:
        return None
    
    # Sort by score (descending) and select the best
    candidate_hubs.sort(key=lambda x: x[1], reverse=True)
    best_hub_id, best_score, best_hub = candidate_hubs[0]
    
    # OWNERSHIP: Assign the hub to this truck before returning
    if assign_hub_to_truck(best_hub_id, truck.id):
        print(f"[LOCAL DECISION] Truck {truck.id} selected and claimed {best_hub.name} "
              f"(score={best_score:.2f}, intensity={best_hub.demand_intensity})")
        return best_hub_id
    else:
        # Assignment failed - hub was taken by another truck
        print(f"[CONFLICT] Truck {truck.id} could not claim hub {best_hub_id}")
        return None

def extend_route_if_efficient(truck: Truck, current_hub: Hub) -> Optional[str]:
    """
    After completing a delivery, check if it's more efficient to:
    1. Continue to a nearby hub that we ALREADY OWN (serve owned hubs first)
    2. If no owned hubs, check for nearby UNASSIGNED hubs to claim
    3. Return to depot if no efficient extension possible
    
    OWNERSHIP RULES:
    - First priority: serve hubs we already own
    - Second priority: claim nearby UNASSIGNED hubs if efficient
    - Never consider hubs owned by other trucks
    
    CLUSTER STABILITY: Prefer extending to nearby hubs to maintain geographic clusters.
    """
    if not is_at_safe_decision_point(truck):
        return None
    
    # FUEL CONSTRAINT: Check if we have fuel to do anything beyond returning
    dist_to_depot = haversine(truck.current_latitude, truck.current_longitude,
                              CENTRAL_HUB["latitude"], CENTRAL_HUB["longitude"])
    fuel_to_depot = dist_to_depot * FUEL_CONSUMPTION_RATE
    reserve_fuel = truck.fuel_remaining - fuel_to_depot
    
    if reserve_fuel <= 0:
        return None  # Must return to depot - HARD CONSTRAINT
    
    # PRIORITY 1: Check if we own any other hubs
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
            print(f"[EXTEND] Truck {truck.id} extending to owned hub {best_owned}")
            return best_owned
    
    # PRIORITY 2: Find nearby UNASSIGNED hubs for efficient extension
    # EXECUTION RULE: Only consider NEW hubs (not frozen_at_commit)
    nearby_hubs = []
    
    for hub in world_state.hubs:
        # Only consider UNASSIGNED hubs
        if not is_hub_available_for_assignment(hub):
            continue
        
        # EXECUTION RULE: Skip frozen hubs - they should have been assigned at commit
        # Only NEW hubs (created after commit) can be claimed during execution
        if hub.frozen_at_commit:
            continue
        
        # Check fuel feasibility - HARD CONSTRAINT
        if not is_fuel_feasible_with_return(truck, hub):
            continue
        
        dist_to_hub = haversine(truck.current_latitude, truck.current_longitude,
                                hub.latitude, hub.longitude)
        dist_hub_to_depot = haversine(hub.latitude, hub.longitude,
                                      CENTRAL_HUB["latitude"], CENTRAL_HUB["longitude"])
        
        # CLUSTER STABILITY: Prefer extending route if marginal cost is less than new truck cost
        marginal_cost = dist_to_hub
        new_truck_cost = dist_hub_to_depot
        
        if marginal_cost < new_truck_cost * 0.8:  # 20% margin for preference
            score = calculate_hub_score(truck, hub)
            nearby_hubs.append((hub.id, score, dist_to_hub))
    
    if not nearby_hubs:
        return None
    
    # Sort by score and select best nearby hub
    nearby_hubs.sort(key=lambda x: x[1], reverse=True)
    best_hub_id, _, _ = nearby_hubs[0]
    
    # OWNERSHIP: Claim the hub before returning
    if assign_hub_to_truck(best_hub_id, truck.id):
        print(f"[EXTEND] Truck {truck.id} extending and claiming hub {best_hub_id}")
        return best_hub_id
    else:
        print(f"[EXTEND FAILED] Could not claim hub {best_hub_id}")
        return None

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
    
    # Get all hubs with demand (excluding central hub)
    hubs_requiring_assignment = []
    for hub in world_state.hubs:
        if hub.id != CENTRAL_HUB["id"] and hub.demand_quantity > 0:
            hubs_requiring_assignment.append(hub)
    
    print(f"[COMMIT PHASE] {len(hubs_requiring_assignment)} hubs require assignment")
    
    # If no hubs need service, commit is successful
    if not hubs_requiring_assignment:
        for truck in world_state.trucks:
            truck.route_plan.clear()
            truck.assigned_hubs.clear()
            truck.status = "idle"
        print("[COMMIT] No hubs to assign - commit successful")
        return True

    # Reset all truck states
    for truck in world_state.trucks:
        if truck.active:
            truck.route_plan.clear()
            truck.assigned_hubs.clear()
            truck.completed_deliveries.clear()
            truck.status = "idle"
    
    # Get active trucks
    active_trucks = [truck for truck in world_state.trucks if truck.active]
    if not active_trucks:
        print("[COMMIT ERROR] No active trucks available")
        return False
    
    # CORRIDOR-BASED CLUSTERING
    import math
    from collections import defaultdict
    
    central_lat = CENTRAL_HUB["latitude"]
    central_lon = CENTRAL_HUB["longitude"]
    
    # Build hub info with angle and distance
    hub_info = []
    for hub in hubs_requiring_assignment:
        distance_km = haversine(central_lat, central_lon, hub.latitude, hub.longitude)
        angle = math.atan2(hub.latitude - central_lat, hub.longitude - central_lon)
        hub_info.append({
            'hub': hub,
            'distance_km': distance_km,
            'angle': angle,
            'demand_count': min(hub.demand_quantity, hub.availability)
        })
    
    # Cluster by angular direction (30 degree bins)
    ANGLE_THRESHOLD = math.radians(30)
    corridors = defaultdict(list)
    
    for hub_data in hub_info:
        angle_bin = round(hub_data['angle'] / ANGLE_THRESHOLD)
        corridors[angle_bin].append(hub_data)
    
    # Sort hubs within each corridor by priority then distance
    priority_order = {"Emergency": 0, "High": 1, "Medium": 2, "Low": 3}
    for corridor_key in corridors:
        corridors[corridor_key].sort(
            key=lambda x: (priority_order.get(x['hub'].demand_priority, 2), x['distance_km'])
        )
    
    print(f"[COMMIT] Created {len(corridors)} geographic corridors")
    
    # ===========================================
    # PHASE 1: CLUSTER-BASED ASSIGNMENT
    # ===========================================
    assigned_hubs = set()
    
    for corridor_key, corridor_hubs in corridors.items():
        # Find best truck for this corridor
        corridor_truck = None
        min_cost = float('inf')
        
        for truck in active_trucks:
            if len(truck.route_plan) >= truck.max_capacity:
                continue
            
            first_hub = corridor_hubs[0]['hub']
            if not truck.route_plan:
                cost = haversine(central_lat, central_lon, first_hub.latitude, first_hub.longitude)
            else:
                last_hub_id = truck.route_plan[-1]
                last_hub = next((h for h in world_state.hubs if h.id == last_hub_id), None)
                cost = haversine(last_hub.latitude, last_hub.longitude, 
                               first_hub.latitude, first_hub.longitude) if last_hub else float('inf')
            
            if cost < min_cost:
                min_cost = cost
                corridor_truck = truck
        
        if not corridor_truck:
            # No truck with capacity - will be handled in fallback
            continue
        
        # Assign hubs in this corridor to the truck
        for hub_data in corridor_hubs:
            hub = hub_data['hub']
            demand_count = hub_data['demand_count']
            
            # Check capacity, switch trucks if needed
            if len(corridor_truck.route_plan) >= corridor_truck.max_capacity:
                for alt_truck in active_trucks:
                    if len(alt_truck.route_plan) < alt_truck.max_capacity:
                        corridor_truck = alt_truck
                        break
                else:
                    continue  # Will be handled in fallback
            
            # Assign with ownership
            if assign_hub_to_truck(hub.id, corridor_truck.id):
                for _ in range(demand_count):
                    if len(corridor_truck.route_plan) < corridor_truck.max_capacity:
                        corridor_truck.route_plan.append(hub.id)
                assigned_hubs.add(hub.id)
    
    # ===========================================
    # PHASE 2: FALLBACK ASSIGNMENT (MANDATORY)
    # ===========================================
    # Any hub not assigned in clustering MUST be assigned here
    
    unassigned_hubs = [hub for hub in hubs_requiring_assignment if hub.id not in assigned_hubs]
    
    if unassigned_hubs:
        print(f"[COMMIT FALLBACK] {len(unassigned_hubs)} hubs need fallback assignment")
        
        for hub in unassigned_hubs:
            # Find the nearest feasible truck (any truck with capacity)
            best_truck = None
            min_distance = float('inf')
            
            for truck in active_trucks:
                if len(truck.route_plan) >= truck.max_capacity:
                    continue
                
                # Calculate distance from depot to this hub
                dist = haversine(central_lat, central_lon, hub.latitude, hub.longitude)
                
                if dist < min_distance:
                    min_distance = dist
                    best_truck = truck
            
            if best_truck:
                if assign_hub_to_truck(hub.id, best_truck.id):
                    demand_count = min(hub.demand_quantity, hub.availability)
                    for _ in range(demand_count):
                        if len(best_truck.route_plan) < best_truck.max_capacity:
                            best_truck.route_plan.append(hub.id)
                    assigned_hubs.add(hub.id)
                    print(f"[COMMIT FALLBACK] Hub {hub.name} assigned to Truck {best_truck.id}")
                else:
                    print(f"[COMMIT ERROR] Failed to assign hub {hub.name}")
            else:
                print(f"[COMMIT ERROR] No truck with capacity for hub {hub.name}")
    
    # ===========================================
    # PHASE 3: COMMIT VALIDATION (MANDATORY)
    # ===========================================
    # Verify ALL hubs are assigned - if any unassigned, commit fails
    
    final_unassigned = []
    for hub in hubs_requiring_assignment:
        if hub.ownership_state != HubOwnershipState.ASSIGNED:
            final_unassigned.append(hub)
    
    if final_unassigned:
        print(f"[COMMIT FAILED] {len(final_unassigned)} hubs remain unassigned!")
        for hub in final_unassigned:
            print(f"  - {hub.name} ({hub.id})")
        return False
    
    # ===========================================
    # PHASE 4: FREEZE ALL INITIAL HUBS
    # ===========================================
    # Mark all hubs as frozen - they cannot be re-assigned during execution
    
    for hub in hubs_requiring_assignment:
        hub.frozen_at_commit = True
    
    # Store initial hub list for reference
    world_state.initial_hubs_with_demand = [h.id for h in hubs_requiring_assignment]
    
    # Print commit summary
    print(f"[COMMIT SUCCESS] All {len(hubs_requiring_assignment)} hubs assigned and frozen")
    for truck in world_state.trucks:
        if truck.route_plan:
            owned_hubs = get_truck_owned_hubs(truck.id)
            print(f"  Truck {truck.id}: {len(owned_hubs)} hubs owned, route_plan={truck.route_plan}")
    
    return True

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

            # ========================================
            # STATE: IDLE (SAFE DECISION POINT)
            # ========================================
            if truck.status == "idle":
                truck.last_decision_point = world_state.simulation_time
                
                # LOCAL DECISION: Select next hub using demand-pressure scoring
                # First try task queue (legacy support), then use local selection
                next_hub_id = None
                
                # If we have pending tasks in queue, reorder and use them
                if truck.future_task_queue:
                    reorder_task_queue_at_decision_point(truck)
                    truck.current_task = truck.future_task_queue.pop(0)
                    next_hub_id = truck.current_task.hub_id
                else:
                    # LOCAL DECISION: Select best hub based on current demand pressure
                    next_hub_id = select_next_hub_locally(truck)
                    if next_hub_id:
                        # Create task for the selected hub
                        hub = next((h for h in world_state.hubs if h.id == next_hub_id), None)
                        if hub:
                            truck.current_task = Task(
                                hub_id=next_hub_id,
                                urgency_weight=get_urgency_weight(hub.demand_intensity),
                                assigned_at=world_state.simulation_time
                            )
                
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
                                f"(Intensity: {hub.demand_intensity}, "
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
                    for disaster in world_state.disasters:
                        if disaster.active and disaster.contains_point(truck.current_latitude, truck.current_longitude):
                            if disaster.disaster_type == DisasterType.RAIN:
                                # Rain increases fuel consumption slightly
                                disaster_multiplier = 1.1
                                                    
                                # Add notification for rain
                                if "Rain zone ahead" not in (truck.disaster_notifications or []):
                                    truck.disaster_notifications.append("Rain zone ahead — ETA may increase")
                            elif disaster.disaster_type == DisasterType.TRAFFIC:
                                # Traffic increases fuel consumption and reduces speed
                                disaster_multiplier = disaster.traffic_severity
                                                    
                                # Add notification for traffic
                                if "Traffic ahead" not in (truck.disaster_notifications or []):
                                    truck.disaster_notifications.append("Traffic ahead — continuing on current route")
                            elif disaster.disaster_type == DisasterType.ROAD_BLOCK:
                                # Road blocks should have been handled at decision points
                                # If truck is still moving through a road block, it's an error
                                print(f"[ERROR] Truck {truck.id} moving through road block at ({truck.current_latitude}, {truck.current_longitude})")
                                                    
                                # Add notification for road block
                                if "Road blocked" not in (truck.disaster_notifications or []):
                                    truck.disaster_notifications.append("Road blocked — waiting for instructions")
                                                        
                                # Set truck to blocked status
                                truck.blocked_status = "BLOCKED_WAITING_OVERRIDE"
                                truck.status = "idle"
                                                    
                                # Add AI decision to notify manager
                                world_state.ai_decisions.append(
                                    AIDecision(
                                        truck_id=truck.id,
                                        decision="TRUCK_BLOCKED_BY_ROAD_BLOCK",
                                        explanation=f"Truck {truck.id} blocked by road block at ({disaster.latitude}, {disaster.longitude}). Awaiting manager override.",
                                        timestamp=world_state.simulation_time
                                    )
                                )
                                                    
                                # Clear the route to stop movement
                                truck.route.clear()
                                                    
                    fuel_used = segment_dist * FUEL_CONSUMPTION_RATE * disaster_multiplier
                    truck.fuel_remaining = max(0, truck.fuel_remaining - fuel_used)
                    truck.current_fuel_used += fuel_used
                                        
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
                    
                    # LOCAL DECISION: Try to extend route or return to depot
                    # Prefer extending route if efficient (reduces total trips)
                    next_hub_id = None
                    if completed_hub:
                        next_hub_id = extend_route_if_efficient(truck, completed_hub)
                    
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
                        # No efficient extension, no more tasks - return to depot
                        # FETCH ROAD ROUTE FROM OSRM (computed ONCE at destination assignment)
                        truck.route = get_road_route(
                            truck.current_latitude,
                            truck.current_longitude,
                            CENTRAL_HUB["latitude"],
                            CENTRAL_HUB["longitude"]
                        )
                        truck.full_route = truck.route.copy()
                        truck.current_route_index = 0
                        truck.status = "returning"
                        
                        world_state.ai_decisions.append(
                            AIDecision(
                                truck_id=truck.id,
                                decision="RETURNING",
                                explanation="Returning to depot - no efficient extensions available",
                                timestamp=world_state.simulation_time
                            )
                        )
                    
                    truck.route.clear()
                    truck.full_route.clear()
                    truck.current_route_index = 0
            
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
                                            if disaster.disaster_type == DisasterType.TRAFFIC:
                                                # Traffic increases fuel consumption and reduces speed
                                                disaster_multiplier = disaster.traffic_severity
            
                                                # Add notification for traffic
                                                if "Traffic ahead" not in (truck.disaster_notifications or []):
                                                    truck.disaster_notifications.append("Traffic ahead — continuing on current route")
                                            elif disaster.disaster_type == DisasterType.ROAD_BLOCK:
                                                # Road blocks should have been handled at decision points
                                                # If truck is still moving through a road block, it's an error
                                                print(f"[ERROR] Truck {truck.id} moving through road block at ({truck.current_latitude}, {truck.current_longitude})")
            
                                                # Add notification for road block
                                                if "Road blocked" not in (truck.disaster_notifications or []):
                                                    truck.disaster_notifications.append("Road blocked — waiting for instructions")
            
                                                # Set truck to blocked status
                                                truck.blocked_status = "BLOCKED_WAITING_OVERRIDE"
                                                truck.status = "idle"
            
                                                # Add AI decision to notify manager
                                                world_state.ai_decisions.append(
                                                    AIDecision(
                                                        truck_id=truck.id,
                                                        decision="TRUCK_BLOCKED_BY_ROAD_BLOCK",
                                                        explanation=f"Truck {truck.id} blocked by road block at ({disaster.latitude}, {disaster.longitude}). Awaiting manager override.",
                                                        timestamp=world_state.simulation_time
                                                    )
                                                )
            
                                                # Clear the route to stop movement
                                                truck.route.clear()
                            else:
                                # For non-route disasters (like rain), check if point is within radius
                                if disaster.contains_point(truck.current_latitude, truck.current_longitude):
                                    if disaster.disaster_type == DisasterType.RAIN:
                                        # Rain increases fuel consumption slightly
                                        disaster_multiplier = 1.1
            
                                        # Add notification for rain
                                        if "Rain zone ahead" not in (truck.disaster_notifications or []):
                                            truck.disaster_notifications.append("Rain zone ahead — ETA may increase")
                                            
                    truck.fuel_remaining = max(0, truck.fuel_remaining - segment_dist * FUEL_CONSUMPTION_RATE * disaster_multiplier)
                else:
                    # ARRIVED AT DEPOT (SAFE DECISION POINT)
                    truck.current_latitude = CENTRAL_HUB["latitude"]
                    truck.current_longitude = CENTRAL_HUB["longitude"]
                    truck.status = "idle"
                    
                    # Refuel and reset
                    truck.fuel_remaining = truck.fuel_capacity
                    truck.current_fuel_used = 0.0
                    
                    truck.route.clear()
                    truck.full_route.clear()
                    truck.current_route_index = 0

# =========================
# API
# =========================


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

def initialize_task_queues_from_route_plans():
    """Convert legacy route_plan to new task queue system"""
    for truck in world_state.trucks:
        if not truck.active:
            continue
        
        # Clear task queues
        truck.current_task = None
        truck.future_task_queue = []
        
        # Convert route_plan to task queue
        for hub_id in truck.route_plan:
            hub = next((h for h in world_state.hubs if h.id == hub_id), None)
            if hub:
                task = Task(
                    hub_id=hub_id,
                    urgency_weight=get_urgency_weight(hub.demand_intensity),
                    assigned_at=world_state.simulation_time
                )
                truck.future_task_queue.append(task)
        
        # If truck has tasks, make first one the current task (if idle)
        if truck.future_task_queue and truck.status == "idle":
            truck.current_task = truck.future_task_queue.pop(0)

@app.post("/simulation/start")
def start_sim():
    """
    ====================================================
    COMMIT PHASE - STRICT TWO-STAGE CONTRACT
    ====================================================
    
    This endpoint initiates the MANDATORY commit phase:
    1. Freezes all hubs
    2. Assigns ALL hubs to trucks (must succeed for every hub)
    3. Validates that no hub remains unassigned
    4. Blocks simulation if any hub is unassigned
    5. Starts execution phase only after successful commit
    """
    # Freeze hubs - no new hubs can be added after this
    world_state.hubs_frozen = True
    world_state.simulation_phase = "committing"
    
    # ===========================================
    # COMMIT PHASE: Assign ALL hubs (MANDATORY)
    # ===========================================
    commit_success = assign_hubs_to_trucks()
    
    if not commit_success:
        # COMMIT FAILED: Some hubs are unassigned
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
            detail="COMMIT FAILED: Not all hubs could be assigned. Check truck capacity and availability."
        )
    
    # COMMIT SUCCESS: All hubs are assigned and frozen
    world_state.simulation_phase = "committed"
    
    # Convert route plans to task queues
    initialize_task_queues_from_route_plans()

    world_state.simulation_running = True
    world_state.simulation_phase = "executing"
    
    global simulation_thread
    simulation_thread = Thread(target=simulation_loop, daemon=True)
    simulation_thread.start()
    
    return {
        "message": "COMMIT SUCCESS: All hubs assigned and frozen. Execution phase started.",
        "hubs_committed": len(world_state.initial_hubs_with_demand),
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
    demand_priority: str
    availability: int = 20

class HubUpdateRequest(BaseModel):
    demand_quantity: int
    demand_priority: str

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
        demand_priority=hub_data.demand_priority,
        availability=hub_data.availability if hasattr(hub_data, 'availability') else 20,
        priority_cost=0.0,
        delivered=False,
        demand_intensity="Medium",  # Default intensity
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
                        "demand_priority": "High",
                        "availability": 20,
                        "priority_cost": 0.0
                    },
                    {
                        "id": "H2",
                        "name": "Karur",
                        "latitude": 10.9601,
                        "longitude": 78.0766,
                        "demand_quantity": 1,
                        "demand_priority": "Medium",
                        "availability": 20,
                        "priority_cost": 0.0
                    },
                    {
                        "id": "H3",
                        "name": "Dindigul",
                        "latitude": 10.3673,
                        "longitude": 77.9803,
                        "demand_quantity": 1,
                        "demand_priority": "Medium",
                        "availability": 20,
                        "priority_cost": 0.0
                    },
                    {
                        "id": "H4",
                        "name": "Perambalur",
                        "latitude": 11.2342,
                        "longitude": 78.8803,
                        "demand_quantity": 1,
                        "demand_priority": "Low",
                        "availability": 20,
                        "priority_cost": 0.0
                    },
                    {
                        "id": "H5",
                        "name": "Ariyalur",
                        "latitude": 11.1401,
                        "longitude": 79.0787,
                        "demand_quantity": 1,
                        "demand_priority": "Low",
                        "availability": 20,
                        "priority_cost": 0.0
                    },
                    {
                        "id": "H6",
                        "name": "Pudukkottai",
                        "latitude": 10.3797,
                        "longitude": 78.8208,
                        "demand_quantity": 1,
                        "demand_priority": "Medium",
                        "availability": 20,
                        "priority_cost": 0.0
                    },
                    {
                        "id": "H7",
                        "name": "Sivaganga",
                        "latitude": 9.8470,
                        "longitude": 78.4809,
                        "demand_quantity": 1,
                        "demand_priority": "Low",
                        "availability": 20,
                        "priority_cost": 0.0
                    },
                    {
                        "id": "H8",
                        "name": "Virudhunagar",
                        "latitude": 9.5851,
                        "longitude": 77.9579,
                        "demand_quantity": 1,
                        "demand_priority": "Medium",
                        "availability": 20,
                        "priority_cost": 0.0
                    },
                    {
                        "id": "H9",
                        "name": "Salem",
                        "latitude": 11.6643,
                        "longitude": 78.1460,
                        "demand_quantity": 1,
                        "demand_priority": "High",
                        "availability": 20,
                        "priority_cost": 0.0
                    },
                    {
                        "id": "H10",
                        "name": "Namakkal",
                        "latitude": 11.2194,
                        "longitude": 78.1677,
                        "demand_quantity": 1,
                        "demand_priority": "Medium",
                        "availability": 20,
                        "priority_cost": 0.0
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
    """Update hub demand quantity and priority"""
    if hub_id == CENTRAL_HUB["id"]:
        raise HTTPException(status_code=400, detail="Cannot modify central hub")
    
    hub = next((h for h in world_state.hubs if h.id == hub_id), None)
    if not hub:
        raise HTTPException(status_code=404, detail="Hub not found")
    
    hub.demand_quantity = update_data.demand_quantity
    hub.demand_priority = update_data.demand_priority
    
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
    affected_route_id: Optional[str] = None
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
    affected_route_id = None
    affected_segment_start_idx = None
    affected_segment_end_idx = None
    snapped_coordinates = None
    
    if request.disaster_type in ["traffic", "road_block"]:
        # If route segment information is provided, use it directly
        if (request.affected_route_id is not None and 
            request.affected_segment_start_idx is not None and 
            request.affected_segment_end_idx is not None):
            # Use provided route segment information
            affected_route_id = request.affected_route_id
            affected_segment_start_idx = request.affected_segment_start_idx
            affected_segment_end_idx = request.affected_segment_end_idx
            snapped_coordinates = {"latitude": snapped_lat, "longitude": snapped_lon}
        else:
            # Find nearest active route segment
            nearest_point = None
            min_distance = float('inf')
            nearest_route_id = None
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
                        nearest_route_id = truck.id
                        nearest_segment_start_idx = i
                        nearest_segment_end_idx = i + 1
            
            # Distance threshold for snapping (in km)
            threshold = 1.0  # 1.0 km
            
            if nearest_point and min_distance <= threshold:
                snapped_lat, snapped_lon = nearest_point
                affected_route_id = nearest_route_id
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
        affected_route_id=affected_route_id,
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
        
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
