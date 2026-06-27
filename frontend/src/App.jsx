import React, { useState, useEffect, useRef } from 'react';
import maplibregl from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import axios from 'axios'
import './index.css'
const API_BASE = 'http://localhost:8000'
function createTruckElement() {
  const wrapper = document.createElement('div');
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
const haversine = (lat1, lon1, lat2, lon2) => {
  const R = 6371;
  const dLat = (lat2 - lat1) * Math.PI / 180;
  const dLon = (lon2 - lon1) * Math.PI / 180;
  const a =
    Math.sin(dLat / 2) * Math.sin(dLat / 2) +
    Math.cos(lat1 * Math.PI / 180) * Math.cos(lat2 * Math.PI / 180) *
    Math.sin(dLon / 2) * Math.sin(dLon / 2);
  const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
  return R * c;
}
const pointToLineDistance = (lat, lon, lineStartLat, lineStartLon, lineEndLat, lineEndLon) => {
  const lineVecX = lineEndLon - lineStartLon;
  const lineVecY = lineEndLat - lineStartLat;
  const pointVecX = lon - lineStartLon;
  const pointVecY = lat - lineStartLat;
  const lineLenSq = lineVecX * lineVecX + lineVecY * lineVecY;
  if (lineLenSq === 0) {
    return haversine(lat, lon, lineStartLat, lineStartLon);
  }
  let t = (pointVecX * lineVecX + pointVecY * lineVecY) / lineLenSq;
  t = Math.max(0, Math.min(1, t));
  const closestLon = lineStartLon + t * lineVecX;
  const closestLat = lineStartLat + t * lineVecY;
  return haversine(lat, lon, closestLat, closestLon);
}
function App() {
  const [role, setRole] = useState('manager')
  const [worldState, setWorldState] = useState(null)
  const [selectedTruck, setSelectedTruck] = useState(null)
  const [driverTruckId, setDriverTruckId] = useState(null)
  const [instructionText, setInstructionText] = useState('')
  const [sensorType, setSensorType] = useState('rain')
  const [sensorRadius, setSensorRadius] = useState(5)
  const [placementMode, setPlacementMode] = useState(false)
  const [activeMode, setActiveMode] = useState('monitoring');
  const [simulationStarted, setSimulationStarted] = useState(false)
  const [isImpactsPanelOpen, setIsImpactsPanelOpen] = useState(false)
  const [commitError, setCommitError] = useState(null)
  const [simSpeed, setSimSpeed] = useState(1.0)
  const [simPaused, setSimPaused] = useState(false)
  const [showStopOverlay, setShowStopOverlay] = useState(false)
  const [simulationTerminated, setSimulationTerminated] = useState(false)
  const [showDashboard, setShowDashboard] = useState(false)
  const [activeRerouteDecision, setActiveRerouteDecision] = useState(null)
  const lastSeenDecisionRef = useRef(null)
  const mapContainer = useRef(null)
  const map = useRef(null)
  const markers = useRef({
    hubs: {},
    trucks: {},
    destinations: {}
  })
  const [hubModal, setHubModal] = useState({
    show: false,
    mode: 'create',
    hub: null,
    lat: null,
    lng: null
  })
  const [addHubMode, setAddHubMode] = useState(false)
  const [showRouteChangeBanner, setShowRouteChangeBanner] = useState(false)
  const [routeChangeMessage, setRouteChangeMessage] = useState('')
  const [showEtaIncreaseBanner, setShowEtaIncreaseBanner] = useState(false)
  const [etaIncreaseMessage, setEtaIncreaseMessage] = useState('')
  const prevTruckRoutes = useRef({})
  const prevHubEtas = useRef({})
  const hasResetOnLoadRef = useRef(false)
  useEffect(() => {
    if (hasResetOnLoadRef.current) return
    hasResetOnLoadRef.current = true
    const resetOnLoad = async () => {
      try {
        await axios.post(`${API_BASE}/simulation/reset`)
      } catch (e) {
        console.error('[INIT] Failed to reset simulation on load:', e)
      }
    }
    resetOnLoad()
  }, [])
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
  useEffect(() => {
    if (!map.current) return
    const handleMapClick = (e) => {
      try {
        if (e && e.originalEvent) {
          e.originalEvent.preventDefault()
          e.originalEvent.stopPropagation()
        }
      } catch (_) { }
      if (role === 'driver_perspective') return
      if (role === 'manager' && placementMode && simulationStarted && activeMode === 'sensor') {
        if (sensorType === 'rain') {
          createSensor(e.lngLat.lat, e.lngLat.lng)
          return
        }
        const clickedLat = e.lngLat.lat
        const clickedLng = e.lngLat.lng
        let nearestPoint = null
        let minDistance = Infinity
        let nearestTruckId = null
        let nearestSegmentStartIdx = null
        let nearestSegmentEndIdx = null
        const trucks = worldState?.trucks ?? []
        for (const truck of trucks) {
          const route = truck.full_route || truck.route
          if (!route || route.length < 2) continue
          for (let i = 0; i < route.length - 1; i++) {
            const start = route[i]
            const end = route[i + 1]
            const dist = pointToLineDistance(clickedLat, clickedLng, start.latitude, start.longitude, end.latitude, end.longitude)
            if (dist < minDistance) {
              minDistance = dist
              nearestPoint = { latitude: clickedLat, longitude: clickedLng }
              nearestTruckId = truck.id
              nearestSegmentStartIdx = i
              nearestSegmentEndIdx = i + 1
            }
          }
        }
        const thresholdKm = 1.0
        if (nearestPoint && minDistance <= thresholdKm) {
          const truck = worldState.trucks.find(t => t.id === nearestTruckId);
          const route = truck.full_route || truck.route;
          const segmentStart = route[nearestSegmentStartIdx];
          const segmentEnd = route[nearestSegmentEndIdx];
          createSensor(nearestPoint.latitude, nearestPoint.longitude, segmentStart, segmentEnd)
        } else {
          alert('Click directly on an active route (within 1 km).')
        }
        return
      }
      if (role === 'manager' && addHubMode) {
        setHubModal({ show: true, mode: 'create', hub: null, lat: e.lngLat.lat, lng: e.lngLat.lng })
      }
    }
    map.current.on('click', handleMapClick)
    return () => {
      if (map.current) {
        map.current.off('click', handleMapClick)
      }
    }
  }, [role, addHubMode, placementMode, sensorType, activeMode, worldState, simulationStarted])
  const [driverAutoFollow, setDriverAutoFollow] = useState(true);
  const [driverFollowTimeout, setDriverFollowTimeout] = useState(null);
  useEffect(() => {
    if (role === 'driver') {
      setDriverTruckId(null);
      setDriverAutoFollow(false);
    }
    if (role === 'driver_perspective') {
      setSelectedTruck(null);
    }
    if (role === 'manager') {
      setSelectedTruck(null);
      setDriverTruckId(null);
      setDriverAutoFollow(false);
    }
  }, [role]);
  useEffect(() => {
    if (!map.current || role !== 'driver_perspective') return;
    const handleMapMove = () => {
      if (driverAutoFollow) {
        setDriverAutoFollow(false);
        if (driverFollowTimeout) {
          clearTimeout(driverFollowTimeout);
        }
        const timeout = setTimeout(() => {
          setDriverAutoFollow(true);
          setDriverFollowTimeout(null);
        }, 7000);
        setDriverFollowTimeout(timeout);
      }
    };
    map.current.on('drag', handleMapMove);
    map.current.on('zoom', handleMapMove);
    map.current.on('rotate', handleMapMove);
    return () => {
      if (map.current) {
        map.current.off('drag', handleMapMove);
        map.current.off('zoom', handleMapMove);
        map.current.off('rotate', handleMapMove);
      }
      if (driverFollowTimeout) {
        clearTimeout(driverFollowTimeout);
      }
    };
  }, [role, driverAutoFollow, driverFollowTimeout]);
  useEffect(() => {
    const interval = setInterval(async () => {
      try {
        const res = await axios.get(`${API_BASE}/state`)
        const data = res.data;
        setWorldState(data)
        const truckIds = new Set((data.trucks || []).map(t => t.id))
        setSelectedTruck(prev => (prev && truckIds.has(prev)) ? prev : null)
        setDriverTruckId(prev => (prev && truckIds.has(prev)) ? prev : null)
        if (data.simulation_running !== undefined) setSimulationStarted(data.simulation_running);
        if (data.simulation_paused !== undefined) setSimPaused(data.simulation_paused);
        if (data.simulation_speed !== undefined) setSimSpeed(data.simulation_speed);
        const rerouteDecisions = data.ai_decisions?.filter(d => d.decision === 'CHECKPOINT_REROUTE_EVALUATION');
        if (rerouteDecisions && rerouteDecisions.length > 0) {
          const latest = rerouteDecisions[rerouteDecisions.length - 1];
          if (!lastSeenDecisionRef.current || latest.timestamp > lastSeenDecisionRef.current.timestamp) {
            setActiveRerouteDecision(latest);
            lastSeenDecisionRef.current = latest;
            setTimeout(() => {
              setActiveRerouteDecision(prev => prev === latest ? null : prev);
            }, 10000);
          }
        }
        if (data.hubs && data.active_sensors && data.active_sensors.length > 0) {
          data.hubs.forEach(hub => {
            if (hub.estimated_arrival_hours && hub.owner_truck_id) {
              const prevEta = prevHubEtas.current[hub.id];
              const currentEta = hub.estimated_arrival_hours;
              if (prevEta !== undefined && currentEta > prevEta + 0.01) {
                const increase = currentEta - prevEta;
                setEtaIncreaseMessage(
                  `⚠️ ETA increased for ${hub.name}: +${increase.toFixed(2)}h due to live sensor nodes`
                );
                setShowEtaIncreaseBanner(true);
                setTimeout(() => setShowEtaIncreaseBanner(false), 8000);
              }
              prevHubEtas.current[hub.id] = currentEta;
            }
          });
        }
      } catch (e) {
        console.error(e)
      }
    }, 1000)
    return () => clearInterval(interval)
  }, [])
  useEffect(() => {
    if (!map.current || !worldState) return
    const liveHubIds = new Set(worldState.hubs.map(h => h.id));
    Object.keys(markers.current.hubs).forEach(hubId => {
      if (!liveHubIds.has(hubId)) {
        markers.current.hubs[hubId].remove();
        delete markers.current.hubs[hubId];
      }
    });
    const liveTruckIds = new Set(worldState.trucks.map(t => t.id));
    Object.keys(markers.current.trucks).forEach(truckId => {
      if (!liveTruckIds.has(truckId)) {
        markers.current.trucks[truckId].remove();
        delete markers.current.trucks[truckId];
      }
    });
    if (map.current) {
      const allLayers = map.current.getStyle().layers || [];
      allLayers.forEach(layer => {
        if (layer.id.startsWith('truck-') && layer.id.endsWith('-route')) {
          const truckId = layer.id.split('-')[1];
          if (!liveTruckIds.has(truckId)) {
            if (map.current.getLayer(layer.id)) map.current.removeLayer(layer.id);
            if (map.current.getSource(layer.id)) map.current.removeSource(layer.id);
          }
        }
      });
    }
    worldState.hubs.forEach(hub => {
      let marker = markers.current.hubs[hub.id]
      const isDestinationHub = role === 'driver_perspective' && driverTruckId && worldState.trucks &&
        worldState.trucks.some(truck =>
          truck.id === driverTruckId &&
          truck.current_task &&
          truck.current_task.hub_id === hub.id
        );
      const isCentralHub = hub.id === 'CENTRAL_DEPOT';
      const isDeliveredHub = hub.delivered || hub.demand_quantity === 0;
      const isVisible = role !== 'driver_perspective' || isDestinationHub || isCentralHub || isDeliveredHub;
      if (!marker) {
        const el = document.createElement('div')
        el.style.zIndex = '1000'
        el.style.display = 'flex'
        el.style.alignItems = 'center'
        el.style.justifyContent = 'center'
        el.style.cursor = 'pointer'
        if (hub.id === 'CENTRAL_DEPOT') {
          el.innerHTML = '';
          el.style.width = '64px';
          el.style.height = '64px';
          el.style.background = '#2ecc71';
          el.style.borderRadius = '50%';
          el.style.border = '4px solid #ffffff';
          el.style.boxShadow = '0 0 20px rgba(46,204,113,0.9)';
          el.style.display = 'flex';
          el.style.alignItems = 'center';
          el.style.justifyContent = 'center';
          el.title = 'Central Depot';
          const inner = document.createElement('div');
          inner.style.width = '42px';
          inner.style.height = '42px';
          inner.style.borderRadius = '50%';
          inner.style.border = '2px dashed rgba(255,255,255,0.8)';
          el.appendChild(inner);
        }
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
        else {
          el.innerHTML = '📦'
          el.style.fontSize = '24px'
          el.style.width = '30px'
          el.style.height = '30px'
          if (hub.is_late) {
            el.style.background = '#dc3545'
            el.style.boxShadow = '0 0 8px rgba(220,53,69,0.8)'
          } else if (hub.replan_candidate) {
            el.style.background = '#ff6b35'
            el.style.boxShadow = '0 0 8px rgba(255,107,53,0.8)'
          } else {
            el.style.background = '#007bff'
            el.style.boxShadow = '0 0 8px rgba(0,123,255,0.6)'
          }
          el.style.border = '2px solid #ffffff'
          el.style.borderRadius = '50%'
          if (hub.is_late) {
            const existingBadges = el.querySelectorAll('.replan-badge, .late-badge');
            existingBadges.forEach(b => b.remove());
            const badge = document.createElement('div');
            badge.className = 'late-badge';
            badge.innerHTML = '⚠️';
            badge.style.position = 'absolute';
            badge.style.top = '-5px';
            badge.style.right = '-5px';
            badge.style.width = '18px';
            badge.style.height = '18px';
            badge.style.background = '#dc3545';
            badge.style.color = 'white';
            badge.style.borderRadius = '50%';
            badge.style.fontSize = '10px';
            badge.style.display = 'flex';
            badge.style.alignItems = 'center';
            badge.style.justifyContent = 'center';
            badge.style.border = '1px solid white';
            badge.style.zIndex = '1001';
            badge.style.pointerEvents = 'none';
            badge.title = 'Will miss deadline';
            el.appendChild(badge);
          }
          else if (hub.replan_candidate) {
            const existingBadges = el.querySelectorAll('.replan-badge, .late-badge');
            existingBadges.forEach(b => b.remove());
            const badge = document.createElement('div');
            badge.className = 'replan-badge';
            badge.innerHTML = '🔄';
            badge.style.position = 'absolute';
            badge.style.top = '-5px';
            badge.style.right = '-5px';
            badge.style.width = '18px';
            badge.style.height = '18px';
            badge.style.background = '#ff3b30';
            badge.style.color = 'white';
            badge.style.borderRadius = '50%';
            badge.style.fontSize = '10px';
            badge.style.display = 'flex';
            badge.style.alignItems = 'center';
            badge.style.justifyContent = 'center';
            badge.style.border = '1px solid white';
            badge.style.zIndex = '1001';
            badge.style.pointerEvents = 'none';
            badge.title = 'Replan Required';
            el.appendChild(badge);
          }
          if (hub.is_late) {
            el.title = `${hub.name} - Will miss deadline (${hub.deadline_hours}h)`
          } else if (hub.replan_candidate) {
            el.title = `${hub.name} - Deadline changed, evaluating at next decision point`
          } else {
            el.title = `${hub.name} - Deadline: ${hub.deadline_hours}h`
          }
        }
        el.style.display = isVisible ? 'flex' : 'none';
        marker = new maplibregl.Marker(el)
          .setLngLat([hub.longitude, hub.latitude])
          .addTo(map.current)
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
        const el = marker.getElement()
        marker.setLngLat([hub.longitude, hub.latitude])
        if (hub.id === 'CENTRAL_DEPOT') {
          el.innerHTML = '';
          el.style.width = '48px';
          el.style.height = '48px';
          el.style.background = '#2ecc71';
          el.style.borderRadius = '50%';
          el.style.border = '4px solid #ffffff';
          el.style.boxShadow = '0 0 20px rgba(46,204,113,0.9)';
          el.style.display = 'flex';
          el.style.alignItems = 'center';
          el.style.justifyContent = 'center';
          el.title = 'Central Depot';
          const inner = document.createElement('div');
          inner.style.width = '30px';
          inner.style.height = '30px';
          inner.style.borderRadius = '50%';
          inner.style.border = '2px dashed rgba(255,255,255,0.8)';
          el.appendChild(inner);
        }
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
          if (hub.is_late) {
            el.style.background = '#dc3545'
            el.style.boxShadow = '0 0 8px rgba(220,53,69,0.8)'
          } else if (hub.replan_candidate) {
            el.style.background = '#ff6b35'
            el.style.boxShadow = '0 0 8px rgba(255,107,53,0.8)'
          } else {
            el.style.background = '#007bff'
            el.style.boxShadow = '0 0 8px rgba(0,123,255,0.6)'
          }
          el.style.border = '2px solid #ffffff'
          el.style.borderRadius = '50%'
          const existingBadges = el.querySelectorAll('.replan-badge, .late-badge');
          existingBadges.forEach(b => b.remove());
          if (hub.is_late) {
            const badge = document.createElement('div');
            badge.className = 'late-badge';
            badge.innerHTML = '⚠️';
            badge.style.position = 'absolute';
            badge.style.top = '-5px';
            badge.style.right = '-5px';
            badge.style.width = '18px';
            badge.style.height = '18px';
            badge.style.background = '#dc3545';
            badge.style.color = 'white';
            badge.style.borderRadius = '50%';
            badge.style.fontSize = '10px';
            badge.style.display = 'flex';
            badge.style.alignItems = 'center';
            badge.style.justifyContent = 'center';
            badge.style.border = '1px solid white';
            badge.style.zIndex = '1001';
            badge.style.pointerEvents = 'none';
            badge.title = 'Will miss deadline';
            el.appendChild(badge);
          }
          else if (hub.replan_candidate) {
            const badge = document.createElement('div');
            badge.className = 'replan-badge';
            badge.innerHTML = '🔄';
            badge.style.position = 'absolute';
            badge.style.top = '-5px';
            badge.style.right = '-5px';
            badge.style.width = '18px';
            badge.style.height = '18px';
            badge.style.background = '#ff3b30';
            badge.style.color = 'white';
            badge.style.borderRadius = '50%';
            badge.style.fontSize = '10px';
            badge.style.display = 'flex';
            badge.style.alignItems = 'center';
            badge.style.justifyContent = 'center';
            badge.style.border = '1px solid white';
            badge.style.zIndex = '1001';
            badge.style.pointerEvents = 'none';
            badge.title = 'Replan Required';
            el.appendChild(badge);
          }
          if (hub.is_late) {
            el.title = `${hub.name} - Will miss deadline (${hub.deadline_hours}h)`
          } else if (hub.replan_candidate) {
            el.title = `${hub.name} - Deadline changed, evaluating at next decision point`
          } else {
            el.title = `${hub.name} - Deadline: ${hub.deadline_hours}h`
          }
        }
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
    worldState.trucks.forEach(truck => {
      const isDriverTruck = driverTruckId === truck.id && role === 'driver_perspective';
      const isVisible = role !== 'driver_perspective' || isDriverTruck;
      if (!markers.current.trucks[truck.id]) {
        const el = createTruckElement();
        let positionLng, positionLat;
        if (!truck.active) {
          const centralHub = worldState.hubs.find(h => h.id === 'CENTRAL_DEPOT');
          if (centralHub) {
            const index = worldState.trucks.findIndex(t => t.id === truck.id);
            const angle = (index / worldState.trucks.length) * Math.PI * 2;
            const radius = 0.00015;
            positionLng = centralHub.longitude + Math.cos(angle) * radius;
            positionLat = centralHub.latitude + Math.sin(angle) * radius;
          } else {
            positionLng = truck.current_longitude;
            positionLat = truck.current_latitude;
          }
        } else {
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
        if (!truck.active) {
          const centralHub = worldState.hubs.find(h => h.id === 'CENTRAL_DEPOT');
          if (centralHub) {
            const index = worldState.trucks.findIndex(t => t.id === truck.id);
            const angle = (index / worldState.trucks.length) * Math.PI * 2;
            const radius = 0.00015;
            const offsetLng = centralHub.longitude + Math.cos(angle) * radius;
            const offsetLat = centralHub.latitude + Math.sin(angle) * radius;
            markers.current.trucks[truck.id].setLngLat([offsetLng, offsetLat]);
          }
        } else {
          markers.current.trucks[truck.id]
            .setLngLat([truck.current_longitude, truck.current_latitude])
        }
        const el = markers.current.trucks[truck.id].getElement()
        if (el) {
          const shouldBeVisible = role !== 'driver_perspective' || isDriverTruck;
          el.style.display = shouldBeVisible ? 'flex' : 'none';
        }
      }
      if (truck.full_route && truck.full_route.length > 1) {
        const routeId = `route-${truck.id}`
        const isFollowedTruck = selectedTruck === truck.id && role === 'driver'
        const isDriverTruck = driverTruckId === truck.id && role === 'driver_perspective'
        let lineColor, lineWidth, lineDashArray, lineOpacity, showRoute;
        if (role === 'driver_perspective') {
          if (isDriverTruck) {
            lineColor = '#FF0000';
            lineWidth = 8;
            lineDashArray = [1, 0];
            lineOpacity = 0.95;
            showRoute = true;
          } else {
            lineColor = '#000000';
            lineWidth = 0;
            lineDashArray = [1, 0];
            lineOpacity = 0;
            showRoute = false;
          }
        } else if (role === 'manager') {
          lineColor = '#007bff';
          lineWidth = 2;
          lineDashArray = [1, 0];
          lineOpacity = 0.6;
          showRoute = true;
        } else if (isFollowedTruck) {
          lineColor = '#ff0000';
          lineWidth = 4;
          lineDashArray = [1, 0];
          lineOpacity = 0.9;
          showRoute = true;
        } else {
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
        if (map.current.getLayer(routeId)) {
          if (showRoute) {
            map.current.setPaintProperty(routeId, 'line-color', lineColor);
            map.current.setPaintProperty(routeId, 'line-width', lineWidth);
            map.current.setPaintProperty(routeId, 'line-dasharray', lineDashArray);
            map.current.setPaintProperty(routeId, 'line-opacity', lineOpacity);
          } else {
            map.current.setPaintProperty(routeId, 'line-opacity', 0);
          }
        }
      }
      if (role === 'driver_perspective' && driverTruckId === truck.id && truck.current_task) {
        const destinationHub = worldState.hubs.find(h => h.id === truck.current_task.hub_id);
        if (destinationHub) {
          const destMarkerId = `dest-${truck.id}`;
          const destColor = '#FF0000';
          if (markers.current.destinations?.[destMarkerId]) {
            markers.current.destinations[destMarkerId].remove();
          }
          if (!markers.current.destinations) {
            markers.current.destinations = {};
          }
          markers.current.destinations[destMarkerId] = new maplibregl.Marker()
            .setLngLat([destinationHub.longitude, destinationHub.latitude])
            .addTo(map.current);
        }
      } else {
        const destMarkerId = `dest-${truck.id}`;
        if (markers.current.destinations?.[destMarkerId]) {
          markers.current.destinations[destMarkerId].remove();
          delete markers.current.destinations[destMarkerId];
        }
      }
    })
    if (map.current) {
      const layers = map.current.getStyle().layers || [];
      layers.forEach(l => {
        if (l.id.startsWith('disaster-')) {
          map.current.removeLayer(l.id);
          const s = l.id.replace('layer', 'source');
          if (map.current.getSource(s)) map.current.removeSource(s);
        }
      });
    }
    if (worldState?.active_sensors && worldState.active_sensors.length > 0) {
      worldState.active_sensors.forEach(sensor => {
        if (!sensor || !sensor.sensor_id || !sensor.type) return
        const layerId = `sensor-layer-${sensor.sensor_id}`
        const sourceId = `sensor-source-${sensor.sensor_id}`
        let geojsonData
        if (sensor.type === 'weather_sensor') {
          const points = [];
          const sides = 64;
          for (let i = 0; i <= sides; i++) {
            const angle = (i / sides) * 2 * Math.PI;
            const lat = sensor.latitude + (sensor.radius_km / 111) * Math.cos(angle);
            const lng = sensor.longitude + (sensor.radius_km / (111 * Math.cos(sensor.latitude * Math.PI / 180))) * Math.sin(angle);
            points.push([lng, lat]);
          }
          geojsonData = {
            type: 'Feature',
            geometry: {
              type: 'Polygon',
              coordinates: [points]
            },
            properties: { sensor_type: sensor.type }
          };
        } else if (sensor.type === 'traffic_sensor') {
          if (sensor.start_latitude != null && sensor.end_latitude != null) {
            geojsonData = {
              type: 'Feature',
              geometry: {
                type: 'LineString',
                coordinates: [
                  [sensor.start_longitude, sensor.start_latitude],
                  [sensor.end_longitude, sensor.end_latitude]
                ]
              },
              properties: { sensor_type: sensor.type }
            };
          }
        }
        if (geojsonData) {
          if (!map.current.getSource(sourceId)) {
            map.current.addSource(sourceId, { type: 'geojson', data: geojsonData });
            let layerProps = {};
            if (sensor.type === 'weather_sensor') {
              layerProps = {
                id: layerId,
                type: 'fill',
                source: sourceId,
                paint: {
                  'fill-color': 'rgba(52, 152, 219, 0.25)',
                  'fill-outline-color': '#3498db',
                  'fill-opacity': 0.4
                }
              };
            } else {
              layerProps = {
                id: layerId,
                type: 'line',
                source: sourceId,
                paint: {
                  'line-color': '#FF4500',
                  'line-width': 12,
                  'line-opacity': 0.9,
                  'line-cap': 'round'
                }
              };
            }
            map.current.addLayer(layerProps);
          } else {
            map.current.getSource(sourceId).setData(geojsonData);
          }
        }
      });
    }
    const activeSensorIds = new Set(worldState?.active_sensors?.map(s => s.sensor_id) || []);
    const layers = map.current.getStyle().layers || [];
    layers.forEach(layer => {
      if (layer.id.startsWith('sensor-layer-')) {
        const sensorId = layer.id.replace('sensor-layer-', '');
        if (!activeSensorIds.has(sensorId)) {
          if (map.current.getLayer(layer.id)) map.current.removeLayer(layer.id);
          const sourceId = `sensor-source-${sensorId}`;
          if (map.current.getSource(sourceId)) map.current.removeSource(sourceId);
        }
      }
    });
  }, [worldState])
  useEffect(() => {
    if (!worldState || !worldState.trucks) return;
    worldState.trucks.forEach(truck => {
      const prevQueue = prevTruckRoutes.current[truck.id] || [];
      const currentQueue = truck.future_task_queue || [];
      if (prevQueue.length !== currentQueue.length) {
        setShowRouteChangeBanner(true);
        setRouteChangeMessage('Route updated by system');
        if (currentQueue.length > 0) {
          const newDestinationHubId = currentQueue[0]?.hub_id;
          if (newDestinationHubId && markers.current.hubs[newDestinationHubId]) {
            const hubMarkerEl = markers.current.hubs[newDestinationHubId].getElement();
            if (hubMarkerEl) {
              hubMarkerEl.style.transform = 'scale(1.2)';
              hubMarkerEl.style.transition = 'transform 0.3s ease';
              setTimeout(() => {
                if (hubMarkerEl && hubMarkerEl.style) {
                  hubMarkerEl.style.transform = 'scale(1)';
                }
              }, 1500);
            }
          }
        }
        setTimeout(() => {
          setShowRouteChangeBanner(false);
        }, 3000);
      } else {
        let orderChanged = false;
        for (let i = 0; i < prevQueue.length; i++) {
          if (prevQueue[i]?.hub_id !== currentQueue[i]?.hub_id ||
            prevQueue[i]?.urgency_weight !== currentQueue[i]?.urgency_weight) {
            orderChanged = true;
            break;
          }
        }
        if (orderChanged) {
          setShowRouteChangeBanner(true);
          setRouteChangeMessage('Route updated by system');
          if (currentQueue.length > 0) {
            const newDestinationHubId = currentQueue[0]?.hub_id;
            if (newDestinationHubId && markers.current.hubs[newDestinationHubId]) {
              const hubMarkerEl = markers.current.hubs[newDestinationHubId].getElement();
              if (hubMarkerEl) {
                hubMarkerEl.style.transform = 'scale(1.2)';
                hubMarkerEl.style.transition = 'transform 0.3s ease';
                setTimeout(() => {
                  if (hubMarkerEl && hubMarkerEl.style) {
                    hubMarkerEl.style.transform = 'scale(1)';
                  }
                }, 1500);
              }
            }
          }
          setTimeout(() => {
            setShowRouteChangeBanner(false);
          }, 3000);
        }
      }
      prevTruckRoutes.current[truck.id] = [...currentQueue];
    });
  }, [worldState]);
  useEffect(() => {
    if (role === 'driver' && selectedTruck && worldState && map.current) {
      const truck = worldState.trucks.find(t => t.id === selectedTruck);
      if (truck) {
        map.current.flyTo({
          center: [truck.current_longitude, truck.current_latitude],
          zoom: 12,
          duration: 500
        });
      }
    }
  }, [role, selectedTruck, worldState]);
  useEffect(() => {
    if (role !== 'driver' || !driverTruckId || selectedTruck !== null || !worldState || !map.current || !driverAutoFollow) return;
    const truck = worldState.trucks.find(t => t.id === driverTruckId);
    if (truck && truck.full_route && truck.full_route.length > 1) {
      let bearing = 0;
      if (truck.full_route.length > 1) {
        let closestIndex = 0;
        let minDistance = Infinity;
        for (let i = 0; i < truck.full_route.length; i++) {
          const point = truck.full_route[i];
          const dLat = (point.latitude - truck.current_latitude) * Math.PI / 180;
          const dLon = (point.longitude - truck.current_longitude) * Math.PI / 180;
          const a =
            Math.sin(dLat / 2) * Math.sin(dLat / 2) +
            Math.cos(truck.current_latitude * Math.PI / 180) * Math.cos(point.latitude * Math.PI / 180) *
            Math.sin(dLon / 2) * Math.sin(dLon / 2);
          const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
          const dist = 6371 * c;
          if (dist < minDistance) {
            minDistance = dist;
            closestIndex = i;
          }
        }
        if (closestIndex < truck.full_route.length - 1) {
          const nextPoint = truck.full_route[closestIndex + 1];
          const lat1 = truck.current_latitude * Math.PI / 180;
          const lat2 = nextPoint.latitude * Math.PI / 180;
          const dLon = (nextPoint.longitude - truck.current_longitude) * Math.PI / 180;
          const y = Math.sin(dLon) * Math.cos(lat2);
          const x = Math.cos(lat1) * Math.sin(lat2) - Math.sin(lat1) * Math.cos(lat2) * Math.cos(dLon);
          const brng = Math.atan2(y, x) * 180 / Math.PI;
          bearing = (brng + 360) % 360;
        }
      }
      map.current.flyTo({
        center: [truck.current_longitude, truck.current_latitude],
        zoom: 14,
        bearing: bearing,
        pitch: 45,
        duration: 1000
      });
    } else if (truck) {
      map.current.flyTo({
        center: [truck.current_longitude, truck.current_latitude],
        zoom: 14,
        duration: 1000
      });
    }
  }, [role, driverTruckId, worldState, driverAutoFollow]);
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
      setAddHubMode(false)
      console.log('Commit success:', response.data)
    } catch (error) {
      const errorMsg = error.response?.data?.detail || 'Commit failed - unknown error'
      setCommitError(errorMsg)
      setSimulationStarted(false)
      console.error('Commit failed:', errorMsg)
    }
  }
  const resetSimulation = async () => {
    if (window.confirm('Are you sure you want to reset the entire system? All current hubs and trucks will be cleared.')) {
      try {
        await axios.post(`${API_BASE}/simulation/reset`)
        setSimulationStarted(false)
        setCommitError(null)
        setHubModal({ show: false, mode: 'create', hub: null, lat: null, lng: null })
        console.log('System reset successful')
      } catch (error) {
        console.error('Reset failed:', error)
        alert('Failed to reset system: ' + (error.response?.data?.detail || error.message))
      }
    }
  }
  const stopSimulation = async () => {
    await axios.post(`${API_BASE}/simulation/stop`)
    setSimulationStarted(false)
  }
  const handleCreateHub = async (hubData) => {
    try {
      if (!hubData.deadline_hours || hubData.deadline_hours <= 0) {
        alert('Deadline hours is required and must be positive')
        return
      }
      const payload = {
        name: hubData.name,
        latitude: hubModal.lat,
        longitude: hubModal.lng,
        demand_quantity: parseInt(hubData.demand_quantity),
        demand_intensity: hubData.demand_intensity || 'Medium'
      }
      if (hubData.deadline_hours && parseFloat(hubData.deadline_hours) > 0) {
        payload.deadline_hours = parseFloat(hubData.deadline_hours)
      }
      console.log('[FRONTEND] Creating hub with payload:', payload)
      await axios.post(`${API_BASE}/hubs/manual`, payload)
      setHubModal({ show: false, mode: 'create', hub: null, lat: null, lng: null })
    } catch (error) {
      console.error('Error creating hub:', error)
      alert('Failed to create hub: ' + (error.response?.data?.detail || error.message))
    }
  }
  const handleUpdateHub = async (hubData) => {
    try {
      const DEPOT_LAT = 10.7905;
      const DEPOT_LON = 78.7047;
      const GLOBAL_SPEED_KMPH = 40.0;
      const targetLat = hubModal.hub.latitude;
      const targetLon = hubModal.hub.longitude;
      const dLat = (targetLat - DEPOT_LAT) * Math.PI / 180;
      const dLon = (targetLon - DEPOT_LON) * Math.PI / 180;
      const a = Math.sin(dLat / 2) * Math.sin(dLat / 2) +
        Math.cos(DEPOT_LAT * Math.PI / 180) * Math.cos(targetLat * Math.PI / 180) *
        Math.sin(dLon / 2) * Math.sin(dLon / 2);
      const distanceKm = 6371 * (2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a)));
      const minTimeHours = distanceKm / GLOBAL_SPEED_KMPH;
      const payload = {
        demand_quantity: parseInt(hubData.demand_quantity),
      };
      if (hubData.deadline_hours) {
        if (parseFloat(hubData.deadline_hours) < minTimeHours) {
          alert(`Demand Update Rejected: Deadline impossible.\nMinimum time based on GLOBAL_SPEED of 40km/h is ${minTimeHours.toFixed(2)}h.`);
          return;
        }
        const slack = parseFloat(hubData.deadline_hours) - minTimeHours;
        if (slack <= 0.5 && slack >= 0) {
          if (!window.confirm(`Warning: Deadline at high risk! Slack is only ${slack.toFixed(2)}h. Do you want to proceed?`)) {
            return;
          }
        }
        payload.deadline_hours = parseFloat(hubData.deadline_hours);
      }
      await axios.put(`${API_BASE}/hubs/${hubModal.hub.id}`, payload)
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
      alert('Successfully created some random hubs!')
    } catch (error) {
      console.error('Error creating random hubs:', error)
      alert('Failed to create random hubs: ' + (error.response?.data?.detail || error.message))
    }
  }
  const sendInstruction = async () => {
    if (!driverTruckId || !instructionText.trim()) return;
    try {
      await axios.post(`${API_BASE}/trucks/${driverTruckId}/instruction`, {
        instruction: instructionText
      });
      setInstructionText('');
      alert('Instruction sent successfully!');
    } catch (error) {
      console.error('Error sending instruction:', error);
      alert('Failed to send instruction');
    }
  };
  const toggleSensor = (type) => {
    if (sensorType === type) {
      setPlacementMode(!placementMode);
      console.log(`${type} toggle ${!placementMode ? 'ON' : 'OFF'}, placementMode: ${!placementMode}`);
    } else {
      setSensorType(type);
      setPlacementMode(true);
      console.log(`${type} selected and placementMode ON`);
    }
  };
  const createSensor = async (latitude, longitude, segmentStart = null, segmentEnd = null) => {
    if (!simulationStarted) {
      alert('Start simulation first to place sensors');
      return;
    }
    try {
      if (sensorType === 'rain') {
        const payload = {
          latitude: Number(latitude),
          longitude: Number(longitude),
          radius_km: Number(sensorRadius),
          rain_intensity: 0.6
        };
        await axios.post(`${API_BASE}/sensors/weather`, payload);
        alert(`Weather sensor activated (Rain).`);
      } else {
        if (segmentStart != null && segmentEnd != null) {
          const payload = {
            start_latitude: Number(segmentStart.latitude),
            start_longitude: Number(segmentStart.longitude),
            end_latitude: Number(segmentEnd.latitude),
            end_longitude: Number(segmentEnd.longitude),
            congestion_factor: 0.5
          };
          await axios.post(`${API_BASE}/sensors/traffic`, payload);
          alert(`Traffic sensor activated.`);
        } else {
          alert('Click directly on an active route for traffic sensors.');
        }
      }
      setPlacementMode(false);
    } catch (err) {
      console.error('Create sensor error:', err);
      const msg = err.response?.data?.detail ?? err.message ?? 'Failed to create sensor';
      alert(Array.isArray(msg) ? msg.join(', ') : msg);
    }
  };
  const handleSpeedChange = async (e) => {
    const newSpeed = parseFloat(e.target.value);
    setSimSpeed(newSpeed);
    try {
      await axios.post(`${API_BASE}/simulation/speed`, { speed: newSpeed });
    } catch (error) {
      console.error('Error changing simulation speed:', error);
    }
  };
  const handlePauseResume = async () => {
    try {
      if (simPaused) {
        await axios.post(`${API_BASE}/simulation/resume`);
        setSimPaused(false);
      } else {
        await axios.post(`${API_BASE}/simulation/pause`);
        setSimPaused(true);
      }
    } catch (error) {
      console.error('Error controlling simulation:', error);
    }
  };
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
  useEffect(() => {
    if (!simulationStarted) {
    }
  }, [simulationStarted]);
  const currentTruck = worldState?.trucks?.find(t => {
    if (role === 'driver_perspective' && driverTruckId) {
      return t.id === driverTruckId;
    } else if (role === 'driver' && selectedTruck) {
      return t.id === selectedTruck;
    }
    return false;
  });
  const truckDecision = worldState?.ai_decisions?.find(d => {
    if (role === 'driver_perspective' && driverTruckId) {
      return d.truck_id === driverTruckId;
    } else if (role === 'driver' && selectedTruck) {
      return d.truck_id === selectedTruck;
    }
    return false;
  });
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
          <div
            ref={mapContainer}
            style={{ position: 'absolute', inset: 0, cursor: placementMode ? 'crosshair' : 'default' }}
            onClick={(e) => {
              if (placementMode && activeMode === 'sensor' && role === 'manager') {
                e.preventDefault()
                e.stopPropagation()
              }
            }}
            onMouseDown={(e) => {
              if (placementMode && activeMode === 'sensor' && role === 'manager') {
                e.preventDefault()
                e.stopPropagation()
              }
            }}
          />
          { }
          {showRouteChangeBanner && (
            <div style={{
              position: 'fixed',
              top: '12px',
              left: '50%',
              transform: 'translateX(-50%)',
              backgroundColor: '#2ecc71',
              color: 'white',
              padding: '10px 20px',
              borderRadius: '4px',
              boxShadow: '0 2px 10px rgba(0,0,0,0.2)',
              zIndex: 2000,
              fontWeight: 'bold',
              fontSize: '14px',
              textAlign: 'center',
              animation: 'slideDown 0.3s ease-in-out'
            }}>
              {routeChangeMessage}
            </div>
          )}
          { }
          {showEtaIncreaseBanner && (
            <div style={{
              position: 'fixed',
              top: showRouteChangeBanner ? '60px' : '12px',
              left: '50%',
              transform: 'translateX(-50%)',
              backgroundColor: '#FF8C00',
              color: 'white',
              padding: '10px 20px',
              borderRadius: '4px',
              boxShadow: '0 2px 10px rgba(0,0,0,0.2)',
              zIndex: 2000,
              fontWeight: 'bold',
              fontSize: '14px',
              textAlign: 'center',
              animation: 'slideDown 0.3s ease-in-out',
              maxWidth: '600px'
            }}>
              {etaIncreaseMessage}
            </div>
          )}
          { }
          {/* Live Impacts Panel */}
          {simulationStarted && (
            <div style={{
              position: 'fixed',
              left: '20px',
              bottom: '20px',
              width: isImpactsPanelOpen ? '320px' : 'auto',
              maxHeight: 'calc(100vh - 100px)',
              backgroundColor: '#1e272e',
              color: '#ecf0f1',
              borderRadius: '10px',
              boxShadow: '0 8px 32px rgba(0,0,0,0.5)',
              zIndex: 2000,
              border: '1px solid #34495e',
              display: 'flex',
              flexDirection: 'column',
              overflow: 'hidden',
              cursor: isImpactsPanelOpen ? 'default' : 'pointer'
            }}>
              {/* Header / Toggle Bar */}
              <div
                onClick={() => setIsImpactsPanelOpen(!isImpactsPanelOpen)}
                style={{
                  padding: '12px 15px',
                  backgroundColor: '#2c3e50',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  cursor: 'pointer',
                  borderBottom: isImpactsPanelOpen ? '1px solid #34495e' : 'none'
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', fontWeight: 'bold' }}>
                  <span>⚡</span> Live Impacts & Decisions
                </div>
                <div>{isImpactsPanelOpen ? '▼' : '▲'}</div>
              </div>

              {/* Collapsible Content */}
              {isImpactsPanelOpen && (
                <div style={{ padding: '15px', overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: '15px' }}>

                  {/* AI Decisions */}
                  <div>
                    <h4 style={{ margin: '0 0 10px 0', fontSize: '14px', color: '#95a5a6' }}>Recent Decisions</h4>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                      {worldState?.ai_decisions?.slice(-10).reverse().map((d, i) => (
                        <div key={i} style={{ padding: '10px', backgroundColor: '#2c3e50', borderRadius: '6px', fontSize: '12px', borderLeft: d.decision.includes('DEADLINE') ? '4px solid #e74c3c' : (d.decision.includes('IMPACT') ? '4px solid #f39c12' : '4px solid #3498db') }}>
                          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '4px' }}>
                            <strong style={{ color: '#ecf0f1' }}>{d.truck_id}</strong>
                            <span style={{ color: '#bdc3c7', fontSize: '10px' }}>{new Date(d.timestamp * 1000).toISOString().substr(11, 8)}</span>
                          </div>
                          <div style={{ color: '#bdc3c7', marginBottom: '4px' }}>{d.decision}</div>
                          <div style={{ color: '#7f8c8d' }}>{d.explanation}</div>
                          {d.details && (
                            <button
                              onClick={() => setActiveRerouteDecision(d)}
                              style={{ marginTop: '8px', padding: '4px 8px', backgroundColor: '#2980b9', color: 'white', border: 'none', borderRadius: '4px', cursor: 'pointer', fontSize: '11px', width: '100%' }}
                            >
                              View Logic Details
                            </button>
                          )}
                        </div>
                      ))}
                      {(!worldState?.ai_decisions || worldState.ai_decisions.length === 0) && (
                        <div style={{ color: '#7f8c8d', fontStyle: 'italic', textAlign: 'center', padding: '10px' }}>No recent decisions</div>
                      )}
                    </div>
                  </div>

                  {/* Active Impacts */}
                  <div>
                    <h4 style={{ margin: '0 0 10px 0', fontSize: '14px', color: '#95a5a6' }}>Active Environment Impacts</h4>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                      {worldState?.active_sensors && worldState.active_sensors.length > 0 ? (
                        worldState.active_sensors.map((sensor, idx) => (
                          <div key={sensor.sensor_id} style={{
                            padding: '10px',
                            backgroundColor: '#16213e',
                            borderRadius: '6px',
                            fontSize: '11px',
                            borderLeft: `4px solid ${sensor.type === 'weather_sensor' ? '#4cc9f0' : '#f72585'}`
                          }}>
                            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '4px' }}>
                              <span style={{ fontWeight: 'bold', color: '#fff' }}>
                                {sensor.type === 'weather_sensor' ? '🌧 Rain Impact' : '🚦 Traffic Impact'}
                              </span>
                              <button
                                onClick={async () => {
                                  try {
                                    await axios.delete(`${API_BASE}/sensors/${sensor.sensor_id}`);
                                  } catch (e) { console.error(e); }
                                }}
                                style={{ backgroundColor: 'transparent', border: 'none', color: '#ff4d4d', cursor: 'pointer', fontSize: '14px', padding: '0 4px' }}
                                title="Remove Impact"
                              >×</button>
                            </div>
                            {sensor.type === 'weather_sensor' ? (
                              <>
                                <div style={{ color: '#ff9e00', fontWeight: 'bold' }}>Delay Impact: +{Math.round((1 / sensor.rain_intensity - 1) * 100)}%</div>
                              </>
                            ) : (
                              <>
                                <div style={{ color: '#ff4d4d', fontWeight: 'bold' }}>Delay Impact: +{Math.round((1 / sensor.congestion_factor - 1) * 100)}%</div>
                              </>
                            )}
                          </div>
                        ))
                      ) : (
                        <div style={{ color: '#7f8c8d', fontStyle: 'italic', textAlign: 'center', padding: '10px' }}>No active impacts</div>
                      )}
                    </div>
                  </div>
                </div>
              )}
            </div>
          )}
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
            { }
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
            { }
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
            { }
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
          { }
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
                    initialData={{ name: '', demand_quantity: 1, deadline_hours: 15.0 }}
                  />
                ) : (
                  <HubForm
                    onSubmit={handleUpdateHub}
                    onCancel={() => setHubModal({ show: false, mode: 'edit', hub: null, lat: null, lng: null })}
                    onDelete={!simulationStarted && hubModal.hub?.id !== 'CENTRAL_DEPOT' ? handleDeleteHub : null}
                    initialData={{
                      name: hubModal.hub?.name || '',
                      demand_quantity: hubModal.hub?.demand_quantity || 1,
                      deadline_hours: hubModal.hub?.deadline_hours || 15.0,
                      id: hubModal.hub?.id,
                      replan_candidate: hubModal.hub?.replan_candidate
                    }}
                    isEdit={true}
                  />
                )}
              </div>
            </div>
          )}
        </>
      )}
      {activeRerouteDecision && (
        <RerouteBanner decision={activeRerouteDecision} />
      )}
      {showDashboard && (
        <FleetDashboard
          worldState={worldState}
          onClose={() => setShowDashboard(false)}
        />
      )}
      <div className="control-panel">
        <h2>🚚 Route Optimization System</h2>
        {simulationStarted && (
          <div className="role-selector">
            <button onClick={() => setRole('manager')} className={role === 'manager' ? 'active' : ''}>Manager</button>
            <button onClick={() => setRole('driver')} className={role === 'driver' ? 'active' : ''}>Driver Follow</button>
            <button onClick={() => {
              if (worldState?.trucks && worldState.trucks.length > 0) {
                const firstTruck = worldState.trucks[0];
                setDriverTruckId(firstTruck.id);
              }
              setRole('driver_perspective');
              localStorage.setItem('driverViewMode', 'DRIVER_FOLLOW');
            }} className={role === 'driver_perspective' ? 'active' : ''} style={{
              backgroundColor: role === 'driver_perspective' ? '#28a745' : '#17a2b8',
              color: 'white',
              fontWeight: 'bold'
            }}>Driver View</button>
            <button onClick={() => setShowDashboard(!showDashboard)} style={{
              backgroundColor: showDashboard ? '#ffc107' : '#e9ecef',
              color: '#212529',
              fontWeight: 'bold',
              border: '2px solid #ffc107',
              borderRadius: '4px',
              padding: '8px',
              cursor: 'pointer',
              flex: 1
            }}>🛰 Fleet Dashboard</button>
          </div>
        )}
        {(role === 'manager' || role === 'driver') && (
          <>
            { }
            {role === 'manager' && (
              <>
                {!simulationStarted && (
                  <>
                    <label>Trucks CSV</label>
                    <input type="file" onChange={e => handleFileUpload('trucks', e.target.files[0])} />
                  </>
                )}
                {!simulationStarted && (
                  <>
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
                        className="control-btn"
                        onClick={handleCreateRandomHubs}
                        disabled={worldState?.trucks?.length === 0}
                        title={worldState?.trucks?.length === 0 ? "Please upload trucks first" : "Create standard delivery fixed hubs"}
                        style={{
                          width: '100%',
                          backgroundColor: '#17a2b8',
                          opacity: worldState?.trucks?.length === 0 ? 0.6 : 1
                        }}
                      >
                        📍 Create Fixed Hubs
                      </button>
                    </div>
                  </>
                )}
                { }
                {role === 'manager' && (
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
                            simulationStarted ? (
                              <button
                                disabled
                                style={{
                                  padding: '4px 8px',
                                  backgroundColor: '#6c757d',
                                  color: 'white',
                                  border: 'none',
                                  borderRadius: '4px',
                                  cursor: 'not-allowed',
                                  fontSize: '12px'
                                }}
                                title="Hubs cannot be deleted after simulation start"
                              >
                                🗑 Delete
                              </button>
                            ) : (
                              <button
                                onClick={async () => {
                                  if (window.confirm('Delete this hub permanently?')) {
                                    try {
                                      await axios.delete(`${API_BASE}/hubs/${hub.id}`);
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
                            )
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
                {!simulationStarted && (
                  <div style={{ marginTop: '10px', display: 'flex', gap: '10px' }}>
                    <button className="btn btn-success" onClick={startSimulation} style={{ flex: 1 }}>Start</button>
                    <button
                      className="btn btn-secondary"
                      onClick={resetSimulation}
                      style={{
                        flex: 1,
                        backgroundColor: '#6c757d',
                        color: 'white',
                        padding: '8px',
                        borderRadius: '4px',
                        border: 'none',
                        cursor: 'pointer'
                      }}
                    >
                      Reset
                    </button>
                  </div>
                )}
                { }
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
            )
            }
            { }
            {
              simulationStarted && (
                <>
                  <h3 style={{ marginTop: '15px', color: '#28a745' }}>🟢 System Active ({worldState?.simulation_phase || 'executing'})</h3>
                  { }
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
                  { }
                  {role === 'manager' && (
                    <div style={{ marginTop: '15px' }}>
                      <h4>Delivery Deadlines</h4>
                      <p style={{ fontSize: '11px', color: '#888', marginBottom: '10px' }}>
                        Edit delivery deadlines. Changes are evaluated conservatively at the next safe decision point.
                      </p>
                      {worldState?.hubs?.filter(h => h.id !== 'CENTRAL_DEPOT' && !h.delivered).map(hub => (
                        <HubDeadlineCard
                          key={hub.id}
                          hub={hub}
                          onDeadlineChange={async (hubId, deadlineHours) => {
                            try {
                              await axios.put(`${API_BASE}/hubs/${hubId}/deadline`, {
                                deadline_hours: deadlineHours
                              })
                            } catch (error) {
                              console.error('Error updating deadline:', error)
                            }
                          }}
                        />
                      ))}
                      { }
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
              )
            }
            {
              role === 'manager' && (
                <div style={{
                  position: 'fixed',
                  bottom: '20px',
                  right: '20px',
                  width: '280px',
                  backgroundColor: 'white',
                  padding: '15px',
                  borderRadius: '8px',
                  boxShadow: '0 4px 12px rgba(0,0,0,0.15)',
                  zIndex: 2000,
                  border: '1px solid #ddd'
                }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '10px' }}>
                    <h4 style={{ margin: '0', color: '#2c3e50' }}>Add Live Impact</h4>
                    <button
                      type="button"
                      onClick={() => setActiveMode(activeMode === 'sensor' ? 'monitoring' : 'sensor')}
                      style={{
                        padding: '4px 8px',
                        backgroundColor: activeMode === 'sensor' ? '#007bff' : '#f8f9fa',
                        color: activeMode === 'sensor' ? 'white' : '#333',
                        border: '1px solid #ccc',
                        borderRadius: '4px',
                        cursor: 'pointer',
                        fontSize: '12px',
                        transition: 'all 0.2s ease'
                      }}
                    >
                      {activeMode === 'sensor' ? 'Cancel' : 'Add Impact'}
                    </button>
                  </div>
                  {activeMode === 'sensor' && (
                    <>
                      <div style={{ marginBottom: '10px' }}>
                        <label style={{ display: 'block', marginBottom: '5px', fontWeight: 'bold' }}>Select Impact Type:</label>
                        <div style={{ display: 'flex', gap: '5px' }}>
                          <button type="button" onClick={() => toggleSensor('rain')} style={{ flex: 1, padding: '5px 10px', backgroundColor: placementMode && sensorType === 'rain' ? '#3498db' : '#f8f9fa', color: placementMode && sensorType === 'rain' ? 'white' : '#2c3e50', border: '1px solid #bdc3c7', borderRadius: '4px', cursor: 'pointer', fontSize: '11px' }}>🌧 Add Rain {placementMode && sensorType === 'rain' ? '(ON)' : ''}</button>
                          <button type="button" onClick={() => toggleSensor('traffic')} style={{ flex: 1, padding: '5px 10px', backgroundColor: placementMode && sensorType === 'traffic' ? '#e67e22' : '#f8f9fa', color: placementMode && sensorType === 'traffic' ? 'white' : '#2c3e50', border: '1px solid #bdc3c7', borderRadius: '4px', cursor: 'pointer', fontSize: '11px' }}>🚦 Add Traffic {placementMode && sensorType === 'traffic' ? '(ON)' : ''}</button>
                        </div>
                      </div>
                      {sensorType === 'rain' && (
                        <div style={{ marginBottom: '10px' }}>
                          <label style={{ display: 'block', marginBottom: '5px', fontWeight: 'bold' }}>Coverage Radius (km):</label>
                          <input type="range" min="1" max="15" value={sensorRadius} onChange={e => setSensorRadius(Number(e.target.value))} style={{ width: '100%' }} />
                          <div style={{ fontSize: '12px', textAlign: 'center' }}>{sensorRadius} km</div>
                        </div>
                      )}
                      <p style={{ fontSize: '12px', color: '#e74c3c', fontWeight: 'bold', margin: '0' }}>
                        {placementMode ? `PLACING ${sensorType === 'rain' ? 'RAIN' : 'TRAFFIC'} IMPACT - Click on Map` : 'Impact Placement Offline...'}
                      </p>
                    </>
                  )}
                </div>
              )
            }
          </>
        )}
        {
          role === 'driver_perspective' && (
            <>
              <h3>Driver View: {driverTruckId || 'No Truck Assigned'}</h3>
              { }
              <div style={{ marginBottom: '10px' }}>
                <label style={{ display: 'block', marginBottom: '5px', fontWeight: 'bold' }}>Your Truck:</label>
                <select
                  value={driverTruckId || ''}
                  onChange={e => {
                    const truckId = e.target.value;
                    setDriverTruckId(truckId || null);
                    if (truckId && map.current) {
                      const truck = worldState?.trucks?.find(t => t.id === truckId);
                      if (truck) {
                        map.current.easeTo({
                          center: [truck.current_longitude, truck.current_latitude],
                          zoom: 14,
                          bearing: 0,
                          pitch: 0,
                          duration: 300,
                          easing: t => t
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
                { }
                <button
                  onClick={() => {
                    if (driverTruckId) {
                      localStorage.setItem('driverTruckId', driverTruckId);
                      localStorage.setItem('driverViewMode', 'DRIVER_NAVIGATION');
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
          )
        }
        {
          role === 'driver' && (
            <>
              <select
                value={selectedTruck || ''}
                onChange={e => {
                  const truckId = e.target.value;
                  setSelectedTruck(truckId || null);
                  if (truckId && map.current && role === 'driver') {
                    const truck = worldState?.trucks?.find(t => t.id === truckId);
                    if (truck) {
                      map.current.flyTo({
                        center: [truck.current_longitude, truck.current_latitude],
                        zoom: 12,
                        duration: 1000
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
          )
        }
      </div >
    </div >
  );
}
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
  const calculateFeasibility = () => {
    const DEPOT_LAT = 10.7905;
    const DEPOT_LON = 78.7047;
    const GLOBAL_SPEED_KMPH = 40.0;
    let targetLat = initialData.lat;
    let targetLon = initialData.lng;
    if (isEdit && formData.latitude) {
      targetLat = formData.latitude;
      targetLon = formData.longitude;
    }
    if (!targetLat || !targetLon) return null;
    const dLat = (targetLat - DEPOT_LAT) * Math.PI / 180;
    const dLon = (targetLon - DEPOT_LON) * Math.PI / 180;
    const a = Math.sin(dLat / 2) * Math.sin(dLat / 2) +
      Math.cos(DEPOT_LAT * Math.PI / 180) * Math.cos(targetLat * Math.PI / 180) *
      Math.sin(dLon / 2) * Math.sin(dLon / 2);
    const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
    const distanceKm = 6371 * c;
    const minTimeHours = distanceKm / GLOBAL_SPEED_KMPH;
    const slack = formData.deadline_hours - minTimeHours;
    let severity = "Low Risk";
    let color = "#2ecc71";
    if (slack < 0) {
      severity = "Not Possible";
      color = "#95a5a6";
    } else if (slack <= 0.5) {
      severity = "High Risk";
      color = "#e74c3c";
    } else if (slack <= 2.0) {
      severity = "Medium Risk";
      color = "#f39c12";
    }
    return { slack, severity, color, minTimeHours, distanceKm };
  };
  const feasibility = calculateFeasibility();
  const isSubmitDisabled = feasibility && feasibility.severity === "Not Possible";
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
          Demand Intensity (Urgency)
        </label>
        <select
          value={formData.demand_intensity || 'Medium'}
          onChange={(e) => setFormData({ ...formData, demand_intensity: e.target.value })}
          style={{ width: '100%', padding: '8px', borderRadius: '4px', border: '1px solid #ccc' }}
        >
          <option value="Low">Low</option>
          <option value="Medium">Medium</option>
          <option value="High">High</option>
          <option value="Emergency">Emergency</option>
        </select>
      </div>
      <div style={{ marginBottom: '15px' }}>
        <label style={{ display: 'block', marginBottom: '5px', fontWeight: 'bold' }}>
          Delivery Deadline (hours)
        </label>
        <input
          type="number"
          step="0.5"
          min="0.5"
          max="48"
          value={formData.deadline_hours}
          onChange={(e) => setFormData({ ...formData, deadline_hours: parseFloat(e.target.value) })}
          style={{
            width: '100%', padding: '8px', borderRadius: '4px', border: '1px solid #ccc',
            borderColor: feasibility && feasibility.severity === "Not Possible" ? '#e74c3c' : '#ccc'
          }}
          required
        />
        {feasibility && (
          <div style={{ marginTop: '8px', padding: '10px', backgroundColor: '#f8f9fa', borderRadius: '4px', fontSize: '12px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '4px' }}>
              <span style={{ fontWeight: 'bold' }}>Feasibility:</span>
              <span style={{
                backgroundColor: feasibility.color,
                color: 'white',
                padding: '2px 8px',
                borderRadius: '12px',
                fontWeight: 'bold',
                fontSize: '11px'
              }}>
                {feasibility.severity}
              </span>
            </div>
            <div style={{ color: '#555', marginTop: '4px' }}>
              Minimum Time: {feasibility.minTimeHours.toFixed(1)}h
              (Distance: {feasibility.distanceKm.toFixed(1)}km at 40km/h)
            </div>
            {feasibility.severity === "Not Possible" && (
              <div style={{ color: '#e74c3c', marginTop: '4px', fontWeight: 'bold' }}>
                Cannot save: Deadline must be at least {Math.ceil(feasibility.minTimeHours * 10) / 10}h
              </div>
            )}
            <small style={{ color: '#666', fontSize: '11px', display: 'block', marginTop: '8px' }}>
              Hours from simulation start. Planning guarantees deadline feasibility.
            </small>
          </div>
        )}
      </div>
      <div style={{ display: 'flex', gap: '10px', justifyContent: 'flex-end' }}>
        {formData.replan_candidate && (
          <button
            type="button"
            onClick={async () => {
              try {
                await axios.post(`${API_BASE}/hubs/${formData.id}/confirm-replan`);
                alert('Replan confirmed successfully!');
                onCancel();
              } catch (error) {
                console.error('Error confirming replan:', error);
                alert('Failed to confirm replan: ' + (error.response?.data?.detail || error.message));
              }
            }}
            style={{
              padding: '8px 16px',
              backgroundColor: '#ff6b35',
              color: 'white',
              border: 'none',
              borderRadius: '4px',
              cursor: 'pointer'
            }}
          >
            Confirm Replan
          </button>
        )}
        {onDelete && !simulationStarted && (
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
            title="Hubs cannot be deleted after simulation start"
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
          disabled={isSubmitDisabled}
          style={{
            padding: '8px 16px',
            backgroundColor: isSubmitDisabled ? '#95a5a6' : '#007bff',
            color: 'white',
            border: 'none',
            borderRadius: '4px',
            cursor: isSubmitDisabled ? 'not-allowed' : 'pointer'
          }}
        >
          {isEdit ? 'Save Changes' : 'Create Hub'}
        </button>
      </div>
    </form>
  )
}
function FleetDashboard({ worldState, onClose }) {
  if (!worldState) return null;
  return (
    <div style={{
      position: 'fixed',
      top: 0,
      right: 0,
      width: '600px',
      height: '100vh',
      backgroundColor: '#f4f7f6',
      boxShadow: '-4px 0 15px rgba(0,0,0,0.2)',
      zIndex: 5000,
      overflowY: 'auto',
      padding: '20px',
      borderLeft: '4px solid #ffc107'
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '20px' }}>
        <h2 style={{ margin: 0 }}>🛰 Fleet Command Dashboard</h2>
        <button
          onClick={onClose}
          style={{
            padding: '8px 16px',
            backgroundColor: '#dc3545',
            color: 'white',
            border: 'none',
            borderRadius: '4px',
            cursor: 'pointer',
            fontWeight: 'bold'
          }}
        >Close</button>
      </div>
      <div style={{ marginBottom: '20px', padding: '15px', backgroundColor: '#e9ecef', borderRadius: '8px' }}>
        <div style={{ fontSize: '14px', fontWeight: 'bold' }}>Simulation Intelligence Overview</div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '10px', marginTop: '10px' }}>
          <div>Global Speed: <strong>40.0 km/h</strong></div>
          <div>Simulation Time: <strong>{worldState.simulation_time.toFixed(2)}h</strong></div>
          <div>Active Trucks: <strong>{worldState.trucks?.filter(t => t.active).length}</strong></div>
          <div>Pending Hubs: <strong>{worldState.hubs?.filter(h => !h.delivered && h.id !== 'CENTRAL_DEPOT').length}</strong></div>
        </div>
      </div>
      {worldState.trucks?.filter(t => t.active).map(truck => {
        let totalDist = 0;
        let lastLat = truck.current_latitude;
        let lastLon = truck.current_longitude;
        const tasks = [];
        if (truck.current_task) tasks.push(truck.current_task);
        if (truck.future_task_queue) tasks.push(...truck.future_task_queue);
        let simTime = worldState.simulation_time;
        const timeline = tasks.map(task => {
          const hub = worldState.hubs.find(h => h.id === task.hub_id);
          if (!hub) return null;
          const d = haversine(lastLat, lastLon, hub.latitude, hub.longitude);
          totalDist += d;
          const travel = d / 40.0;
          simTime += travel;
          const slack = hub.deadline_hours - simTime;
          let riskColor = '#2ecc71';
          if (slack < 0.5) riskColor = '#e74c3c';
          else if (slack < 2.0) riskColor = '#f39c12';
          lastLat = hub.latitude;
          lastLon = hub.longitude;
          return {
            name: hub.name,
            eta: simTime,
            deadline: hub.deadline_hours,
            slack: slack,
            riskColor: riskColor,
            dist: d
          };
        }).filter(t => t !== null);
        const projectFinish = simTime;
        const worstSlack = timeline.length > 0 ? Math.min(...timeline.map(t => t.slack)) : 0;
        return (
          <div key={truck.id} style={{
            backgroundColor: 'white',
            borderRadius: '8px',
            padding: '15px',
            marginBottom: '20px',
            boxShadow: '0 2px 8px rgba(0,0,0,0.1)',
            borderLeft: `5px solid ${worstSlack < 0.5 ? '#e74c3c' : '#007bff'}`
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '10px' }}>
              <h3 style={{ margin: 0 }}>🚚 Truck {truck.id}</h3>
              <div style={{
                padding: '2px 8px',
                backgroundColor: truck.status === 'moving' ? '#d4edda' : '#fff3cd',
                color: truck.status === 'moving' ? '#155724' : '#856404',
                borderRadius: '4px',
                fontSize: '12px',
                fontWeight: 'bold'
              }}>{truck.status.toUpperCase()}</div>
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '10px', fontSize: '13px', marginBottom: '15px' }}>
              <div>Next: <strong>{truck.current_task ? worldState.hubs.find(h => h.id === truck.current_task.hub_id)?.name : 'None'}</strong></div>
              <div>Finish: <strong>{projectFinish.toFixed(2)}h</strong></div>
              <div>Distance Left: <strong>{totalDist.toFixed(1)} km</strong></div>
              <div>Worst Slack: <strong style={{ color: worstSlack < 0.5 ? '#e74c3c' : 'inherit' }}>{worstSlack.toFixed(2)}h</strong></div>
            </div>
            {timeline.length > 0 && (
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '11px' }}>
                <thead>
                  <tr style={{ borderBottom: '1px solid #ddd', textAlign: 'left' }}>
                    <th style={{ padding: '4px' }}>Hub</th>
                    <th style={{ padding: '4px' }}>ETA</th>
                    <th style={{ padding: '4px' }}>Deadline</th>
                    <th style={{ padding: '4px' }}>Slack</th>
                  </tr>
                </thead>
                <tbody>
                  {timeline.map((t, idx) => (
                    <tr key={idx} style={{ borderBottom: '1px solid #eee' }}>
                      <td style={{ padding: '4px' }}>{t.name}</td>
                      <td style={{ padding: '4px' }}>{t.eta.toFixed(2)}h</td>
                      <td style={{ padding: '4px' }}>{t.deadline.toFixed(2)}h</td>
                      <td style={{ padding: '4px', fontWeight: 'bold', color: t.riskColor }}>{t.slack.toFixed(2)}h</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
            { }
            <div style={{ marginTop: '15px', borderTop: '1px solid #eee', paddingTop: '10px' }}>
              <div style={{ fontSize: '11px', color: '#666', marginBottom: '5px' }}>Latest Intelligence</div>
              {worldState.ai_decisions?.filter(d => d.truck_id === truck.id).slice(-1).map((decision, idx) => (
                <div key={idx} style={{
                  padding: '8px',
                  backgroundColor: '#f8f9fa',
                  borderRadius: '4px',
                  fontSize: '11px',
                  borderLeft: '3px solid #007bff'
                }}>
                  <strong>{decision.decision}</strong>: {decision.explanation}
                  {decision.details?.evaluated_orders && (
                    <div style={{ marginTop: '5px', color: '#444' }}>
                      <details>
                        <summary style={{ cursor: 'pointer' }}>Show Evaluation Details</summary>
                        <div style={{ padding: '5px', background: '#eee', borderRadius: '4px', marginTop: '5px' }}>
                          {decision.details.evaluated_orders.map((order, oidx) => (
                            <div key={oidx} style={{ marginBottom: '5px', padding: '3px', borderBottom: '1px solid #ddd' }}>
                              Order: {order.order.join(' → ')} <br />
                              Feasible: <span style={{ color: order.feasible ? 'green' : 'red' }}>{order.feasible ? 'YES' : 'NO'}</span> |
                              Min Slack: {order.minimum_slack.toFixed(2)}h
                            </div>
                          ))}
                        </div>
                      </details>
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>
        );
      })}
    </div>
  )
}
function RerouteBanner({ decision }) {
  if (!decision || !decision.details) return null;
  const details = decision.details;
  return (
    <div style={{
      position: 'fixed',
      top: '20px',
      left: '50%',
      transform: 'translateX(-50%)',
      width: '500px',
      backgroundColor: 'white',
      borderRadius: '8px',
      boxShadow: '0 4px 20px rgba(0,0,0,0.3)',
      zIndex: 10000,
      padding: '20px',
      borderTop: '5px solid #ffc107',
      animation: 'slideDown 0.5s ease-out'
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '15px' }}>
        <h3 style={{ margin: 0 }}>🔁 Checkpoint Reroute Analysis</h3>
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          <span style={{ fontSize: '12px', color: '#666' }}>Truck {decision.truck_id}</span>
          <button
            onClick={() => setActiveRerouteDecision(null)}
            style={{
              background: 'none',
              border: 'none',
              color: '#999',
              cursor: 'pointer',
              fontSize: '18px',
              padding: '0'
            }}
          >×</button>
        </div>
      </div>
      <div style={{ fontSize: '13px', marginBottom: '15px' }}>
        <strong>Context:</strong> {decision.explanation}
      </div>
      <div style={{ fontSize: '12px', color: '#444' }}>
        <strong>Evaluated Orders:</strong>
        <div style={{ maxHeight: '150px', overflowY: 'auto', marginTop: '5px' }}>
          {details.evaluated_orders?.map((order, idx) => (
            <div key={idx} style={{
              marginBottom: '10px',
              padding: '8px',
              backgroundColor: order.feasible ? '#f0fdf4' : '#fef2f2',
              borderRadius: '4px',
              border: `1px solid ${order.feasible ? '#bcf0da' : '#fecaca'}`
            }}>
              <div style={{ fontWeight: 'bold', marginBottom: '3px' }}>
                {idx + 1}. {order.order.join(' → ')}
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                <span>Feasible: <strong style={{ color: order.feasible ? '#166534' : '#991b1b' }}>{order.feasible ? 'YES' : 'NO'}</strong></span>
                <span>Min Slack: <strong>{order.minimum_slack.toFixed(2)}h</strong></span>
              </div>
            </div>
          ))}
        </div>
      </div>
      <div style={{ marginTop: '15px', padding: '10px', backgroundColor: '#fffbeb', borderRadius: '4px', border: '1px solid #fef3c7' }}>
        <strong>Final Decision:</strong> {details.chosen_order?.join(' → ')}
      </div>
    </div>
  );
}
function HubDeadlineCard({ hub, onDeadlineChange }) {
  const [deadlineValue, setDeadlineValue] = useState(hub.deadline_hours || 15.0)
  const [isPending, setIsPending] = useState(false)
  const [showRejectMessage, setShowRejectMessage] = useState(false)
  const prevReplanCandidate = useRef(hub.replan_candidate)
  const pendingDeadlineValue = useRef(null)
  useEffect(() => {
    const newDeadline = hub.deadline_hours || 15.0
    setDeadlineValue(newDeadline)
    if (isPending && pendingDeadlineValue.current !== null &&
      Math.abs(newDeadline - pendingDeadlineValue.current) < 0.1 &&
      prevReplanCandidate.current && !hub.replan_candidate) {
      setShowRejectMessage(true)
      setIsPending(false)
      pendingDeadlineValue.current = null
      setTimeout(() => setShowRejectMessage(false), 5000)
    } else if (isPending && Math.abs(newDeadline - deadlineValue) < 0.1) {
      if (!hub.replan_candidate && prevReplanCandidate.current) {
        setIsPending(false)
        pendingDeadlineValue.current = null
      }
    }
    prevReplanCandidate.current = hub.replan_candidate
  }, [hub.deadline_hours, hub.replan_candidate])
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
      return { text: 'COMMITTED ✔', color: '#6c757d' }
    }
    return null
  }
  const handleDeadlineChange = async (newValue) => {
    const numValue = parseFloat(newValue)
    if (isNaN(numValue) || numValue < 0.5 || numValue > 48) return
    setDeadlineValue(numValue)
    setIsPending(true)
    pendingDeadlineValue.current = numValue
    setShowRejectMessage(false)
    try {
      await onDeadlineChange(hub.id, numValue)
    } catch (error) {
      console.error('Error updating deadline:', error)
      setDeadlineValue(hub.deadline_hours || 15.0)
      setIsPending(false)
      pendingDeadlineValue.current = null
    }
  }
  const ownership = getOwnershipBadge()
  const frozen = getFrozenBadge()
  const isLate = hub.is_late && hub.ownership_state !== 'COMPLETED'
  const isReplanCandidate = hub.replan_candidate && hub.ownership_state === 'ASSIGNED'
  return (
    <div style={{
      padding: '12px',
      margin: '8px 0',
      background: '#f8f9fa',
      borderRadius: '6px',
      border: '1px solid #ddd'
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
        <span style={{ fontWeight: 'bold', fontSize: '14px' }}>{hub.name}</span>
        <div style={{ display: 'flex', gap: '4px', alignItems: 'center' }}>
          {frozen && (
            <span style={{
              fontSize: '9px',
              padding: '2px 6px',
              borderRadius: '4px',
              backgroundColor: frozen.color,
              color: 'white',
              fontWeight: 'bold'
            }}>
              {frozen.text}
            </span>
          )}
          <span style={{
            fontSize: '10px',
            padding: '2px 6px',
            borderRadius: '4px',
            backgroundColor: ownership.color,
            color: 'white',
            fontWeight: 'bold'
          }}>
            {ownership.text}
          </span>
        </div>
      </div>
      <div style={{ marginBottom: '8px' }}>
        <label style={{ display: 'block', fontSize: '12px', fontWeight: 'bold', marginBottom: '4px', color: '#333' }}>
          Delivery Deadline (hours):
        </label>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <input
            type="number"
            step="0.5"
            min="0.5"
            max="48"
            value={deadlineValue}
            onChange={(e) => setDeadlineValue(parseFloat(e.target.value) || 0.5)}
            onBlur={(e) => handleDeadlineChange(e.target.value)}
            style={{
              flex: 1,
              padding: '6px 8px',
              borderRadius: '4px',
              border: '1px solid #ccc',
              fontSize: '13px'
            }}
          />
          <span style={{ fontSize: '12px', color: '#666' }}>hrs</span>
        </div>
        {isPending && (
          <div style={{ fontSize: '10px', color: '#ff9800', marginTop: '4px' }}>
            Pending decision point
          </div>
        )}
        {isLate && !isPending && (
          <div style={{ fontSize: '10px', color: '#dc3545', marginTop: '4px' }}>
            Will miss deadline
          </div>
        )}
        {isReplanCandidate && !isPending && !isLate && (
          <div style={{ fontSize: '10px', color: '#ff9800', marginTop: '4px' }}>
            Evaluated at next decision point
          </div>
        )}
        {showRejectMessage && (
          <div style={{ fontSize: '10px', color: '#6c757d', marginTop: '4px', fontStyle: 'italic' }}>
            Deadline change evaluated — no safe reroute available.
          </div>
        )}
      </div>
      <div style={{ fontSize: '10px', color: '#666', marginTop: '4px' }}>
        Deadline changes apply at the next safe decision point.
      </div>
    </div>
  )
}
export default App;
