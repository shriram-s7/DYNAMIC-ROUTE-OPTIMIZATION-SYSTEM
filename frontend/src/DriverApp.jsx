import React from 'react';
import { BrowserRouter as Router, Routes, Route, useParams } from 'react-router-dom';
import DriverView from './DriverView';
import './index.css';
function DriverApp() {
  const TruckView = () => {
    const { truckId } = useParams();
    return <DriverView truckId={truckId} />;
  };
  return (
    <Router>
      <Routes>
        <Route path="/driver/:truckId" element={<TruckView />} />
        {}
        <Route path="*" element={
          <div style={{
            display: 'flex',
            justifyContent: 'center',
            alignItems: 'center',
            height: '100vh',
            backgroundColor: '#f8f9fa',
            fontSize: '18px',
            color: '#6c757d'
          }}>
            <div>
              <h2>Driver Navigation</h2>
              <p>Please access via /driver/:truckId</p>
            </div>
          </div>
        } />
      </Routes>
    </Router>
  );
}
export default DriverApp;
