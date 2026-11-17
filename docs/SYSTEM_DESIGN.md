# System Design Explanation

## Architecture Overview

The system follows a client-server architecture with a Python FastAPI backend and React frontend, communicating via REST API with polling-based state synchronization.

### Hosted demo variant

The live demo (https://optiflow-dro.vercel.app) keeps this same architecture but moves the "server" into the browser: the unmodified backend runs in a web worker on Pyodide (WebAssembly) and the frontend's API calls are routed to it instead of `http://localhost:8000`. The simulation loop body is exposed as `simulation_tick()` so the worker can drive it without a thread. Details: [DEPLOYMENT.md](DEPLOYMENT.md).

## Backend Design

### State Management
- **Single Global State**: `WorldState` object holds all simulation data in memory
- **No Persistence**: Designed for demo/prototype - restart loses state
- **Thread-Safe Simulation**: Background thread runs simulation loop independently (each step is `simulation_tick()`; the hosted demo calls it from a worker timer instead of a thread)

### Simulation Engine
- **Time-Based Loop**: Advances simulation every 1 second
- **Incremental Movement**: Trucks move step-by-step along route waypoints
- **Resource Tracking**: Fuel decreases with distance, fatigue increases with time
- **Event-Driven Updates**: Disruptions modify speed and fuel consumption in real-time

### AI Decision Engine
The AI makes routing decisions based on:
1. **Route Quality Analysis**: Calculates distance, affected segments, speed/fuel multipliers
2. **Risk Assessment**: Evaluates delay risk and fuel impact
3. **Priority Weighting**: Emergency > High > Medium > Low
4. **Alternative Evaluation**: Compares current route vs. alternatives

**Decision Output**: WAIT, REROUTE, or CONTINUE with human-readable explanation

### Route Calculation
- **Simplified Routing**: Straight-line paths with intermediate waypoints (20 points)
- **Production Alternative**: Would use OSRM/GraphHopper for real road networks
- **Dynamic Updates**: Routes recalculated when disruptions occur

## Frontend Design

### Map Visualization
- **MapLibre GL JS**: Modern WebGL-based mapping
- **OpenStreetMap Tiles**: Free, no API keys required
- **Real-Time Updates**: Polls backend every second for state changes
- **Marker Management**: Dynamic creation/removal of hubs, trucks, routes

### Role-Based UI
- **Manager View**: Full system control, all trucks visible, disruption toggles
- **Driver View**: Single truck focus, personalized instructions, condition alerts
- **State Synchronization**: Frontend is purely presentational - all logic in backend

### Visual Design
- **Color Coding**: Hubs by priority (Low=black, Medium=green, High=blue, Emergency=red)
- **Smooth Animation**: Trucks move incrementally, routes update dynamically
- **AI Explanations**: Real-time decision explanations displayed in UI

## Data Flow

1. **Initialization**: CSV uploads populate hubs and trucks
2. **Simulation Start**: Backend begins time loop, assigns trucks to hubs
3. **Movement**: Each second, trucks advance along routes
4. **AI Evaluation**: Before each move, AI evaluates route and makes decision
5. **State Update**: Backend updates world state
6. **Frontend Poll**: Frontend fetches state and re-renders map
7. **Disruption Handling**: User toggles disruptions → AI recalculates → routes update

## Key Design Decisions

1. **In-Memory State**: Simpler for prototype, no database overhead
2. **Polling vs WebSockets**: Polling is easier to implement, WebSockets better for production
3. **Straight-Line Routes**: Visual clarity over geographic accuracy for demo
4. **Greedy Assignment**: Trucks assigned to highest priority hub (no global optimization)
5. **Explainable AI**: Simple rule-based logic with clear explanations (not black box)

## Scalability Considerations

**Current Limitations**:
- Single-threaded simulation (could parallelize truck updates)
- Polling overhead (WebSockets would be better)
- No horizontal scaling (single backend instance)

**Production Improvements**:
- Database for persistence
- Message queue for event handling
- WebSocket connections
- Real road network routing
- Multi-objective optimization algorithms
- Caching and CDN for frontend

## Security Considerations

**Prototype**: No authentication, no validation (demo only)

**Production Needs**:
- User authentication/authorization
- Input validation and sanitization
- Rate limiting
- CORS configuration
- API key management
- Data encryption

