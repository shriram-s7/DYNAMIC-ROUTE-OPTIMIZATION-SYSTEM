# Setup Instructions

## Hosted demo (no setup)

Open https://optiflow-dro.vercel.app. See [DEPLOYMENT.md](DEPLOYMENT.md) for how it works and how to run the demo build locally (`cd frontend && npm run dev:demo`).

## Quick Start

### 1. Backend Setup

```bash
cd backend
pip install -r requirements.txt
python main.py
```

The backend will start on `http://localhost:8000`

### 2. Frontend Setup

In a new terminal:

```bash
cd frontend
npm install
npm run dev
```

The frontend will start on `http://localhost:3000`

### 3. Using the System

1. Open `http://localhost:3000` in your browser
2. Upload `sample_data/hubs.csv` via the "Hubs CSV" upload button
3. Upload `sample_data/trucks.csv` via the "Trucks CSV" upload button
4. Click "Start Deployment" to begin the simulation
5. Toggle disruptions (Rain, Traffic, Roadblock) to see AI reactions
6. Switch between Manager and Driver views using the role selector

## System Design Summary

**Backend**: FastAPI with in-memory state, simulation loop, and AI decision engine
**Frontend**: React + MapLibre GL JS with real-time visualization
**Features**: CSV upload, real-time simulation, AI routing decisions, role-based views, disruption handling

