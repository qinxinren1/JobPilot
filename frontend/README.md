# ApplyPilot Frontend

React + TypeScript frontend for ApplyPilot web interface.

## Setup

1. Install dependencies:
```bash
npm install
```

2. Start development server:
```bash
npm run dev
```

The frontend will run on http://localhost:3000

## Build

Build for production:
```bash
npm run build
```

The built files will be in the `dist` directory.

## Development

- Frontend runs on port 3000 (Vite dev server)
- Backend API runs on port 8000 (FastAPI)
- Vite proxy is configured to forward `/api` requests to the backend

## Environment Variables

Create a `.env` file in the frontend directory:

```
VITE_API_URL=http://localhost:8000
```
