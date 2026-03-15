import { useState } from 'react'
import { BrowserRouter, Routes, Route } from 'react-router-dom'
import ProfilePage from './pages/ProfilePage'
import ApplyTrackerPage from './pages/ApplyTrackerPage'
import './App.css'

function App() {
  const [activeMainTab, setActiveMainTab] = useState<'profile' | 'tracker'>('profile')

  return (
    <BrowserRouter>
      <div className="app">
        <header className="app-header">
          <h1>JobPilot</h1>
          <div className="main-tabs">
            <button
              className={`main-tab ${activeMainTab === 'profile' ? 'active' : ''}`}
              onClick={() => setActiveMainTab('profile')}
            >
              Profile Management
            </button>
            <button
              className={`main-tab ${activeMainTab === 'tracker' ? 'active' : ''}`}
              onClick={() => setActiveMainTab('tracker')}
            >
              Apply Tracker
            </button>
          </div>
        </header>
        <main className="app-main">
          <Routes>
            <Route 
              path="/" 
              element={
                activeMainTab === 'profile' ? <ProfilePage /> :
                <ApplyTrackerPage />
              } 
            />
            <Route path="/profile" element={<ProfilePage />} />
            <Route path="/tracker" element={<ApplyTrackerPage />} />
          </Routes>
        </main>
      </div>
    </BrowserRouter>
  )
}

export default App
