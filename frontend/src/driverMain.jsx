import React from 'react';
import { createRoot } from 'react-dom/client';
import DriverView from './DriverView';  
import './index.css';
const urlParams = new URLSearchParams(window.location.search);
let truckId = urlParams.get('truckId');
if (!truckId) {
  truckId = localStorage.getItem('driverTruckId');
}
const container = document.getElementById('root');
const root = createRoot(container);
root.render(
  <React.StrictMode>
    <DriverView truckId={truckId} />
  </React.StrictMode>
);
