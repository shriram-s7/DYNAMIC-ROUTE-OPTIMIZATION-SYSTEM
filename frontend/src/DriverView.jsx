import React, { useState, useEffect, useRef } from 'react';
import maplibregl from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';
import axios from 'axios';
import './index.css';
const API_BASE = 'http://localhost:8000';
function createArrowElement() {
  const wrapper = document.createElement('div');
  wrapper.style.width = '48px';
  wrapper.style.height = '48px';
  wrapper.style.display = 'flex';
  wrapper.style.alignItems = 'center';
  wrapper.style.justifyContent = 'center';
  const arrow = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  arrow.setAttribute('viewBox', '0 0 100 100');
  arrow.setAttribute('width', '48');
  arrow.setAttribute('height', '48');
  arrow.style.overflow = 'visible';
  arrow.innerHTML = `
    <defs>
      <linearGradient id="split-blue" x1="0%" y1="0%" x2="100%" y2="0%">
        <stop offset="50%" stop-color="#1e6fe3" />
        <stop offset="50%" stop-color="#0b4fcf" />
      </linearGradient>
    </defs>
    <path
      d="M 50 5 L 90 95 L 50 75 L 10 95 Z"
      fill="url(#split-blue)"
      stroke="url(#split-blue)"
      stroke-width="8"
      stroke-linejoin="round"
    />
  `;
  wrapper.appendChild(arrow);
  return wrapper;
}
function DriverView({ truckId: propTruckId, mode: propMode }) {
  const urlParams = new URLSearchParams(window.location.search);
  const urlTruckId = urlParams.get('truckId');
  const storageTruckId = localStorage.getItem('driverTruckId');
  const effectiveTruckId = propTruckId || urlTruckId || storageTruckId;
  const storageMode = localStorage.getItem('driverViewMode');
  const initialMode = propMode || storageMode || 'DRIVER_FOLLOW';
  const [worldState, setWorldState] = useState(null);
  const [currentTruck, setCurrentTruck] = useState(null);
  const [currentHub, setCurrentHub] = useState(null);
  const [instruction, setInstruction] = useState(null);  
  const [acknowledgedInstructions, setAcknowledgedInstructions] = useState(new Set());  
  const [disasterNotifications, setDisasterNotifications] = useState([]);  
  const [bearing, setBearing] = useState(0); 
  const [mapMode, setMapMode] = useState(initialMode);  
  const mapContainer = useRef(null);
  const map = useRef(null);
  const mapInitialized = useRef(false);
  const markers = useRef({
    destination: null,
    truck: null
  });
  const truckPositionRef = useRef(null);
  const truckBearingRef = useRef(0);
  useEffect(() => {
    const interval = setInterval(async () => {
      try {
        const res = await axios.get(`${API_BASE}/state`);
        setWorldState(res.data);
      } catch (e) {
        console.error('Error fetching state:', e);
      }
    }, 1000);
    return () => clearInterval(interval);
  }, []);
  useEffect(() => {
    if (worldState && effectiveTruckId) {
      const truck = worldState.trucks?.find(t => t.id === effectiveTruckId);
      setCurrentTruck(truck);
      if (truck?.current_task?.hub_id) {
        const hub = worldState.hubs?.find(h => h.id === truck.current_task.hub_id);
        setCurrentHub(hub);
      }
      if (truck?.instructions && truck.instruction_status === 'ACTIVE') {
        setInstruction(truck.instructions);
      } else {
        setInstruction(null);
      }
      if (truck?.disaster_notifications && Array.isArray(truck.disaster_notifications)) {
        setDisasterNotifications(truck.disaster_notifications);
      } else {
        setDisasterNotifications([]);
      }
      if (truck) {
        truckPositionRef.current = [
          truck.current_longitude,
          truck.current_latitude
        ];
        let calculatedBearing = 0;
        if (truck.full_route && truck.full_route.length > 1) {
          if (truck.full_route.length > 1) {
              let segmentIndex = 0;
              let minDist = Infinity;
              for (let i = 0; i < truck.full_route.length - 1; i++) {
                const a = truck.full_route[i];
                const b = truck.full_route[i + 1];
                const midLat = (a.latitude + b.latitude) / 2;
                const midLon = (a.longitude + b.longitude) / 2;
                const dLat = (midLat - truck.current_latitude) * Math.PI / 180;
                const dLon = (midLon - truck.current_longitude) * Math.PI / 180;
                const dist = Math.sqrt(dLat * dLat + dLon * dLon);
                if (dist < minDist) {
                  minDist = dist;
                  segmentIndex = i;
                }
              }
              if (segmentIndex > 0 && segmentIndex < truck.full_route.length - 1) {
                const prev = truck.full_route[segmentIndex];
                const next = truck.full_route[segmentIndex + 1];
                const lat1 = prev.latitude * Math.PI / 180;
                const lat2 = next.latitude * Math.PI / 180;
                const dLon = (next.longitude - prev.longitude) * Math.PI / 180;
                const y = Math.sin(dLon) * Math.cos(lat2);
                const x =
                  Math.cos(lat1) * Math.sin(lat2) -
                  Math.sin(lat1) * Math.cos(lat2) * Math.cos(dLon);
                calculatedBearing = (Math.atan2(y, x) * 180 / Math.PI + 360) % 360;
              }
          }
        }
        truckBearingRef.current = calculatedBearing;
        setBearing(calculatedBearing); 
      }
    }
  }, [worldState, effectiveTruckId]);
  useEffect(() => {
    if (mapInitialized.current || !mapContainer.current) return;
    const initialMode = 'DRIVER_FOLLOW';
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
      zoom: 5,
      bearing: 0,  
      pitch: 0,
      renderWorldCopies: false
    });
    map.current.on('load', () => {
      map.current.setPaintProperty('osm-layer', 'raster-opacity', 1);
      const layers = map.current.getStyle().layers;
      if (layers) {
        layers.forEach(layer => {
          if (layer.type === 'symbol' && 
              (layer.id.includes('label') || 
               layer.id.includes('place') || 
               layer.id.includes('poi') ||
               layer.id.includes('text'))
          ) {
            map.current.setLayoutProperty(layer.id, 'visibility', 'none');
          }
        });
      }
    });
    mapInitialized.current = true;
    return () => {
      if (map.current) {
        map.current.remove();
        mapInitialized.current = false;
      }
    };
  }, []);
  const [autoFollow, setAutoFollow] = useState(true);
  const [followTimeout, setFollowTimeout] = useState(null);
  useEffect(() => {
    if (!map.current || !mapInitialized.current) return;
    if (mapMode !== "DRIVER_FOLLOW" && mapMode !== "DRIVER_NAVIGATION") return;
    let animationFrameId;
    const followCamera = () => {
      if (!truckPositionRef.current) {
        animationFrameId = requestAnimationFrame(followCamera);
        return;
      }
      const isNavigation = mapMode === "DRIVER_NAVIGATION";
      map.current.easeTo({
        center: truckPositionRef.current,
        zoom: isNavigation ? 15.8 : 14,
        bearing: isNavigation ? truckBearingRef.current : 0,
        pitch: isNavigation ? 40 : 0,
        offset: isNavigation
          ? [0, map.current.getCanvas().height * 0.15] 
          : [0, 0],
        duration: 0   
      });
      animationFrameId = requestAnimationFrame(followCamera);
    };
    followCamera();
    return () => cancelAnimationFrame(animationFrameId);
  }, [mapMode, autoFollow]);
  useEffect(() => {
    if (!map.current || !mapInitialized.current) return;
    const handleMapMove = () => {
      if (autoFollow) {
        setAutoFollow(false);
        if (followTimeout) {
          clearTimeout(followTimeout);
        }
        const timeout = setTimeout(() => {
          setAutoFollow(true);
          setFollowTimeout(null);
        }, 7000);
        setFollowTimeout(timeout);
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
      if (followTimeout) {
        clearTimeout(followTimeout);
      }
    };
  }, [autoFollow, followTimeout]);
  useEffect(() => {
    if (!map.current || !currentTruck || !currentTruck.full_route || !mapInitialized.current) return;
    const routeId = 'driver-route';
    let routeToRender = currentTruck.full_route;
    if (mapMode === 'DRIVER_NAVIGATION') {
      let closestIndex = 0;
      let minDistance = Infinity;
      for (let i = 0; i < currentTruck.full_route.length; i++) {
        const point = currentTruck.full_route[i];
        const dLat = (point.latitude - currentTruck.current_latitude) * Math.PI / 180;
        const dLon = (point.longitude - currentTruck.current_longitude) * Math.PI / 180;
        const a = 
          Math.sin(dLat/2) * Math.sin(dLat/2) +
          Math.cos(currentTruck.current_latitude * Math.PI / 180) * Math.cos(point.latitude * Math.PI / 180) * 
          Math.sin(dLon/2) * Math.sin(dLon/2);
        const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1-a));
        const dist = 6371 * c; 
        if (dist < minDistance) {
          minDistance = dist;
          closestIndex = i;
        }
      }
      routeToRender = currentTruck.full_route.slice(closestIndex);
    }
    const geojson = {
      type: 'Feature',
      geometry: {
        type: 'LineString',
        coordinates: routeToRender.map(p => [
          p.longitude,
          p.latitude
        ])
      }
    };
    if (map.current.getSource(routeId)) {
      map.current.getSource(routeId).setData(geojson);
    } else {
      map.current.addSource(routeId, {
        type: 'geojson',
        data: geojson
      });
      map.current.addLayer({
        id: routeId,
        type: 'line',
        source: routeId,
        paint: {
          'line-color': '#FF0000',  
          'line-width': 8,
          'line-opacity': 0.95,
          'line-blur': 0.5
        }
      });
    }
  }, [currentTruck, mapMode]);
  useEffect(() => {
    if (!map.current || !mapInitialized.current || !worldState) return;
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
    if (worldState?.disasters && worldState.disasters.length > 0) {
      worldState.disasters.forEach(disaster => {
        const disasterId = `disaster-${disaster.id}`;
        const layerId = `disaster-layer-${disaster.id}`;
        const sourceId = `disaster-source-${disaster.id}`;
        let geojsonData;
        if (disaster.disaster_type === 'rain') {
          const points = [];
          const sides = 64; 
          for (let i = 0; i <= sides; i++) {
            const angle = (i / sides) * 2 * Math.PI;
            const lat = disaster.latitude + (disaster.radius_km / 111) * Math.cos(angle); 
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
        } else if (disaster.disaster_type === 'traffic' || disaster.disaster_type === 'road_block') {
          const truckId = disaster.affected_truck_id;
          const startIdx = disaster.affected_segment_start_idx;
          const endIdx = disaster.affected_segment_end_idx;
          if (truckId != null && startIdx != null && endIdx != null) {
            const affectedTruck = worldState.trucks.find(t => t.id === truckId);
            const route = affectedTruck ? (affectedTruck.full_route || affectedTruck.route) : null;
            if (route && route.length >= 2) {
              const si = Math.max(0, Math.min(startIdx, route.length - 1));
              const ei = Math.max(si, Math.min(endIdx, route.length - 1));
              const segmentPoints = [];
              for (let i = si; i <= ei; i++) {
                segmentPoints.push([route[i].longitude, route[i].latitude]);
              }
              if (segmentPoints.length >= 2) {
                geojsonData = {
                  type: 'Feature',
                  geometry: { type: 'LineString', coordinates: segmentPoints },
                  properties: { disaster_type: disaster.disaster_type }
                };
              }
            }
          }
          if (!geojsonData) {
            const lat = disaster.snapped_coordinates?.latitude ?? disaster.latitude;
            const lng = disaster.snapped_coordinates?.longitude ?? disaster.longitude;
            const d = 0.008;
            geojsonData = {
              type: 'Feature',
              geometry: { type: 'LineString', coordinates: [[lng - d, lat], [lng + d, lat]] },
              properties: { disaster_type: disaster.disaster_type }
            };
          }
        }
        if (geojsonData) {
          map.current.addSource(sourceId, {
            type: 'geojson',
            data: geojsonData
          });
        }
        if (geojsonData) {
          let layerType, paintProps;
          if (disaster.disaster_type === 'rain') {
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
          } else if (disaster.disaster_type === 'traffic' || disaster.disaster_type === 'road_block') {
            layerType = 'line';
            paintProps = {
              'line-color': disaster.disaster_type === 'traffic' ? '#FF8C00' : '#e74c3c',
              'line-width': disaster.disaster_type === 'traffic' ? 16 : 14,
              'line-opacity': 1,
              'line-dasharray': [1, 0],
              'line-cap': 'round',
              'line-join': 'round'
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
  }, [worldState]);
  useEffect(() => {
  if (!map.current || !currentTruck || !mapInitialized.current) return;
  if (!markers.current.truck) {
    const el = createArrowElement();
    markers.current.truck = new maplibregl.Marker({
        element: el,
        anchor: 'center',
      })
      .setLngLat([
        currentTruck.current_longitude,
        currentTruck.current_latitude
      ])
      .addTo(map.current);
  } else {
    markers.current.truck.setLngLat([
      currentTruck.current_longitude,
      currentTruck.current_latitude
    ]);
  }
}, [currentTruck, bearing]);
  useEffect(() => {
    if (!map.current || !currentHub || !mapInitialized.current) return;
    if (markers.current.destination) {
      markers.current.destination.remove();
    }
    markers.current.destination = new maplibregl.Marker()
      .setLngLat([currentHub.longitude, currentHub.latitude])
      .addTo(map.current);
  }, [currentHub]);
  const calculateRemainingDistance = () => {
    if (!currentTruck?.full_route) return 0;
    const route = currentTruck.full_route;
    if (route.length === 0) return 0;
    let distance = 0;
    let closestPointIndex = 0;
    let minDistance = Infinity;
    for (let i = 0; i < route.length; i++) {
      const point = route[i];
      const dLat = (point.latitude - currentTruck.current_latitude) * Math.PI / 180;
      const dLon = (point.longitude - currentTruck.current_longitude) * Math.PI / 180;
      const a = 
        Math.sin(dLat/2) * Math.sin(dLat/2) +
        Math.cos(currentTruck.current_latitude * Math.PI / 180) * Math.cos(point.latitude * Math.PI / 180) * 
        Math.sin(dLon/2) * Math.sin(dLon/2);
      const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1-a));
      const dist = 6371 * c; 
      if (dist < minDistance) {
        minDistance = dist;
        closestPointIndex = i;
      }
    }
    for (let i = closestPointIndex; i < route.length - 1; i++) {
      const point1 = route[i];
      const point2 = route[i + 1];
      const dLat = (point2.latitude - point1.latitude) * Math.PI / 180;
      const dLon = (point2.longitude - point1.longitude) * Math.PI / 180;
      const a = 
        Math.sin(dLat/2) * Math.sin(dLat/2) +
        Math.cos(point1.latitude * Math.PI / 180) * Math.cos(point2.latitude * Math.PI / 180) * 
        Math.sin(dLon/2) * Math.sin(dLon/2);
      const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1-a));
      distance += 6371 * c; 
    }
    return distance.toFixed(1);
  };
  const calculateRemainingTime = () => {
    if (!currentTruck || currentTruck.status !== 'moving') return 'N/A';
    const distance = calculateRemainingDistance();
    const speed = currentTruck.speed || 40; 
    if (speed <= 0) return 'N/A';
    const timeInHours = distance / speed;
    const hours = Math.floor(timeInHours);
    const minutes = Math.round((timeInHours - hours) * 60);
    return `${hours}h ${minutes}m`;
  };
  return (
    <div style={{ 
      position: 'relative', 
      height: '100vh', 
      width: '100vw',
      overflow: 'hidden'
    }}>
      <div 
        ref={mapContainer} 
        style={{ 
          position: 'absolute', 
          inset: 0 
        }} 
      />
      {}
      <div style={{
        position: 'absolute',
        top: '20px',
        left: '20px',
        backgroundColor: 'rgba(0, 0, 0, 0.85)',
        borderRadius: '12px',
        padding: '15px',
        boxShadow: '0 4px 20px rgba(0,0,0,0.3)',
        zIndex: 1000,
        maxWidth: '400px',
        color: 'white'
      }}>
        {}
        {disasterNotifications.length > 0 && (
          <div style={{
            position: 'absolute',
            top: '-30px',
            left: '0',
            right: '0',
            backgroundColor: disasterNotifications[0].includes('blocked') ? '#e74c3c' : disasterNotifications[0].includes('rain') ? '#3498db' : '#f39c12',
            color: 'white',
            padding: '8px',
            borderRadius: '4px',
            textAlign: 'center',
            fontWeight: 'bold',
            fontSize: '14px',
            zIndex: 1001
          }}>
            {disasterNotifications[0]}
          </div>
        )}
        <h3 style={{ margin: '0 0 10px 0', color: '#ffffff' }}>Navigation</h3>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '15px' }}>
          <div>
            <div style={{ fontSize: '14px', color: '#bdc3c7', marginBottom: '4px' }}>Remaining Distance</div>
            <div style={{ fontSize: '20px', fontWeight: 'bold', color: '#ffffff' }}>
              {calculateRemainingDistance()} km
            </div>
          </div>
          <div>
            <div style={{ fontSize: '14px', color: '#bdc3c7', marginBottom: '4px' }}>Estimated Time</div>
            <div style={{ fontSize: '20px', fontWeight: 'bold', color: '#ffffff' }}>
              {calculateRemainingTime()}
            </div>
          </div>
          <div>
            <div style={{ fontSize: '14px', color: '#bdc3c7', marginBottom: '4px' }}>Current Task</div>
            <div style={{ fontSize: '16px', color: '#ffffff' }}>
              {currentHub ? `Deliver to ${currentHub.name}` : 'No active task'}
            </div>
          </div>
          <div>
            <div style={{ fontSize: '14px', color: '#bdc3c7', marginBottom: '4px' }}>Status</div>
            <div style={{ 
              fontSize: '16px', 
              fontWeight: 'bold',
              color: currentTruck?.status === 'moving' ? '#27ae60' : '#f39c12'
            }}>
              {currentTruck?.status?.toUpperCase() || 'IDLE'}
            </div>
          </div>
        </div>
      </div>
      {}
      <div style={{
        position: 'absolute',
        top: '20px',
        right: '20px',
        width: '350px',
        backgroundColor: 'rgba(0, 0, 0, 0.85)',
        borderRadius: '12px',
        padding: '15px',
        boxShadow: '0 4px 20px rgba(0,0,0,0.3)',
        zIndex: 1000,
        maxHeight: 'calc(100vh - 40px)',
        overflowY: 'auto',
        color: 'white'
      }}>
        <h4 style={{ margin: '0 0 15px 0', color: '#ffffff' }}>Manager Instructions</h4>
        {instruction ? (
          <div style={{ marginBottom: '15px' }}>
            <div style={{ 
              fontSize: '15px', 
              color: '#ffffff',
              lineHeight: '1.5',
              backgroundColor: 'rgba(255, 255, 255, 0.1)',
              padding: '10px',
              borderRadius: '4px',
              borderLeft: '4px solid #007bff',
              marginBottom: '10px'
            }}>
              {instruction}
            </div>
            <button
              onClick={async () => {
                try {
                  await axios.post(`${API_BASE}/trucks/${effectiveTruckId}/acknowledge-instruction`);
                  setAcknowledgedInstructions(prev => new Set([...prev, instruction]));
                  setInstruction(null);
                } catch (error) {
                  console.error('Error acknowledging instruction:', error);
                  setAcknowledgedInstructions(prev => new Set([...prev, instruction]));
                  setInstruction(null);
                }
              }}
              style={{
                marginTop: '5px',
                padding: '8px 16px',
                backgroundColor: '#28a745',
                color: 'white',
                border: 'none',
                borderRadius: '4px',
                cursor: 'pointer',
                fontSize: '14px',
                width: '100%'
              }}
            >
              Noted
            </button>
          </div>
        ) : (
          <div style={{ 
            fontSize: '14px', 
            color: '#bdc3c7',
            fontStyle: 'italic',
            textAlign: 'center',
            padding: '20px 0',
            minHeight: '80px',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center'
          }}>
            <div>
              <div>No instructions from manager</div>
              <small style={{ fontSize: '12px', display: 'block', marginTop: '5px', color: '#95a5a6' }}>Waiting for instructions...</small>
            </div>
          </div>
        )}
      </div>
      {}
      <div style={{
        position: 'absolute',
        bottom: '20px',
        left: '20px',
        right: '370px', 
        backgroundColor: 'rgba(0, 0, 0, 0.85)',
        borderRadius: '12px',
        padding: '15px',
        boxShadow: '0 4px 20px rgba(0,0,0,0.3)',
        zIndex: 1000,
        color: 'white'
      }}>
        <h4 style={{ margin: '0 0 10px 0', color: '#ffffff' }}>Route Information</h4>
        <div style={{ 
          fontSize: '14px', 
          color: '#ffffff',
          lineHeight: '1.5'
        }}>
          {currentHub ? (
            <p>
              Proceed to <strong>{currentHub.name}</strong> for delivery. 
              Follow the red route on your map. Estimated arrival: {calculateRemainingTime()}.
            </p>
          ) : (
            <p>
              No active delivery task. Return to depot or wait for new instructions.
            </p>
          )}
          {currentTruck?.current_task?.instructions && !instruction && (
            <p style={{ marginTop: '8px', fontStyle: 'italic' }}>
              Additional: {currentTruck.current_task.instructions}
            </p>
          )}
        </div>
      </div>
    </div>
  );
}
DriverView.setNavigationMode = function() {
};
export default DriverView;
