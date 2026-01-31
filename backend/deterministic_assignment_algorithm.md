# Deterministic Truck-Hub Assignment Algorithm

## Algorithm Overview

This is a three-stage deterministic algorithm for assigning hubs to trucks with strict constraints and objectives.

### Objectives (Strict Order)
1. **Primary**: Maximize number of hubs successfully served without missing deadlines
2. **Secondary**: Among solutions satisfying (1), maximize total demand_quantity delivered
3. **Tertiary**: Among solutions satisfying (1) and (2), minimize total fuel consumed

### Hard Constraints (Never Violated)
- Depot → last hub time ≤ 7.5h (return trip does NOT count)
- Depot → hub arrival time ≤ hub deadline
- Truck fuel must cover entire round trip (depot → hubs → depot)
- No zig-zag routes (directional coherence enforced)

---

## Stage 1: Feasibility Filtering

**Purpose**: Remove hubs that cannot be served under any circumstances.

**Steps**:
1. For each hub, compute:
   - `time_depot_to_hub` = time from depot to hub (using precomputed matrix)
   - `fuel_round_trip` = fuel needed for depot → hub → depot
   
2. Reject hub if:
   - `time_depot_to_hub > hub.deadline_hours` (cannot meet deadline)
   - `time_depot_to_hub > 7.5` (violates 7.5h constraint)
   - `fuel_round_trip > max(truck.fuel_capacity)` (no truck can serve it)

3. Record rejection reason for each rejected hub.

**Output**: List of feasible hubs with rejection reasons for infeasible ones.

---

## Stage 2: Directional Clustering (Zig-Zag Prevention)

**Purpose**: Group hubs into directional cones to prevent zig-zag routes.

**Zig-Zag Definition**:
- A route is invalid if angular spread of visited hubs exceeds threshold (45°)
- OR total route distance is significantly higher than serving same hubs in single directional cone

**Steps**:
1. Compute bearing for each feasible hub from depot (0-360°)
2. Group hubs into directional cones:
   - Use 45° sectors (8 sectors: 0-45°, 45-90°, ..., 315-360°)
   - Hubs on boundaries (e.g., exactly 45°) assigned deterministically (e.g., to lower sector)
   
3. For each cluster:
   - Compute cluster properties:
     - `hub_count` = number of hubs
     - `total_demand` = sum of demand_quantity
     - `angular_spread` = max(bearing) - min(bearing) in cluster
     - `avg_bearing` = mean bearing of hubs in cluster
   
4. Identify isolated clusters:
   - Clusters with only 1 hub are "isolated"
   - Isolated clusters may cause zig-zag if combined with opposite-direction clusters
   - Mark isolated clusters for special handling

5. Reject isolated hubs that cause zig-zag:
   - If isolated hub is opposite direction (>135° difference) from any other cluster
   - AND there are sufficient hubs in other clusters to maximize coverage
   - THEN reject isolated hub (unless it's the only way to increase hub count)

**Output**: List of directional clusters, each containing hubs with similar bearings.

---

## Stage 3: Route Construction & Selection

**Purpose**: Build feasible routes within clusters and select best combination.

### 3.1: Within-Cluster Route Construction

For each cluster:
1. Sort hubs by `deadline_hours` (earliest first)
2. Build routes using greedy deadline-first insertion:
   - Start with empty route
   - For each hub in sorted order:
     - Try inserting at all positions (start, between hubs, end)
     - Accept insertion if:
       - All deadlines still met
       - Depot → last hub time ≤ 7.5h
       - Fuel constraint satisfied
     - Choose insertion position that minimizes extra time (tie-breaker: fuel)
   
3. If route exceeds constraints, split into multiple routes:
   - Create new route when current route cannot accommodate next hub
   - Assign smallest sufficient truck to each route

**Output**: List of feasible routes per cluster, each route = ordered list of hub IDs.

### 3.2: Across-Cluster Selection

**Goal**: Select combination of routes that maximizes objectives.

**Algorithm**:
1. Generate all valid route combinations:
   - For each cluster, select one route (or skip cluster)
   - Ensure no hub appears in multiple routes
   - Ensure total trucks used ≤ available trucks

2. For each combination, compute:
   - `hubs_served` = total unique hubs in all routes
   - `total_demand` = sum of demand_quantity for served hubs
   - `total_fuel` = sum of fuel consumed for all routes

3. Select best combination using lexicographic ordering:
   - **Primary**: Maximize `hubs_served`
   - **Secondary**: Among ties, maximize `total_demand`
   - **Tertiary**: Among ties, minimize `total_fuel`

4. Assign trucks:
   - For each selected route, assign smallest truck that can serve it
   - Use deterministic tie-breaking (e.g., truck ID order)

**Output**: Final assignment: routes → trucks, with metrics.

---

## Deterministic Tie-Breaking Rules

1. **Hub ordering**: Sort by `(deadline_hours, hub_id)` (lexicographic)
2. **Route selection**: Sort by `(hubs_served, total_demand, -total_fuel, route_id)`
3. **Truck assignment**: Sort trucks by `(fuel_capacity, truck_id)` (smallest first)

---

## Complexity Analysis

- **Stage 1**: O(m) where m = number of hubs
- **Stage 2**: O(m) for bearing computation + O(m) for clustering = O(m)
- **Stage 3.1**: O(m × m) for route construction within clusters
- **Stage 3.2**: O(2^c × m) where c = number of clusters (worst case, but c << m)

**Total**: O(m²) in practice, scales well for m ≤ 50, n ≤ 20.

---

## Edge Cases Handled

1. **Two hubs opposite directions, both urgent**: Algorithm selects one (based on demand/fuel), not zig-zag
2. **One far hub with huge demand vs multiple nearby small hubs**: Secondary objective (demand) decides
3. **Fewer trucks than feasible hubs**: Algorithm selects best subset
4. **Multiple hubs with identical deadlines**: Tie-breaking by hub_id ensures determinism
5. **Hub feasible by time but not by fuel**: Rejected in Stage 1
6. **All hubs infeasible**: Returns empty plan with rejection reasons

---

## Why Zig-Zag is Prevented

1. **Directional clustering**: Hubs are grouped by bearing, ensuring routes stay within directional cones
2. **Isolated hub rejection**: Isolated hubs opposite to other clusters are rejected unless necessary
3. **Route construction**: Within-cluster routes maintain directional coherence
4. **Angular spread check**: Routes exceeding 45° angular spread are invalid

---

## Optimality Under Constraints

- **Primary objective**: Algorithm is optimal - it tries all valid combinations and selects maximum hubs served
- **Secondary objective**: Optimal among solutions satisfying primary - selects maximum demand
- **Tertiary objective**: Optimal among solutions satisfying primary and secondary - selects minimum fuel

The algorithm is **deterministic** (same input → same output) and **explainable** (every decision has a recorded reason).
