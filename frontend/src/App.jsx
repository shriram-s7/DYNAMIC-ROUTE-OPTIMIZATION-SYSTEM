import React, { useState, useEffect, useRef } from 'react';
import maplibregl from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import axios from 'axios'
import './index.css'

const API_BASE = 'http://localhost:8000'
function createTruckElement() {
  const wrapper = document.createElement('div');

  // Marker root (NEVER rotate this)
  wrapper.style.width = '56px';
  wrapper.style.height = '56px';
  wrapper.style.display = 'flex';
  wrapper.style.alignItems = 'center';
  wrapper.style.justifyContent = 'center';
  wrapper.style.pointerEvents = 'none';
  wrapper.style.transform = 'translateZ(0)';

  wrapper.innerHTML = `
    <div style="
  width: 34px;
  height: 34px;
  background-color: #E3F2FD;
  border-radius: 50%;
  border: 3px solid #2196F3;
  display: flex;
  justify-content: center;
  align-items: center;
  overflow: hidden;
  box-shadow: 0 2px 6px rgba(0,0,0,0.15);
">
  <div style="
    width: 20px;
    height: 17px;
    background-color: #1976D2;
    border-radius: 4px 4px 0 0;
    display: flex;
    flex-direction: column;
    align-items: center;
    position: relative;
    top: -3px;
  ">
    <!-- Windshield -->
    <div style="
      width: 80%;
      height: 6px;
      background-color: #B3E5FC;
      margin-top: 1px;
      border-radius: 2px;
      border: 1px solid #0D47A1;
      box-sizing: border-box;
    "></div>

    <!-- Mid section -->
    <div style="
      display: flex;
      justify-content: space-evenly;
      align-items: center;
      width: 100%;
      flex-grow: 1;
      padding: 0 2px;
      box-sizing: border-box;
    ">
      <!-- Left headlight -->
      <div style="
        width: 4px;
        height: 4px;
        background-color: #FFEB3B;
        border-radius: 50%;
        border: 1px solid #FBC02D;
      "></div>

      <!-- Grille -->
      <div style="
        width: 8px;
        height: 6px;
        background-color: #546E7A;
        border-radius: 1px;
        border: 1px solid #37474F;
        background-image: repeating-linear-gradient(
          to bottom,
          #CFD8DC,
          #CFD8DC 2px,
          transparent 2px,
          transparent 4px
        );
      "></div>

      <!-- Right headlight -->
      <div style="
        width: 4px;
        height: 4px;
        background-color: #FFEB3B;
        border-radius: 50%;
        border: 1px solid #FBC02D;
      "></div>
    </div>

    <!-- Bumper -->
    <div style="
      width: 110%;
      height: 3px;
      background-color: #78909C;
      position: absolute;
      bottom: -1px;
      border-radius: 2px;
      border-top: 1px solid #455A64;
    "></div>

    <!-- Tires -->
    <div style="
      position: absolute;
      bottom: -3px;
      width: 100%;
      display: flex;
      justify-content: space-between;
      padding: 0 2px;
      box-sizing: border-box;
    ">
      <div style="
        width: 5px;
        height: 3px;
        background-color: #212121;
        border-radius: 2px;
        border: 1px solid #424242;
      "></div>
      <div style="
        width: 5px;
        height: 3px;
        background-color: #212121;
        border-radius: 2px;
        border: 1px solid #424242;
      "></div>
    </div>
  </div>
</div>

  `;

  return wrapper;
}
// Haversine formula to calculate distance between two lat/lon points in km
const haversine = (lat1, lon1, lat2, lon2) => {
  const R = 6371; // Earth's radius in km
  const dLat = (lat2 - lat1) * Math.PI / 180;
  const dLon = (lon2 - lon1) * Math.PI / 180;
  const a = 
    Math.sin(dLat / 2) * Math.sin(dLat / 2) +
    Math.cos(lat1 * Math.PI / 180) * Math.cos(lat2 * Math.PI / 180) * 
    Math.sin(dLon / 2) * Math.sin(dLon / 2);
  const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
  return R * c; // Distance in km
}

// Calculate the shortest distance from a point to a line segment
const pointToLineDistance = (lat, lon, lineStartLat, lineStartLon, lineEndLat, lineEndLon) => {
  // Vector from start to end of line segment
  const lineVecX = lineEndLon - lineStartLon;
  const lineVecY = lineEndLat - lineStartLat;
  
  // Vector from start of line to point
  const pointVecX = lon - lineStartLon;
  const pointVecY = lat - lineStartLat;
  
  // Calculate line length squared
  const lineLenSq = lineVecX * lineVecX + lineVecY * lineVecY;
  
  if (lineLenSq === 0) {
    // Line segment is actually a point
    return haversine(lat, lon, lineStartLat, lineStartLon);
  }
  
  // Calculate projection of point onto line
  let t = (pointVecX * lineVecX + pointVecY * lineVecY) / lineLenSq;
  t = Math.max(0, Math.min(1, t)); // Clamp t to [0, 1]
  
  // Calculate closest point on the line segment
  const closestLon = lineStartLon + t * lineVecX;
  const closestLat = lineStartLat + t * lineVecY;
  
  // Calculate distance from point to closest point on line
  return haversine(lat, lon, closestLat, closestLon);
}

function App() {
  const [role, setRole] = useState('manager')
  const [worldState, setWorldState] = useState(null)
  const [selectedTruck, setSelectedTruck] = useState(null)  // For driver follow mode
  const [driverTruckId, setDriverTruckId] = useState(null)  // For driver perspective mode
  const [instructionText, setInstructionText] = useState('')  // For manager to send instructions
  
  // Disaster management state
  const [disasterType, setDisasterType] = useState('rain')  // Current disaster type
  const [disasterRadius, setDisasterRadius] = useState(5)  // Radius in km
  const [placementMode, setPlacementMode] = useState(false)  // Placement mode active
  
  // Mode state for manager UI
  const [activeMode, setActiveMode] = useState('monitoring'); // 'monitoring', 'disaster', 'truck_focus', 'instruction'
  
  // State to track if simulation has started
  const [simulationStarted, setSimulationStarted] = useState(false)
  const [commitError, setCommitError] = useState(null)
  
  // Simulation control state
  const [simSpeed, setSimSpeed] = useState(1.0)
  const [simPaused, setSimPaused] = useState(false)
  const [showStopOverlay, setShowStopOverlay] = useState(false)
  const [simulationTerminated, setSimulationTerminated] = useState(false)

  const mapContainer = useRef(null)
  const map = useRef(null)

  // persistent markers
  const markers = useRef({
    hubs: {},
    trucks: {},
    destinations: {}
  })

  // Hub creation/editing state
  const [hubModal, setHubModal] = useState({
    show: false,
    mode: 'create', // 'create' or 'edit'
    hub: null,
    lat: null,
    lng: null
  })

  // Add Hub mode toggle (Manager only) - only available before start
  const [addHubMode, setAddHubMode] = useState(false)

  /* =========================
     MAP INITIALIZATION
  ========================== */
  useEffect(() => {
    if (map.current) return

    map.current = new maplibregl.Map({
      container: mapContainer.current,
      style: {
        version: 8,
        sources: {
          osm: {
            type: 'raster',
            tiles: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'],
            tileSize: 256,
            attribution: '© OpenStreetMap contributors'
          }
        },
        layers: [
          {
            id: 'osm-layer',
            type: 'raster',
            source: 'osm'
          }
        ]
      },
      center: [78.9629, 20.5937],
      zoom: 5
    })

    return () => {
      if (map.current) {
        map.current.remove()
      }
    }
  }, [])

  // Separate effect to handle map clicks (updates when role, addHubMode, placementMode, disasterType, activeMode, or worldState changes)
  useEffect(() => {
    if (!map.current) return

    const handleMapClick = (e) => {
      console.log('Map click detected, placementMode:', placementMode, 'role:', role);
      
      // In driver perspective mode, allow map panning but don't process clicks
      if (role === 'driver_perspective') {
        return;
      }
      
      // If placement mode is active, intercept clicks for disaster placement
      if (role === 'manager' && placementMode && simulationStarted && activeMode === 'disaster') {
        console.log('Processing disaster placement click');
        
        if (disasterType === 'rain') {
          // Rain: place directly at click location
          createDisaster(e.lngLat.lat, e.lngLat.lng);
        } else {
          // Traffic & Road Block: snap to nearest active truck route
          const clickedLat = e.lngLat.lat;
          const clickedLng = e.lngLat.lng;
          
          // Find nearest active truck route segment
          let nearestPoint = null;
          let minDistance = Infinity;
          let nearestTruckId = null;
          let nearestSegmentStartIdx = null;
          let nearestSegmentEndIdx = null;
          
          worldState.trucks.forEach(truck => {
            // Prefer full_route over route when available
            const route = truck.full_route || truck.route;
            
            if (route && route.length > 1) {
              // Check each segment of the route
              for (let i = 0; i < route.length - 1; i++) {
                const start = route[i];
                const end = route[i + 1];
                
                // Calculate distance from clicked point to this segment
                const distance = pointToLineDistance(clickedLat, clickedLng, start.latitude, start.longitude, end.latitude, end.longitude);
                
                if (distance < minDistance) {
                  minDistance = distance;
                  nearestPoint = {
                    latitude: clickedLat,
                    longitude: clickedLng
                  };
                  nearestTruckId = truck.id;
                  nearestSegmentStartIdx = i;
                  nearestSegmentEndIdx = i + 1;
                }
              }
            }
          });
          
          // Distance threshold for snapping (in km)
          const threshold = 1.0; // 1.0 km
          
          if (nearestPoint && minDistance <= threshold) {
            console.log('Snapped to route segment:', minDistance, 'km away');
            createDisaster(nearestPoint.latitude, nearestPoint.longitude, nearestTruckId, nearestSegmentStartIdx, nearestSegmentEndIdx);
          } else {
            console.log('Failed to snap to route, distance:', minDistance, 'km');
            alert('Click directly on an active route');
          }
        }
        return; // Exit early to prevent other handlers
      }
      
      if (role === 'manager' && addHubMode && !simulationStarted) {
        setHubModal({
          show: true,
          mode: 'create',
          hub: null,
          lat: e.lngLat.lat,
          lng: e.lngLat.lng
        })
      }
    }

    map.current.on('click', handleMapClick)

    return () => {
      if (map.current) {
        map.current.off('click', handleMapClick)
      }
    }
  }, [role, addHubMode, placementMode, disasterType, activeMode, worldState, simulationStarted])

  // State for driver perspective navigation
  const [driverAutoFollow, setDriverAutoFollow] = useState(true);
  const [driverFollowTimeout, setDriverFollowTimeout] = useState(null);
useEffect(() => {
  if (role === 'driver') {
    // Entering Driver Follow mode
    setDriverTruckId(null);      // MUST reset driver view selection
    setDriverAutoFollow(false);  // Prevent leftover camera control
  }

  if (role === 'driver_perspective') {
    // Entering Driver View mode
    setSelectedTruck(null);      // Driver Follow selection irrelevant here
  }

  if (role === 'manager') {
    // Manager mode should be clean
    setSelectedTruck(null);
    setDriverTruckId(null);
    setDriverAutoFollow(false);
  }
}, [role]);

  // Effect to handle map interaction for driver perspective auto-follow pause
  useEffect(() => {
    if (!map.current || role !== 'driver_perspective') return;
    
    const handleMapMove = () => {
      if (driverAutoFollow) {
        // Pause auto-follow when user pans the map
        setDriverAutoFollow(false);
        
        // Clear any existing timeout
        if (driverFollowTimeout) {
          clearTimeout(driverFollowTimeout);
        }
        
        // Set timeout to automatically recenter after 7 seconds
        const timeout = setTimeout(() => {
          setDriverAutoFollow(true);
          setDriverFollowTimeout(null);
        }, 7000);
        
        setDriverFollowTimeout(timeout);
      }
    };
    
    // Add event listeners
    map.current.on('drag', handleMapMove);
    map.current.on('zoom', handleMapMove);
    map.current.on('rotate', handleMapMove);
    
    return () => {
      // Remove event listeners
      if (map.current) {
        map.current.off('drag', handleMapMove);
        map.current.off('zoom', handleMapMove);
        map.current.off('rotate', handleMapMove);
      }
      
      // Clear timeout if it exists
      if (driverFollowTimeout) {
        clearTimeout(driverFollowTimeout);
      }
    };
  }, [role, driverAutoFollow, driverFollowTimeout]);
  
  /* =========================
     POLL BACKEND STATE (ALWAYS ON)
  ========================== */
  useEffect(() => {
    const interval = setInterval(async () => {
      try {
        const res = await axios.get(`${API_BASE}/state`)
        setWorldState(res.data)
      } catch (e) {
        console.error(e)
      }
    }, 1000)

    return () => clearInterval(interval)
  }, [])

  /* =========================
     MAP RENDERING
  ========================== */
  useEffect(() => {
    if (!map.current || !worldState) return

    /* -------- HUBS -------- */
    // --- CLEANUP DELETED HUB MARKERS ---
    const liveHubIds = new Set(worldState.hubs.map(h => h.id));
    
    Object.keys(markers.current.hubs).forEach(hubId => {
      if (!liveHubIds.has(hubId)) {
        markers.current.hubs[hubId].remove();
        delete markers.current.hubs[hubId];
      }
    });
    
    worldState.hubs.forEach(hub => {
      let marker = markers.current.hubs[hub.id]
      
      // Determine if hub should be visible based on role
      const isDestinationHub = role === 'driver_perspective' && driverTruckId && worldState.trucks && 
        worldState.trucks.some(truck => 
          truck.id === driverTruckId && 
          truck.current_task && 
          truck.current_task.hub_id === hub.id
        );
      const isCentralHub = hub.id === 'CENTRAL_DEPOT';
      const isDeliveredHub = hub.delivered || hub.demand_quantity === 0;
      const isVisible = role !== 'driver_perspective' || isDestinationHub || isCentralHub || isDeliveredHub;
      
      // Create marker if it doesn't exist
      if (!marker) {
        const el = document.createElement('div')
        el.style.zIndex = '1000'
        el.style.display = 'flex'
        el.style.alignItems = 'center'
        el.style.justifyContent = 'center'
        el.style.cursor = 'pointer'
        
        // CENTRAL HUB - Green circle container
        if (hub.id === 'CENTRAL_DEPOT') {
          el.innerHTML = '';
          el.style.width = '64px';
          el.style.height = '64px';
          el.style.background = '#2ecc71'; // green
          el.style.borderRadius = '50%';
          el.style.border = '4px solid #ffffff';
          el.style.boxShadow = '0 0 20px rgba(46,204,113,0.9)';
          el.style.display = 'flex';
          el.style.alignItems = 'center';
          el.style.justifyContent = 'center';
          el.title = 'Central Depot';

          // inner ring for container feel
          const inner = document.createElement('div');
          inner.style.width = '42px';
          inner.style.height = '42px';
          inner.style.borderRadius = '50%';
          inner.style.border = '2px dashed rgba(255,255,255,0.8)';
          el.appendChild(inner);
        }
        // DELIVERED HUB - Green check icon (remains visible)
        else if (hub.delivered || hub.demand_quantity === 0) {
          el.innerHTML = '✅'
          el.style.fontSize = '24px'
          el.style.width = '30px'
          el.style.height = '30px'
          el.style.background = '#28a745'
          el.style.border = '2px solid #ffffff'
          el.style.borderRadius = '50%'
          el.style.boxShadow = '0 0 8px rgba(40,167,69,0.6)'
          el.title = `${hub.name} - Delivered (Completed)`
        }
        // NORMAL HUB - Blue warehouse/package icon
        else {
          el.innerHTML = '📦'
          el.style.fontSize = '24px'
          el.style.width = '30px'
          el.style.height = '30px'
          el.style.background = '#007bff'
          el.style.border = '2px solid #ffffff'
          el.style.borderRadius = '50%'
          el.style.boxShadow = '0 0 8px rgba(0,123,255,0.6)'
          el.title = `${hub.name} - ${hub.demand_priority} Priority`
        }
        
        // Set visibility based on role
        el.style.display = isVisible ? 'flex' : 'none';
        
        marker = new maplibregl.Marker(el)
          .setLngLat([hub.longitude, hub.latitude])
          .addTo(map.current)
        // Add click handler for editing hubs (Manager role only)
        if (hub.id !== 'CENTRAL_DEPOT') {
          el.addEventListener('click', (e) => {
            e.stopPropagation()
            if (role === 'manager') {
              setHubModal({
                show: true,
                mode: 'edit',
                hub: hub,
                lat: hub.latitude,
                lng: hub.longitude
              })
            }
          })
        }
        
        markers.current.hubs[hub.id] = marker
      } else {
        // Update existing marker if hub properties changed
        const el = marker.getElement()
        
        // Always update position for all hubs (including central hub)
        marker.setLngLat([hub.longitude, hub.latitude])
        
        // For central hub, make sure it always has the correct appearance
        if (hub.id === 'CENTRAL_DEPOT') {
          // Ensure central hub always has correct appearance
          el.innerHTML = '';
          el.style.width = '48px';
          el.style.height = '48px';
          el.style.background = '#2ecc71'; // green
          el.style.borderRadius = '50%';
          el.style.border = '4px solid #ffffff';
          el.style.boxShadow = '0 0 20px rgba(46,204,113,0.9)';
          el.style.display = 'flex';
          el.style.alignItems = 'center';
          el.style.justifyContent = 'center';
          el.title = 'Central Depot';

          // inner ring for container feel
          const inner = document.createElement('div');
          inner.style.width = '30px';
          inner.style.height = '30px';
          inner.style.borderRadius = '50%';
          inner.style.border = '2px dashed rgba(255,255,255,0.8)';
          el.appendChild(inner);
        }
        // For non-central hubs, update based on delivered status
        else if (hub.delivered || hub.demand_quantity === 0) {
          el.innerHTML = '✅'
          el.style.fontSize = '24px'
          el.style.width = '30px'
          el.style.height = '30px'
          el.style.background = '#28a745'
          el.style.border = '2px solid #ffffff'
          el.style.borderRadius = '50%'
          el.style.boxShadow = '0 0 8px rgba(40,167,69,0.6)'
          el.title = `${hub.name} - Delivered (Completed)`
        } else {
          el.innerHTML = '📦'
          el.style.fontSize = '24px'
          el.style.width = '30px'
          el.style.height = '30px'
          el.style.background = '#007bff'
          el.style.border = '2px solid #ffffff'
          el.style.borderRadius = '50%'
          el.style.boxShadow = '0 0 8px rgba(0,123,255,0.6)'
          el.title = `${hub.name} - ${hub.demand_priority} Priority`
        }
        
        // Update visibility based on role
        const isDestinationHub = role === 'driver_perspective' && driverTruckId && worldState.trucks && 
          worldState.trucks.some(truck => 
            truck.id === driverTruckId && 
            truck.current_task && 
            truck.current_task.hub_id === hub.id
          );
        const isCentralHub = hub.id === 'CENTRAL_DEPOT';
        const isDeliveredHub = hub.delivered || hub.demand_quantity === 0;
        const isVisible = role !== 'driver_perspective' || isDestinationHub || isCentralHub || isDeliveredHub;
        el.style.display = isVisible ? 'flex' : 'none';
      }
    })

    /* -------- TRUCKS -------- */
    worldState.trucks.forEach(truck => {
      // Check if this truck should be visible based on role
      // DO NOT REMOVE markers - only show/hide them
      const isDriverTruck = driverTruckId === truck.id && role === 'driver_perspective';
      const isVisible = role !== 'driver_perspective' || isDriverTruck;
      
      if (!markers.current.trucks[truck.id]) {
        const el = createTruckElement();
        
        // If truck is NOT active yet, position it inside central hub
        let positionLng, positionLat;
        if (!truck.active) {
          const centralHub = worldState.hubs.find(h => h.id === 'CENTRAL_DEPOT');
          if (centralHub) {
            // spread trucks slightly inside the hub circle
            const index = worldState.trucks.findIndex(t => t.id === truck.id);
            const angle = (index / worldState.trucks.length) * Math.PI * 2;
            const radius = 0.00015; // small offset (~15m)

            positionLng = centralHub.longitude + Math.cos(angle) * radius;
            positionLat = centralHub.latitude + Math.sin(angle) * radius;
          } else {
            // fallback to actual position if central hub not found
            positionLng = truck.current_longitude;
            positionLat = truck.current_latitude;
          }
        } else {
          // once active → real movement
          positionLng = truck.current_longitude;
          positionLat = truck.current_latitude;
        }
        
        markers.current.trucks[truck.id] = new maplibregl.Marker({
          element: el,
          anchor: 'center'
        })
          .setLngLat([positionLng, positionLat])
          .addTo(map.current);
      } else {
        // If truck is NOT active yet, keep it inside central hub
        if (!truck.active) {
          const centralHub = worldState.hubs.find(h => h.id === 'CENTRAL_DEPOT');
          if (centralHub) {
            // spread trucks slightly inside the hub circle
            const index = worldState.trucks.findIndex(t => t.id === truck.id);
            const angle = (index / worldState.trucks.length) * Math.PI * 2;
            const radius = 0.00015; // small offset (~15m)

            const offsetLng = centralHub.longitude + Math.cos(angle) * radius;
            const offsetLat = centralHub.latitude + Math.sin(angle) * radius;

            markers.current.trucks[truck.id].setLngLat([offsetLng, offsetLat]);
          }
        } else {
          // once active → real movement
          markers.current.trucks[truck.id]
            .setLngLat([truck.current_longitude, truck.current_latitude])
        }
        
        // Update visibility based on role - show all in manager mode, only assigned truck in driver perspective
        const el = markers.current.trucks[truck.id].getElement()
        if (el) {
          const shouldBeVisible = role !== 'driver_perspective' || isDriverTruck;
          el.style.display = shouldBeVisible ? 'flex' : 'none';
        }
      }

      // ROUTE LINE
      if (truck.full_route && truck.full_route.length > 1) {
        const routeId = `route-${truck.id}`
        
        // Check if this truck is selected for follow mode (driver role)
        const isFollowedTruck = selectedTruck === truck.id && role === 'driver'
        
        // Check if this truck is the driver's assigned truck (driver perspective mode)
        const isDriverTruck = driverTruckId === truck.id && role === 'driver_perspective'
        
        // Define styling based on role
        let lineColor, lineWidth, lineDashArray, lineOpacity, showRoute;
        if (role === 'driver_perspective') {
          // Driver perspective mode: only show the assigned truck's route
          if (isDriverTruck) {
            // Driver's truck route: bright red for high contrast navigation
            lineColor = '#FF0000';  // Bright red for high contrast
            lineWidth = 8;  // Thicker for visibility
            lineDashArray = [1, 0];
            lineOpacity = 0.95;  // Higher opacity
            showRoute = true;
          } else {
            // Hide other trucks' routes in driver perspective mode
            lineColor = '#000000';
            lineWidth = 0;
            lineDashArray = [1, 0];
            lineOpacity = 0;
            showRoute = false;
          }
        } else if (role === 'manager') {
          // Manager mode: show all active truck routes with consistent styling
          lineColor = '#007bff';  // Consistent blue color for all routes
          lineWidth = 2;  // Consistent thickness
          lineDashArray = [1, 0];  // Solid line
          lineOpacity = 0.6;  // Consistent opacity
          showRoute = true;
        } else if (isFollowedTruck) {
          // Driver follow mode: red, thick, solid
          lineColor = '#ff0000';
          lineWidth = 4;
          lineDashArray = [1, 0];
          lineOpacity = 0.9;
          showRoute = true;
        } else {
          // Non-focused: muted color, thin, dashed
          lineColor = '#888888';
          lineWidth = 1;
          lineDashArray = [2, 2];
          lineOpacity = 0.4;
          showRoute = true;
        }
        
        const geojson = {
          type: 'Feature',
          geometry: {
            type: 'LineString',
            coordinates: truck.full_route.map(p => [
              p.longitude,
              p.latitude
            ])
          }
        }

        if (map.current.getSource(routeId)) {
          if (showRoute) {
            map.current.getSource(routeId).setData(geojson)
          } else {
            // Clear the route data to hide it
            map.current.getSource(routeId).setData({
              type: 'FeatureCollection',
              features: []
            })
          }
        } else {
          if (showRoute) {
            map.current.addSource(routeId, {
              type: 'geojson',
              data: geojson
            })

            map.current.addLayer({
              id: routeId,
              type: 'line',
              source: routeId,
              paint: {
                'line-color': lineColor,
                'line-width': lineWidth,
                'line-dasharray': lineDashArray,
                'line-opacity': lineOpacity
              }
            })
          }
        }
        
        // Update layer style based on role and focus status
        if (map.current.getLayer(routeId)) {
          if (showRoute) {
            map.current.setPaintProperty(routeId, 'line-color', lineColor);
            map.current.setPaintProperty(routeId, 'line-width', lineWidth);
            map.current.setPaintProperty(routeId, 'line-dasharray', lineDashArray);
            map.current.setPaintProperty(routeId, 'line-opacity', lineOpacity);
          } else {
            // Hide the route by setting opacity to 0
            map.current.setPaintProperty(routeId, 'line-opacity', 0);
          }
        }
      }
      
      // DESTINATION HIGHLIGHTING FOR SELECTED TRUCKS
      if (role === 'driver_perspective' && driverTruckId === truck.id && truck.current_task) {
        // Driver perspective mode: highlight the assigned truck's destination
        const destinationHub = worldState.hubs.find(h => h.id === truck.current_task.hub_id);
        if (destinationHub) {
          const destMarkerId = `dest-${truck.id}`;
          
          // Use bright red color for the driver's destination
          const destColor = '#FF0000';
                  
          
          
          // Remove existing destination marker if it exists
          if (markers.current.destinations?.[destMarkerId]) {
            markers.current.destinations[destMarkerId].remove();
          }
          
          // Initialize destinations markers if needed
          if (!markers.current.destinations) {
            markers.current.destinations = {};
          }
          
          // Create new destination marker with default marker
          markers.current.destinations[destMarkerId] = new maplibregl.Marker()
            .setLngLat([destinationHub.longitude, destinationHub.latitude])
            .addTo(map.current);
        }
      } else {
        // Remove destination marker if truck is no longer focused or has no current task
        const destMarkerId = `dest-${truck.id}`;
        if (markers.current.destinations?.[destMarkerId]) {
          markers.current.destinations[destMarkerId].remove();
          delete markers.current.destinations[destMarkerId];
        }
      }
    })

    // Remove all existing disaster layers and sources before rendering new ones
    if (map.current) {
      const allLayers = map.current.getStyle().layers || [];
      allLayers.forEach(layer => {
        if (layer.id.startsWith('disaster-layer-')) {
          const sourceId = layer.id.replace('disaster-layer-', 'disaster-source-');
          if (map.current.getLayer(layer.id)) {
            map.current.removeLayer(layer.id);
          }
          if (map.current.getSource(sourceId)) {
            map.current.removeSource(sourceId);
          }
        }
      });
    }

    // Render disasters if they exist
    if (worldState?.disasters && worldState.disasters.length > 0) {
      worldState.disasters.forEach(disaster => {
        const disasterId = `disaster-${disaster.id}`;
        const layerId = `disaster-layer-${disaster.id}`;
        const sourceId = `disaster-source-${disaster.id}`;
        
        // Handle different disaster types with appropriate geometry
        let geojsonData;
        
        if (disaster.disaster_type === 'rain') {
          // Rain: Render as circular polygon (original behavior)
          const points = [];
          const sides = 64; // Number of sides for the circle approximation
          for (let i = 0; i <= sides; i++) {
            const angle = (i / sides) * 2 * Math.PI;
            const lat = disaster.latitude + (disaster.radius_km / 111) * Math.cos(angle); // Approximate conversion
            const lng = disaster.longitude + (disaster.radius_km / (111 * Math.cos(disaster.latitude * Math.PI / 180))) * Math.sin(angle);
            points.push([lng, lat]);
          }
          
          geojsonData = {
            type: 'Feature',
            geometry: {
              type: 'Polygon',
              coordinates: [points]
            },
            properties: {
              disaster_type: disaster.disaster_type
            }
          };
        } else {
          // Traffic or Road Block: Render as line overlay on the affected route segment
          // Find the affected truck and route
          const affectedTruck = worldState.trucks.find(t => t.id === disaster.affected_route_id);
          if (affectedTruck && disaster.affected_segment_start_idx !== null && disaster.affected_segment_end_idx !== null) {
            // Get the start and end points of the affected segment
            const route = affectedTruck.full_route || affectedTruck.route;
            if (route && route.length > disaster.affected_segment_start_idx && route.length > disaster.affected_segment_end_idx) {
              const startPoint = route[disaster.affected_segment_start_idx];
              const endPoint = route[disaster.affected_segment_end_idx];
              
              geojsonData = {
                type: 'Feature',
                geometry: {
                  type: 'LineString',
                  coordinates: [
                    [startPoint.longitude, startPoint.latitude],
                    [endPoint.longitude, endPoint.latitude]
                  ]
                },
                properties: {
                  disaster_type: disaster.disaster_type
                }
              };
            }
          }
        }
        
        // Add new source if geojsonData exists
        if (geojsonData) {
          map.current.addSource(sourceId, {
            type: 'geojson',
            data: geojsonData
          });
        }

        // Add new layer with appropriate styling based on disaster type
        if (geojsonData) {
          let layerType, paintProps;
          if (disaster.disaster_type === 'rain') {
            // Rain: Fill polygon with translucent color
            layerType = 'fill';
            paintProps = {
              'fill-color': disaster.disaster_type === 'rain' ? 'rgba(52, 152, 219, 0.3)' : 
                           disaster.disaster_type === 'traffic' ? 'rgba(243, 156, 18, 0.4)' : 
                           'rgba(231, 76, 60, 0.4)',
              'fill-outline-color': disaster.disaster_type === 'rain' ? '#3498db' : 
                                  disaster.disaster_type === 'traffic' ? '#f39c12' : 
                                  '#e74c3c',
              'fill-opacity': 0.4
            };
          } else {
            // Traffic/Road Block: Line overlay
            layerType = 'line';
            paintProps = {
              'line-color': disaster.disaster_type === 'traffic' ? '#f39c12' : '#e74c3c',
              'line-width': disaster.disaster_type === 'traffic' ? 8 : 10,
              'line-opacity': disaster.disaster_type === 'traffic' ? 0.6 : 0.8,
              'line-dasharray': disaster.disaster_type === 'traffic' ? [2, 2] : [1, 0]  // Dashed for traffic, solid for road block
            };
          }

          map.current.addLayer({
            id: layerId,
            type: layerType,
            source: sourceId,
            paint: paintProps
          });
        }
      });
    }

  }, [worldState])

  // Effect for follow mode - center map on selected truck when in driver role
  useEffect(() => {
    if (role === 'driver' && selectedTruck && worldState && map.current) {
      const truck = worldState.trucks.find(t => t.id === selectedTruck);
      if (truck) {
        // Center the map on the truck and maintain tight zoom
        map.current.flyTo({
          center: [truck.current_longitude, truck.current_latitude],
          zoom: 12,
          duration: 500  // Shorter duration for smoother following
        });
      }
    }
  }, [role, selectedTruck, worldState]);



  // Effect for driver mode - auto-follow the assigned truck (NOT for driver_perspective)
  useEffect(() => {
    // Only run for driver role, not driver_perspective (which is handled separately)
    if (role !== 'driver' || !driverTruckId || selectedTruck !== null || !worldState || !map.current || !driverAutoFollow) return;
    
    const truck = worldState.trucks.find(t => t.id === driverTruckId);
    
    if (truck && truck.full_route && truck.full_route.length > 1) {
      // Calculate bearing from route if available
      let bearing = 0;
      
      // Find the next point in the route after the current position
      if (truck.full_route.length > 1) {
        // Find the closest point in the route to current position
        let closestIndex = 0;
        let minDistance = Infinity;
        
        for (let i = 0; i < truck.full_route.length; i++) {
          const point = truck.full_route[i];
          const dLat = (point.latitude - truck.current_latitude) * Math.PI / 180;
          const dLon = (point.longitude - truck.current_longitude) * Math.PI / 180;
          const a = 
            Math.sin(dLat/2) * Math.sin(dLat/2) +
            Math.cos(truck.current_latitude * Math.PI / 180) * Math.cos(point.latitude * Math.PI / 180) * 
            Math.sin(dLon/2) * Math.sin(dLon/2);
          const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1-a));
          const dist = 6371 * c; // Earth's radius in km
          
          if (dist < minDistance) {
            minDistance = dist;
            closestIndex = i;
          }
        }
        
        // Calculate bearing to the next point in the route
        if (closestIndex < truck.full_route.length - 1) {
          const nextPoint = truck.full_route[closestIndex + 1];
          const lat1 = truck.current_latitude * Math.PI / 180;
          const lat2 = nextPoint.latitude * Math.PI / 180;
          const dLon = (nextPoint.longitude - truck.current_longitude) * Math.PI / 180;
          
          const y = Math.sin(dLon) * Math.cos(lat2);
          const x = Math.cos(lat1) * Math.sin(lat2) - Math.sin(lat1) * Math.cos(lat2) * Math.cos(dLon);
          const brng = Math.atan2(y, x) * 180 / Math.PI;
          
          // Make the bearing positive
          bearing = (brng + 360) % 360;
        }
      }
      
      // Center the map on the driver's truck with high zoom and rotate to truck direction
      // Use a slightly offset center to show more road ahead (like Google Maps navigation)
      map.current.flyTo({
        center: [truck.current_longitude, truck.current_latitude],
        zoom: 14,  // High zoom for navigation
        bearing: bearing,  // Rotate map to match truck direction
        pitch: 45,  // Add pitch for realistic navigation feel
        duration: 1000  // Smooth easing
      });
    } else if (truck) {
      // Fallback if no route data is available
      map.current.flyTo({
        center: [truck.current_longitude, truck.current_latitude],
        zoom: 14,
        duration: 1000
      });
    }
  }, [role, driverTruckId, worldState, driverAutoFollow]);

  /* =========================
     ACTION HANDLERS
  ========================== */
  const handleFileUpload = async (type, file) => {
    if (!file) return
    const formData = new FormData()
    formData.append('file', file)
    await axios.post(`${API_BASE}/upload/${type}`, formData)
  }

  const startSimulation = async () => {
    try {
      setCommitError(null)
      const response = await axios.post(`${API_BASE}/simulation/start`)
      setSimulationStarted(true)
      setAddHubMode(false) // Turn off add hub mode after simulation starts
      console.log('Commit success:', response.data)
    } catch (error) {
      // Handle commit failure
      const errorMsg = error.response?.data?.detail || 'Commit failed - unknown error'
      setCommitError(errorMsg)
      setSimulationStarted(false)
      console.error('Commit failed:', errorMsg)
    }
  }

  const stopSimulation = async () => {
    // In the new design, there is no stop functionality after start
    // This function should not be called after simulation starts
    // We can keep it for reset purposes if needed, but normally not used
    await axios.post(`${API_BASE}/simulation/stop`)
    setSimulationStarted(false)
  }

  const handleCreateHub = async (hubData) => {
    try {
      await axios.post(`${API_BASE}/hubs/manual`, {
        name: hubData.name,
        latitude: hubModal.lat,
        longitude: hubModal.lng,
        demand_quantity: parseInt(hubData.demand_quantity),
        demand_priority: hubData.demand_priority,
        availability: parseInt(hubData.availability || 20)  // Set default availability to 20 as per requirements
      })
      setHubModal({ show: false, mode: 'create', hub: null, lat: null, lng: null })
    } catch (error) {
      console.error('Error creating hub:', error)
      alert('Failed to create hub: ' + (error.response?.data?.detail || error.message))
    }
  }

  const handleUpdateHub = async (hubData) => {
    try {
      await axios.put(`${API_BASE}/hubs/${hubModal.hub.id}/demand`, {
        demand_quantity: parseInt(hubData.demand_quantity),
        demand_priority: hubData.demand_priority
      })
      setHubModal({ show: false, mode: 'edit', hub: null, lat: null, lng: null })
    } catch (error) {
      console.error('Error updating hub:', error)
      alert('Failed to update hub: ' + (error.response?.data?.detail || error.message))
    }
  }

  const handleDeleteHub = async () => {
    if (!hubModal.hub) return
    if (!confirm(`Delete this hub permanently?`)) return

    try {
      await axios.delete(`${API_BASE}/hubs/${hubModal.hub.id}`)
      setHubModal({ show: false, mode: 'edit', hub: null, lat: null, lng: null })
    } catch (error) {
      console.error('Error deleting hub:', error)
      alert('Failed to delete hub: ' + (error.response?.data?.detail || error.message))
    }
  }

  const handleCreateRandomHubs = async () => {
    try {
      await axios.post(`${API_BASE}/hubs/random`)
      alert('Successfully created 4 random hubs!')
    } catch (error) {
      console.error('Error creating random hubs:', error)
      alert('Failed to create random hubs: ' + (error.response?.data?.detail || error.message))
    }
  }

  // Function to send instruction to a specific truck
  const sendInstruction = async () => {
    if (!driverTruckId || !instructionText.trim()) return;
    
    try {
      // Send instruction to backend
      await axios.post(`${API_BASE}/trucks/${driverTruckId}/instruction`, {
        instruction: instructionText
      });
      
      // Clear the instruction text after sending
      setInstructionText('');
      alert('Instruction sent successfully!');
    } catch (error) {
      console.error('Error sending instruction:', error);
      alert('Failed to send instruction');
    }
  };
  
  // Function to toggle disaster type and placement mode
  const toggleDisaster = (type) => {
    if (disasterType === type) {
      // Clicking the same disaster type toggles placement ON/OFF
      setPlacementMode(!placementMode);
      console.log(`${type} toggle ${!placementMode ? 'ON' : 'OFF'}, placementMode: ${!placementMode}`);
    } else {
      // Clicking a different disaster switches type and enables placement
      setDisasterType(type);
      setPlacementMode(true);
      console.log(`${type} selected and placementMode ON`);
    }
  };
  
  // Function to create disaster at clicked location
  const createDisaster = async (latitude, longitude, affectedRouteId = null, affectedSegmentStartIdx = null, affectedSegmentEndIdx = null) => {
    if (!simulationStarted) {
      alert('Start simulation first to place disasters');
      return;
    }
    
    try {
      const disasterData = {
        disaster_type: disasterType,
        latitude,
        longitude,
        radius_km: disasterRadius
      };
      
      // Add route segment information for traffic and roadblock disasters
      if (disasterType !== 'rain' && affectedRouteId !== null) {
        disasterData.affected_route_id = affectedRouteId;
        disasterData.affected_segment_start_idx = affectedSegmentStartIdx;
        disasterData.affected_segment_end_idx = affectedSegmentEndIdx;
      }
      
      await axios.post(`${API_BASE}/disasters`, disasterData);
      
      alert(`${disasterType} disaster created at (${latitude.toFixed(4)}, ${longitude.toFixed(4)})`);
      
      // Turn off placement mode after successful placement
      setPlacementMode(false);
      console.log(`${disasterType} disaster placed successfully, placementMode turned off`);
    } catch (error) {
      console.error('Error creating disaster:', error);
      alert('Failed to create disaster');
    }
  };
  
  // Handler for simulation speed change
  const handleSpeedChange = async (e) => {
    const newSpeed = parseFloat(e.target.value);
    setSimSpeed(newSpeed);
    
    try {
      await axios.post(`${API_BASE}/simulation/speed`, { speed: newSpeed });
    } catch (error) {
      console.error('Error changing simulation speed:', error);
    }
  };
  
  // Handler for pause/resume simulation
  const handlePauseResume = async () => {
    try {
      if (simPaused) {
        // Resume simulation
        await axios.post(`${API_BASE}/simulation/resume`);
        setSimPaused(false);
      } else {
        // Pause simulation
        await axios.post(`${API_BASE}/simulation/pause`);
        setSimPaused(true);
      }
    } catch (error) {
      console.error('Error controlling simulation:', error);
    }
  };
  
  // Handler for stopping the simulation
  const handleStopSimulation = async () => {
    if (window.confirm('Are you sure you want to stop the simulation? This action cannot be undone.')) {
      try {
        await axios.post(`${API_BASE}/simulation/stop`);
        setSimulationStarted(false);
        setSimPaused(false);
        setSimulationTerminated(true);
      } catch (error) {
        console.error('Error stopping simulation:', error);
      }
    }
  };
  
  // Add effect to stop polling when simulation is stopped
  useEffect(() => {
    if (!simulationStarted) {
      // When simulation stops, we don't need to do anything special
      // The polling continues to get the stopped state
    }
  }, [simulationStarted]);
  
  // Determine which truck to display based on role
  const currentTruck = worldState?.trucks?.find(t => {
    if (role === 'driver_perspective' && driverTruckId) {
      return t.id === driverTruckId;
    } else if (role === 'driver' && selectedTruck) {
      return t.id === selectedTruck;
    }
    return false;
  });
  
  // Determine which truck's decisions to show based on role
  const truckDecision = worldState?.ai_decisions?.find(d => {
    if (role === 'driver_perspective' && driverTruckId) {
      return d.truck_id === driverTruckId;
    } else if (role === 'driver' && selectedTruck) {
      return d.truck_id === selectedTruck;
    }
    return false;
  });

  /* =========================
     UI
  ========================== */
  return (
    <div className="map-container">
      {simulationTerminated ? (
        <div style={{
          position: 'fixed',
          inset: 0,
          backgroundColor: 'white',
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          zIndex: 10001,
          color: '#333',
          textAlign: 'center'
        }}>
          <h1 style={{
            fontSize: '32px',
            margin: '0 0 20px 0',
            color: '#2c3e50'
          }}>
            Simulation Completed
          </h1>
          <p style={{
            fontSize: '18px',
            margin: '0 0 30px 0',
            maxWidth: '600px',
            color: '#7f8c8d'
          }}>
            Thank you for using the AI-Based Logistics Optimization System.
          </p>
          <p style={{
            fontSize: '14px',
            color: '#95a5a6',
            marginTop: '20px'
          }}>
            You may now safely close this window.
          </p>
        </div>
      ) : (
        <>
          <div ref={mapContainer} style={{ position: 'absolute', inset: 0, cursor: placementMode ? 'crosshair' : 'default' }} />
  
          {/* Simulation Control Bar */}
          <div style={{
            position: 'fixed',
            top: '12px',
            right: '12px',
            display: 'flex',
            flexDirection: 'column',
            gap: '8px',
            padding: '10px',
            background: 'white',
            borderRadius: '8px',
            boxShadow: '0 2px 10px rgba(0,0,0,0.1)',
            zIndex: 1500
          }}>
            {/* Simulation Speed Slider */}
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <label style={{ fontSize: '12px', fontWeight: 'bold' }}>Speed:</label>
              <input
                type="range"
                min="0.25"
                max="20.0"
                step="0.25"
                value={simSpeed}
                onChange={handleSpeedChange}
                disabled={!simulationStarted}
                style={{ width: '100px' }}
              />
              <span style={{ fontSize: '12px', minWidth: '30px' }}>{simSpeed}×</span>
            </div>
              
            {/* Pause/Resume Button */}
            <button
              onClick={handlePauseResume}
              disabled={!simulationStarted}
              style={{
                backgroundColor: simPaused ? '#f39c12' : '#007bff',
                color: 'white',
                border: 'none',
                borderRadius: '4px',
                padding: '6px 10px',
                cursor: 'pointer',
                fontSize: '12px',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                gap: '4px'
              }}
            >
              {simPaused ? '▶ Resume' : '⏸ Pause'}
            </button>
              
            {/* Stop Simulation Button */}
            <button
              onClick={handleStopSimulation}
              disabled={!simulationStarted}
              style={{
                backgroundColor: '#dc3545',
                color: 'white',
                border: 'none',
                borderRadius: '4px',
                padding: '6px 10px',
                cursor: 'pointer',
                fontSize: '12px',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                gap: '4px'
              }}
            >
              ⏹ Stop Simulation
            </button>
          </div>
  
          {/* Hub Creation/Edit Modal */}
          {hubModal.show && (
            <div style={{
              position: 'fixed',
              top: 0,
              left: 0,
              right: 0,
              bottom: 0,
              backgroundColor: 'rgba(0,0,0,0.5)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              zIndex: 10000
            }} onClick={() => setHubModal({ show: false, mode: 'create', hub: null, lat: null, lng: null })}>
              <div style={{
                backgroundColor: 'white',
                padding: '20px',
                borderRadius: '8px',
                minWidth: '300px',
                maxWidth: '400px'
              }} onClick={(e) => e.stopPropagation()}>
                <h3>{hubModal.mode === 'create' ? 'Create New Hub' : 'Edit Hub'}</h3>
                {hubModal.mode === 'create' ? (
                  <HubForm
                    onSubmit={handleCreateHub}
                    onCancel={() => setHubModal({ show: false, mode: 'create', hub: null, lat: null, lng: null })}
                    initialData={{ name: '', demand_quantity: 1, demand_priority: 'Medium', availability: 100 }}
                  />
                ) : (
                  <HubForm
                    onSubmit={handleUpdateHub}
                    onCancel={() => setHubModal({ show: false, mode: 'edit', hub: null, lat: null, lng: null })}
                    onDelete={!simulationStarted && hubModal.hub?.id !== 'CENTRAL_DEPOT' ? handleDeleteHub : null}
                    initialData={{
                      name: hubModal.hub?.name || '',
                      demand_quantity: hubModal.hub?.demand_quantity || 1,
                      demand_priority: hubModal.hub?.demand_priority || 'Medium'
                    }}
                    isEdit={true}
                  />
                )}
              </div>
            </div>
          )}
        </>
      )}
            
      <div className="control-panel">
        <h2>🚚 Route Optimization System</h2>

        <div className="role-selector">
          <button onClick={() => setRole('manager')} className={role === 'manager' ? 'active' : ''}>Manager</button>
          <button onClick={() => setRole('driver')} className={role === 'driver' ? 'active' : ''}>Driver Follow</button>
          <button onClick={() => {
            // Auto-assign the first truck to the driver if available
            if (worldState?.trucks && worldState.trucks.length > 0) {
              const firstTruck = worldState.trucks[0];
              setDriverTruckId(firstTruck.id);
            }
            setRole('driver_perspective');
            // Store mode preference for the driver view component
            localStorage.setItem('driverViewMode', 'DRIVER_FOLLOW');
          }} className={role === 'driver_perspective' ? 'active' : ''} style={{
            backgroundColor: role === 'driver_perspective' ? '#28a745' : '#17a2b8',
            color: 'white',
            fontWeight: 'bold'
          }}>Driver View</button>
        </div>

        {(role === 'manager' || role === 'driver') && (
          <>
            {/* Initialization controls - shown only before simulation starts */}
            {role === 'manager' && !simulationStarted && (
              <>
                <label>Trucks CSV</label>
                <input type="file" onChange={e => handleFileUpload('trucks', e.target.files[0])} />

                <div style={{ marginTop: '10px' }}>
                  <button 
                    className={`toggle-btn ${addHubMode ? 'active' : ''}`}
                    onClick={() => setAddHubMode(!addHubMode)}
                    style={{
                      padding: '8px 16px',
                      backgroundColor: addHubMode ? '#28a745' : '#6c757d',
                      color: 'white',
                      border: 'none',
                      borderRadius: '4px',
                      cursor: 'pointer',
                      width: '100%',
                      fontWeight: 'bold'
                    }}
                  >
                    ➕ Add Hub {addHubMode ? '(ON)' : '(OFF)'}
                  </button>
                  {addHubMode && (
                    <p style={{ fontSize: '12px', color: '#666', marginTop: '5px', fontStyle: 'italic' }}>
                      Click on the map to create a new hub
                    </p>
                  )}
                </div>

                <div style={{ marginTop: '10px' }}>
                  <button 
                    className="btn btn-secondary"
                    onClick={handleCreateRandomHubs}
                    disabled={simulationStarted}
                    style={{
                      padding: '8px 16px',
                      backgroundColor: simulationStarted ? '#6c757d' : '#6f42c1',
                      color: 'white',
                      border: 'none',
                      borderRadius: '4px',
                      cursor: simulationStarted ? 'not-allowed' : 'pointer',
                      width: '100%'
                    }}
                  >
                    🎯 Create 3 Fixed Hubs
                  </button>
                </div>

                {/* Hub List Panel - Manager only, before simulation starts */}
                {role === 'manager' && !simulationStarted && (
                  <div style={{ marginTop: '15px' }}>
                    <h4>📍 Hubs</h4>
                    <div style={{ maxHeight: '200px', overflowY: 'auto', border: '1px solid #ddd', borderRadius: '4px', padding: '10px' }}>
                      {worldState?.hubs?.filter(h => h.id !== 'CENTRAL_DEPOT').map(hub => (
                        <div key={hub.id} style={{ 
                          display: 'flex', 
                          justifyContent: 'space-between', 
                          alignItems: 'center', 
                          padding: '8px', 
                          margin: '5px 0', 
                          backgroundColor: '#f8f9fa', 
                          borderRadius: '4px',
                          border: '1px solid #e9ecef'
                        }}>
                          <span>
                            {hub.name} ({hub.demand_quantity} units, {hub.distance_from_trichy_km?.toFixed(1) || 'N/A'} km)
                          </span>
                          {hub.id !== 'CENTRAL_DEPOT' ? (
                            <button 
                              onClick={async () => {
                                if (window.confirm('Delete this hub permanently?')) {
                                  try {
                                    await axios.delete(`${API_BASE}/hubs/${hub.id}`);
                                    // The state will be updated by the polling mechanism
                                  } catch (error) {
                                    console.error('Error deleting hub:', error);
                                    alert('Failed to delete hub: ' + (error.response?.data?.detail || error.message));
                                  }
                                }
                              }}
                              style={{
                                padding: '4px 8px',
                                backgroundColor: '#dc3545',
                                color: 'white',
                                border: 'none',
                                borderRadius: '4px',
                                cursor: 'pointer',
                                fontSize: '12px'
                              }}
                            >
                              🗑 Delete
                            </button>
                          ) : (
                            <span style={{ color: '#6c757d', fontSize: '12px' }}>🔒</span>
                          )}
                        </div>
                      ))}
                      {worldState?.hubs?.filter(h => h.id !== 'CENTRAL_DEPOT').length === 0 && (
                        <div style={{ textAlign: 'center', color: '#6c757d', fontStyle: 'italic', padding: '10px' }}>
                          No hubs created yet
                        </div>
                      )}
                    </div>
                  </div>
                )}

                <div style={{ marginTop: '10px' }}>
                  <button className="btn btn-success" onClick={startSimulation}>Start</button>
                </div>
                
                {/* Commit Error Display */}
                {commitError && (
                  <div style={{ 
                    marginTop: '10px', 
                    padding: '10px', 
                    backgroundColor: '#f8d7da', 
                    border: '1px solid #f5c6cb',
                    borderRadius: '4px',
                    color: '#721c24'
                  }}>
                    <strong>⚠️ Commit Failed</strong>
                    <p style={{ margin: '5px 0 0 0', fontSize: '12px' }}>{commitError}</p>
                  </div>
                )}
              </>
            )}

            {/* Live operations controls - shown only after simulation starts */}
            {simulationStarted && (
              <>
                <h3 style={{ marginTop: '15px', color: '#28a745' }}>🟢 System Active ({worldState?.simulation_phase || 'executing'})</h3>
                <p style={{ fontSize: '12px', color: '#666', fontStyle: 'italic' }}>
                  All hubs committed and frozen. Adjust demand intensity sliders to influence truck routing.
                  Changes take effect at the next safe decision point.
                </p>
                
                {/* Commit Summary */}
                {role === 'manager' && (
                <div style={{ 
                  marginTop: '10px', 
                  padding: '8px', 
                  backgroundColor: '#d4edda', 
                  borderRadius: '4px',
                  fontSize: '12px'
                }}>
                  <strong>✅ Commit Summary</strong>
                  <div>Hubs Committed: {worldState?.initial_hubs_with_demand?.length || 0}</div>
                  <div>Active Trucks: {worldState?.trucks?.filter(t => t.active).length || 0}</div>
                </div>
                )}
                

                
                {/* Manual Instruction Panel for Manager */}
                {role === 'manager' && (
                <div style={{ marginTop: '15px' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '10px' }}>
                    <h4>📢 Send Instruction</h4>
                    <button
                      onClick={() => setActiveMode(activeMode === 'instruction' ? 'monitoring' : 'instruction')}
                      style={{
                        padding: '4px 8px',
                        backgroundColor: activeMode === 'instruction' ? '#007bff' : '#f8f9fa',
                        color: activeMode === 'instruction' ? 'white' : '#333',
                        border: '1px solid #ccc',
                        borderRadius: '4px',
                        cursor: 'pointer',
                        fontSize: '12px',
                        transition: 'all 0.2s ease'
                      }}
                    >
                      {activeMode === 'instruction' ? 'Disable' : 'Enable'}
                    </button>
                  </div>
                  {activeMode === 'instruction' && (
                  <>
                  <div style={{ marginBottom: '10px' }}>
                    <label style={{ display: 'block', marginBottom: '5px', fontWeight: 'bold' }}>Select Truck:</label>
                    <select 
                      value={driverTruckId || ''}
                      onChange={e => setDriverTruckId(e.target.value || null)}
                      style={{
                        width: '100%',
                        padding: '8px',
                        borderRadius: '4px',
                        border: '1px solid #ccc'
                      }}
                    >
                      <option value="">Select Truck</option>
                      {worldState?.trucks?.filter(t => t.active).map(t => (
                        <option key={t.id} value={t.id}>{t.id} ({t.status})</option>
                      ))}
                    </select>
                  </div>
                  
                  <div style={{ marginBottom: '10px' }}>
                    <label style={{ display: 'block', marginBottom: '5px', fontWeight: 'bold' }}>Instruction:</label>
                    <textarea 
                      value={instructionText || ''}
                      onChange={e => setInstructionText(e.target.value)}
                      placeholder="Enter instruction for driver..."
                      style={{
                        width: '100%',
                        padding: '8px',
                        borderRadius: '4px',
                        border: '1px solid #ccc',
                        minHeight: '60px',
                        resize: 'vertical'
                      }}
                    />
                  </div>
                  
                  <button
                    onClick={sendInstruction}
                    disabled={!driverTruckId || !instructionText}
                    style={{
                      width: '100%',
                      padding: '8px 16px',
                      backgroundColor: driverTruckId && instructionText ? '#007bff' : '#6c757d',
                      color: 'white',
                      border: 'none',
                      borderRadius: '4px',
                      cursor: driverTruckId && instructionText ? 'pointer' : 'not-allowed'
                    }}
                  >
                    Send to Driver
                  </button>
                  </>
                  )}
                </div>
                )}
                
                {/* Hub demand intensity sliders - THE ONLY RUNTIME INTERACTION */}
                {role === 'manager' && (
                <div style={{ marginTop: '15px' }}>
                  <h4>Demand Pressure Controls</h4>
                  <p style={{ fontSize: '11px', color: '#888', marginBottom: '10px' }}>
                    Low → Medium → High → Emergency
                  </p>
                  {worldState?.hubs?.filter(h => h.id !== 'CENTRAL_DEPOT' && !h.delivered).map(hub => (
                    <DemandSlider 
                      key={hub.id} 
                      hub={hub} 
                      onIntensityChange={async (hubId, intensity) => {
                        try {
                          await axios.put(`${API_BASE}/hubs/${hubId}/intensity`, {
                            demand_intensity: intensity
                          })
                        } catch (error) {
                          console.error('Error updating intensity:', error)
                        }
                      }}
                    />
                  ))}
                  
                  {/* Completed hubs display */}
                  {worldState?.hubs?.filter(h => h.id !== 'CENTRAL_DEPOT' && h.delivered).length > 0 && (
                    <div style={{ marginTop: '15px' }}>
                      <h5 style={{ color: '#28a745' }}>✅ Completed Hubs</h5>
                      {worldState?.hubs?.filter(h => h.id !== 'CENTRAL_DEPOT' && h.delivered).map(hub => (
                        <div key={hub.id} style={{ 
                          padding: '4px 8px', 
                          margin: '2px 0', 
                          background: '#d4edda', 
                          borderRadius: '4px',
                          fontSize: '12px'
                        }}>
                          {hub.name}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
                )}
              </>
            )}

            {/* AI Decisions - visible to both manager and driver roles */}
            <h3 style={{ marginTop: '15px' }}>AI Decisions</h3>
            <div style={{ maxHeight: '200px', overflowY: 'auto' }}>
              {worldState?.ai_decisions?.slice(-5).reverse().map((d, i) => (
                <div key={i} className="ai-explanation" style={{ marginBottom: '8px', padding: '8px', background: '#f5f5f5', borderRadius: '4px' }}>
                  <strong>{d.truck_id}</strong><br />
                  {d.decision}<br />
                  <small>{d.explanation}</small>
                </div>
              ))}
            </div>
            
            {role === 'manager' && (
            <div style={{position: 'fixed',bottom: '20px',right: '20px',width: '250px',backgroundColor: 'white',padding: '15px',borderRadius: '8px',boxShadow: '0 4px 12px rgba(0,0,0,0.15)',zIndex: 2000,border: '1px solid #ddd'}}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '10px' }}>
                <h4 style={{ margin: '0', color: '#2c3e50' }}>🚨 Disasters</h4>
                <button
                  onClick={() => setActiveMode(activeMode === 'disaster' ? 'monitoring' : 'disaster')}
                  style={{
                    padding: '4px 8px',
                    backgroundColor: activeMode === 'disaster' ? '#007bff' : '#f8f9fa',
                    color: activeMode === 'disaster' ? 'white' : '#333',
                    border: '1px solid #ccc',
                    borderRadius: '4px',
                    cursor: 'pointer',
                    fontSize: '12px',
                    transition: 'all 0.2s ease'
                  }}
                >
                  {activeMode === 'disaster' ? 'Disable' : 'Enable'}
                </button>
              </div>
              
              {activeMode === 'disaster' && (
              <>
              <div style={{ marginBottom: '10px' }}>
                <label style={{ display: 'block', marginBottom: '5px', fontWeight: 'bold' }}>Select Disaster:</label>
                <div style={{ display: 'flex', gap: '5px' }}>
                  <button onClick={() => toggleDisaster('rain')} style={{flex: 1,padding: '5px 10px',backgroundColor: placementMode && disasterType === 'rain' ? '#3498db' : '#ecf0f1',color: placementMode && disasterType === 'rain' ? 'white' : '#2c3e50',border: '1px solid #bdc3c7',borderRadius: '4px',cursor: 'pointer'}}>🌧 Rain {placementMode && disasterType === 'rain' ? '(ON)' : ''}</button>
                  <button onClick={() => toggleDisaster('traffic')} style={{flex: 1,padding: '5px 10px',backgroundColor: placementMode && disasterType === 'traffic' ? '#f39c12' : '#ecf0f1',color: placementMode && disasterType === 'traffic' ? 'white' : '#2c3e50',border: '1px solid #bdc3c7',borderRadius: '4px',cursor: 'pointer'}}>🚦 Traffic {placementMode && disasterType === 'traffic' ? '(ON)' : ''}</button>
                  <button onClick={() => toggleDisaster('road_block')} style={{flex: 1,padding: '5px 10px',backgroundColor: placementMode && disasterType === 'road_block' ? '#e74c3c' : '#ecf0f1',color: placementMode && disasterType === 'road_block' ? 'white' : '#2c3e50',border: '1px solid #bdc3c7',borderRadius: '4px',cursor: 'pointer'}}>🚧 Road Block {placementMode && disasterType === 'road_block' ? '(ON)' : ''}</button>
                </div>
              </div>
              
              <div style={{ marginBottom: '10px' }}>
                <label style={{ display: 'block', marginBottom: '5px', fontWeight: 'bold' }}>Radius (km):</label>
                <input type="range" min="1" max="15" value={disasterRadius} onChange={e => setDisasterRadius(Number(e.target.value))} style={{ width: '100%' }} />
                <div style={{ fontSize: '12px', textAlign: 'center' }}>{disasterRadius} km</div>
              </div>
              
              <p style={{ fontSize: '12px', color: placementMode ? '#e74c3c' : '#7f8c8d', margin: '0' }}>{placementMode ? `PLACE ${disasterType.toUpperCase()} - Click on map` : 'Click on map to place disaster'}</p>
              </>
              )}
            </div>
            )}
          </>
        )}

        {role === 'driver_perspective' && (
          <>
            <h3>Driver View: {driverTruckId || 'No Truck Assigned'}</h3>
            
            {/* Allow driver to select their assigned truck */}
            <div style={{ marginBottom: '10px' }}>
              <label style={{ display: 'block', marginBottom: '5px', fontWeight: 'bold' }}>Your Truck:</label>
              <select 
                value={driverTruckId || ''}
                onChange={e => {
                  const truckId = e.target.value;
                  setDriverTruckId(truckId || null);
                  
                  // If selecting a truck, center map on it
                  if (truckId && map.current) {
                    const truck = worldState?.trucks?.find(t => t.id === truckId);
                    if (truck) {
                      map.current.easeTo({
                        center: [truck.current_longitude, truck.current_latitude],
                        zoom: 14,
                        bearing: 0,
                        pitch: 0,
                        duration: 300,
                        easing: t => t   // linear easing → continuous follow
                      });

                    }
                  }
                }}
                style={{
                  width: '100%',
                  padding: '8px',
                  borderRadius: '4px',
                  border: '1px solid #ccc'
                }}
              >
                <option value="">Select Your Truck</option>
                {worldState?.trucks?.map(t => (
                  <option key={t.id} value={t.id}>{t.id} ({t.status})</option>
                ))}
              </select>
              
              {/* Button to open driver view in new window */}
              <button
                onClick={() => {
                  if (driverTruckId) {
                    // Store the truckId in localStorage for the driver view
                    localStorage.setItem('driverTruckId', driverTruckId);
                    // Store mode preference for navigation mode
                    localStorage.setItem('driverViewMode', 'DRIVER_NAVIGATION');
                    // Open the driver view in a new window with URL parameter
                    const driverViewUrl = `${window.location.origin}/driver.html?truckId=${driverTruckId}`;
                    window.open(driverViewUrl, 'driver-view', 'width=1000,height=700,scrollbars=yes,resizable=yes');
                  } else {
                    alert('Please select a truck first');
                  }
                }}
                style={{
                  marginTop: '10px',
                  padding: '8px 16px',
                  backgroundColor: '#28a745',
                  color: 'white',
                  border: 'none',
                  borderRadius: '4px',
                  cursor: 'pointer',
                  width: '100%'
                }}
              >
                Open in Driver View
              </button>
            </div>
            
            {currentTruck && (
              <>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '10px', marginBottom: '10px' }}>
                  <div>
                    <div style={{ fontSize: '12px', color: '#666', marginBottom: '2px' }}>Status</div>
                    <div style={{ fontWeight: 'bold', color: currentTruck.status === 'moving' ? '#28a745' : '#ffc107' }}>{currentTruck.status.toUpperCase()}</div>
                  </div>
                  <div>
                    <div style={{ fontSize: '12px', color: '#666', marginBottom: '2px' }}>Fuel</div>
                    <div style={{ fontWeight: 'bold' }}>{currentTruck.fuel_remaining.toFixed(1)}L</div>
                  </div>
                  <div>
                    <div style={{ fontSize: '12px', color: '#666', marginBottom: '2px' }}>Speed</div>
                    <div style={{ fontWeight: 'bold' }}>{currentTruck.speed.toFixed(1)} km/h</div>
                  </div>
                  <div>
                    <div style={{ fontSize: '12px', color: '#666', marginBottom: '2px' }}>Route Points</div>
                    <div style={{ fontWeight: 'bold' }}>{currentTruck.full_route?.length || 0}</div>
                  </div>
                </div>
                <div style={{ marginTop: '10px', padding: '8px', backgroundColor: '#e9ecef', borderRadius: '4px' }}>
                  <strong>Current Task:</strong><br />
                  {currentTruck.current_task ? 
                    `Delivering to ${worldState?.hubs?.find(h => h.id === currentTruck.current_task.hub_id)?.name || 'Unknown Hub'}` :
                    'No active task'
                  }
                </div>
              </>
            )}
            
            {truckDecision && (
              <div className="ai-explanation" style={{ marginTop: '10px', padding: '8px', background: '#f5f5f5', borderRadius: '4px' }}>
                <strong>{truckDecision.decision}</strong><br />
                <small>{truckDecision.explanation}</small>
              </div>
            )}
            
            <button
              onClick={() => {
                setRole('manager');
                setDriverTruckId(null);
              }}
              style={{
                marginTop: '10px',
                padding: '8px 16px',
                backgroundColor: '#6c757d',
                color: 'white',
                border: 'none',
                borderRadius: '4px',
                cursor: 'pointer'
              }}
            >
              Exit Driver View
            </button>
          </>
        )}
        
        {role === 'driver' && (
          <>
            <select 
              value={selectedTruck || ''}
              onChange={e => {
                const truckId = e.target.value;
                setSelectedTruck(truckId || null);
                
                // If following a truck in driver mode, center map on it
                if (truckId && map.current && role === 'driver') {
                  const truck = worldState?.trucks?.find(t => t.id === truckId);
                  if (truck) {
                    map.current.flyTo({
                      center: [truck.current_longitude, truck.current_latitude],
                      zoom: 12,  // Driver-level zoom
                      duration: 1000  // Smooth transition
                    });
                  }
                }
              }}
            >
              <option value="">Select Truck to Follow</option>
              {worldState?.trucks?.map(t => (
                <option key={t.id} value={t.id}>{t.id} ({t.status})</option>
              ))}
            </select>

            {currentTruck && (
              <>
                <p>Status: {currentTruck.status}</p>
                <p>Fuel: {currentTruck.fuel_remaining.toFixed(1)}</p>
                <p>Speed: {currentTruck.speed.toFixed(1)}</p>
                <p>Route Length: {currentTruck.full_route?.length || 0} points</p>
              </>
            )}

            {truckDecision && (
              <div className="ai-explanation" style={{ marginTop: '10px', padding: '8px', background: '#f5f5f5', borderRadius: '4px' }}>
                <strong>{truckDecision.decision}</strong><br />
                <small>{truckDecision.explanation}</small>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}

// Hub Form Component
function HubForm({ onSubmit, onCancel, onDelete, initialData, isEdit = false }) {
  const [formData, setFormData] = useState(initialData)

  const handleSubmit = (e) => {
    e.preventDefault()
    if (!formData.name.trim() && !isEdit) {
      alert('Please enter a hub name')
      return
    }
    onSubmit(formData)
  }

  return (
    <form onSubmit={handleSubmit}>
      {!isEdit && (
        <div style={{ marginBottom: '15px' }}>
          <label style={{ display: 'block', marginBottom: '5px', fontWeight: 'bold' }}>
            Hub Name
          </label>
          <input
            type="text"
            value={formData.name}
            onChange={(e) => setFormData({ ...formData, name: e.target.value })}
            style={{ width: '100%', padding: '8px', borderRadius: '4px', border: '1px solid #ccc' }}
            required
            placeholder="Enter hub name"
          />
        </div>
      )}
      {isEdit && (
        <div style={{ marginBottom: '15px' }}>
          <label style={{ display: 'block', marginBottom: '5px', fontWeight: 'bold' }}>
            Hub Name
          </label>
          <input
            type="text"
            value={formData.name}
            disabled
            style={{ width: '100%', padding: '8px', borderRadius: '4px', border: '1px solid #ccc', backgroundColor: '#f5f5f5' }}
          />
        </div>
      )}
      <div style={{ marginBottom: '15px' }}>
        <label style={{ display: 'block', marginBottom: '5px', fontWeight: 'bold' }}>
          Demand Quantity
        </label>
        <input
          type="number"
          min="1"
          value={formData.demand_quantity}
          onChange={(e) => setFormData({ ...formData, demand_quantity: e.target.value })}
          style={{ width: '100%', padding: '8px', borderRadius: '4px', border: '1px solid #ccc' }}
          required
        />
      </div>
      <div style={{ marginBottom: '15px' }}>
        <label style={{ display: 'block', marginBottom: '5px', fontWeight: 'bold' }}>
          Availability
        </label>
        <input
          type="number"
          min="1"
          value={formData.availability || 100}
          onChange={(e) => setFormData({ ...formData, availability: e.target.value })}
          style={{ width: '100%', padding: '8px', borderRadius: '4px', border: '1px solid #ccc' }}
          required
        />
      </div>
      <div style={{ marginBottom: '15px' }}>
        <label style={{ display: 'block', marginBottom: '5px', fontWeight: 'bold' }}>
          Demand Priority
        </label>
        <select
          value={formData.demand_priority}
          onChange={(e) => setFormData({ ...formData, demand_priority: e.target.value })}
          style={{ width: '100%', padding: '8px', borderRadius: '4px', border: '1px solid #ccc' }}
          required
        >
          <option value="Low">Low</option>
          <option value="Medium">Medium</option>
          <option value="High">High</option>
          <option value="Emergency">Emergency</option>
        </select>
      </div>
      <div style={{ display: 'flex', gap: '10px', justifyContent: 'flex-end' }}>
        {onDelete && (
          <button
            type="button"
            onClick={onDelete}
            style={{
              padding: '8px 16px',
              backgroundColor: '#dc3545',
              color: 'white',
              border: 'none',
              borderRadius: '4px',
              cursor: 'pointer'
            }}
            title={!simulationStarted ? '' : 'Hubs cannot be deleted after simulation start'}
          >
            Delete Hub
          </button>
        )}
        <button
          type="button"
          onClick={onCancel}
          style={{
            padding: '8px 16px',
            backgroundColor: '#6c757d',
            color: 'white',
            border: 'none',
            borderRadius: '4px',
            cursor: 'pointer'
          }}
        >
          Cancel
        </button>
        <button
          type="submit"
          style={{
            padding: '8px 16px',
            backgroundColor: '#007bff',
            color: 'white',
            border: 'none',
            borderRadius: '4px',
            cursor: 'pointer'
          }}
        >
          {isEdit ? 'Update' : 'Create'}
        </button>
      </div>
    </form>
  )
}

// Demand Intensity Slider Component
// THE ONLY RUNTIME INTERACTION - controls urgency pressure on hubs
function DemandSlider({ hub, onIntensityChange }) {
  const intensityLevels = ['Low', 'Medium', 'High', 'Emergency']
  const currentIndex = intensityLevels.indexOf(hub.demand_intensity || 'Medium')
  
  const getIntensityColor = (intensity) => {
    switch(intensity) {
      case 'Emergency': return '#dc3545'  // Red
      case 'High': return '#fd7e14'       // Orange
      case 'Medium': return '#ffc107'     // Yellow
      case 'Low': return '#28a745'        // Green
      default: return '#6c757d'
    }
  }
  
  const getOwnershipBadge = () => {
    if (hub.ownership_state === 'COMPLETED') {
      return { text: '✅ Done', color: '#28a745' }
    } else if (hub.ownership_state === 'ASSIGNED' && hub.owner_truck_id) {
      return { text: `🚚 ${hub.owner_truck_id}`, color: '#007bff' }
    } else {
      return { text: '⏳ Waiting', color: '#6c757d' }
    }
  }
  
  const getFrozenBadge = () => {
    if (hub.frozen_at_commit) {
      return { text: '🔒 Committed', color: '#6c757d' }
    }
    return null
  }
  
  const handleSliderChange = (e) => {
    const newIndex = parseInt(e.target.value)
    const newIntensity = intensityLevels[newIndex]
    onIntensityChange(hub.id, newIntensity)
  }
  
  const ownership = getOwnershipBadge()
  const frozen = getFrozenBadge()
  
  return (
    <div style={{ 
      padding: '10px', 
      margin: '6px 0', 
      background: '#f8f9fa', 
      borderRadius: '6px',
      border: `2px solid ${getIntensityColor(hub.demand_intensity || 'Medium')}`,
      transition: 'border-color 0.3s ease'
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '6px' }}>
        <span style={{ fontWeight: 'bold', fontSize: '13px' }}>{hub.name}</span>
        <div style={{ display: 'flex', gap: '4px', alignItems: 'center' }}>
          {frozen && (
            <span style={{ 
              fontSize: '9px', 
              padding: '2px 4px', 
              borderRadius: '6px',
              backgroundColor: frozen.color,
              color: 'white'
            }}>
              {frozen.text}
            </span>
          )}
          <span style={{ 
            fontSize: '10px', 
            padding: '2px 6px', 
            borderRadius: '8px',
            backgroundColor: ownership.color,
            color: 'white',
            fontWeight: 'bold'
          }}>
            {ownership.text}
          </span>
          <span style={{ 
            fontSize: '11px', 
            padding: '2px 8px', 
            borderRadius: '10px',
            backgroundColor: getIntensityColor(hub.demand_intensity || 'Medium'),
            color: 'white',
            fontWeight: 'bold'
          }}>
            {hub.demand_intensity || 'Medium'}
          </span>
        </div>
      </div>
      
      <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
        <span style={{ fontSize: '10px', color: '#28a745' }}>🟢</span>
        <input
          type="range"
          min="0"
          max="3"
          value={currentIndex >= 0 ? currentIndex : 1}
          onChange={handleSliderChange}
          style={{ 
            flex: 1,
            height: '6px',
            cursor: 'pointer',
            accentColor: getIntensityColor(hub.demand_intensity || 'Medium')
          }}
        />
        <span style={{ fontSize: '10px', color: '#dc3545' }}>🔴</span>
      </div>
      
      <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: '4px', fontSize: '10px', color: '#666' }}>
        <span>Demand: {hub.demand_quantity}</span>
        <span>Priority: {hub.demand_priority}</span>
      </div>
    </div>
  )
}

export default App ;