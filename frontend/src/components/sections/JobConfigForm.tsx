import { useState, useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import { searchConfigApi, profileApi, SearchConfig, SearchLocation, SearchDefaults } from '../../api/client'
import '../sections/SectionForm.css'
import './JobConfigForm.css'

interface JobConfigFormProps {
  data?: unknown
  onChange?: (data: unknown) => void
  onSave?: (config: SearchConfig) => void
  isSaving?: boolean
}

export default function JobConfigForm({ onSave, isSaving }: JobConfigFormProps) {
  // Defaults state
  const [defaults, setDefaults] = useState<SearchDefaults>({
    location: 'Netherlands',
    distance: 0,
    hours_old: 72,
    results_per_site: 50,
    experience_level: [],
  })

  // Locations state
  const [locations, setLocations] = useState<SearchLocation[]>([
    { location: 'Netherlands', remote: false },
  ])

  const { data: configData, isLoading } = useQuery({
    queryKey: ['searchConfig'],
    queryFn: searchConfigApi.getSearchConfig,
  })

  const { data: profileData } = useQuery({
    queryKey: ['profile'],
    queryFn: profileApi.getProfile,
  })

  // Load existing config
  useEffect(() => {
    if (configData?.config) {
      const config = configData.config

      // Load defaults
      if (config.defaults) {
        const level = config.defaults.experience_level
        setDefaults({
          location: config.defaults.location || 'Netherlands',
          distance: config.defaults.distance ?? 0,
          hours_old: config.defaults.hours_old ?? 72,
          results_per_site: config.defaults.results_per_site ?? 50,
          experience_level: Array.isArray(level) ? level : (level ? [level] : []),
        })
      } else if (config.location || config.distance !== undefined) {
        // Legacy format
        setDefaults({
          location: config.location || 'Netherlands',
          distance: config.distance ?? 0,
          hours_old: 72,
          results_per_site: 50,
          experience_level: [],
        })
      }

      // Load locations
      if (config.locations && Array.isArray(config.locations) && config.locations.length > 0) {
        setLocations(config.locations)
      } else if (config.location) {
        // Legacy format - create location from single location
        setLocations([{ location: config.location, remote: (config.distance ?? 0) === 0 }])
      }

    }
  }, [configData])

  const handleAddLocation = () => {
    const newLocation: SearchLocation = {
      location: defaults.location || 'Netherlands',
      remote: defaults.distance === 0,
    }
    setLocations([...locations, newLocation])
  }

  const handleRemoveLocation = (index: number) => {
    setLocations(locations.filter((_, i) => i !== index))
  }

  const handleUpdateLocation = (index: number, field: keyof SearchLocation, value: string | boolean) => {
    const updated = [...locations]
    updated[index] = { ...updated[index], [field]: value }
    setLocations(updated)
  }

  const handleSave = () => {
    if (onSave) {
      const config: SearchConfig = {
        defaults: {
          location: defaults.location,
          distance: defaults.distance,
          hours_old: defaults.hours_old,
          results_per_site: defaults.results_per_site,
          experience_level: defaults.experience_level,
        },
        locations: locations.length > 0 ? locations : [{ location: defaults.location, remote: defaults.distance === 0 }],
        queries: [], // Queries are auto-generated from target_roles, not manually edited
      }
      onSave(config)
    }
  }


  if (isLoading) {
    return (
      <div className="job-config-form">
        <div className="job-config-loading">Loading job configuration...</div>
      </div>
    )
  }

  return (
    <div className="job-config-form">
      <div className="job-config-header">
        <h3>Job Search Configuration</h3>
        <p className="job-config-description">
          Configure where and what types of jobs to search for. Set your target location, search radius, and preferred job roles with priority tiers.
        </p>
      </div>

      {/* Defaults Section */}
      <div className="job-config-section">
        <h4 className="job-config-section-title">Search Defaults</h4>
        <div className="job-config-grid">
          <div className="job-config-input-group">
            <label htmlFor="default-location" className="job-config-label">
              Default Location
              <span className="required">*</span>
            </label>
            <input
              id="default-location"
              type="text"
              value={defaults.location}
              onChange={(e) => setDefaults({ ...defaults, location: e.target.value })}
              placeholder="e.g. Netherlands, Amsterdam, Remote"
              className="job-config-input"
              required
            />
            <div className="job-config-hint">
              Examples: <span className="example">"Netherlands"</span>, <span className="example">"Amsterdam"</span>, <span className="example">"Remote"</span>
            </div>
          </div>

          <div className="job-config-input-group">
            <label htmlFor="default-distance" className="job-config-label">
              Search Radius (miles)
            </label>
            <input
              id="default-distance"
              type="number"
              min="0"
              value={defaults.distance}
              onChange={(e) => setDefaults({ ...defaults, distance: parseInt(e.target.value) || 0 })}
              className="job-config-input"
              required
            />
            <div className="job-config-hint">
              Set to <span className="example">0</span> for remote-only searches
            </div>
          </div>

          <div className="job-config-input-group">
            <label htmlFor="hours-old" className="job-config-label">
              Hours Old (max age)
            </label>
            <input
              id="hours-old"
              type="number"
              min="1"
              value={defaults.hours_old}
              onChange={(e) => setDefaults({ ...defaults, hours_old: parseInt(e.target.value) || 72 })}
              className="job-config-input"
            />
            <div className="job-config-hint">
              Only jobs posted within this many hours (default: <span className="example">72</span>)
            </div>
          </div>

          <div className="job-config-input-group">
            <label htmlFor="results-per-site" className="job-config-label">
              Results Per Site
            </label>
            <input
              id="results-per-site"
              type="number"
              min="1"
              value={defaults.results_per_site}
              onChange={(e) => setDefaults({ ...defaults, results_per_site: parseInt(e.target.value) || 50 })}
              className="job-config-input"
            />
            <div className="job-config-hint">
              Max results per board per query (default: <span className="example">50</span>)
            </div>
          </div>

          <div className="job-config-input-group">
            <label className="job-config-label">
              Experience Level (Multiple Selection)
            </label>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem', marginTop: '0.5rem' }}>
              {(['entry-level', 'senior', 'manager', 'director', 'executive'] as const).map((level) => (
                <label key={level} style={{ display: 'flex', alignItems: 'center', cursor: 'pointer' }}>
                  <input
                    type="checkbox"
                    checked={(defaults.experience_level || []).includes(level)}
                    onChange={(e) => {
                      const current = defaults.experience_level || []
                      if (e.target.checked) {
                        setDefaults({ ...defaults, experience_level: [...current, level] })
                      } else {
                        const updated = current.filter(l => l !== level)
                        setDefaults({ ...defaults, experience_level: updated })
                      }
                    }}
                    style={{ marginRight: '0.5rem' }}
                  />
                  <span>
                    {level === 'entry-level' && 'Entry-level'}
                    {level === 'senior' && 'Senior'}
                    {level === 'manager' && 'Manager'}
                    {level === 'director' && 'Director'}
                    {level === 'executive' && 'Executive'}
                  </span>
                </label>
              ))}
            </div>
            <div className="job-config-hint" style={{ marginTop: '0.5rem' }}>
              Select one or more experience levels to filter job results.
            </div>
          </div>
        </div>
      </div>

      {/* Locations Section */}
      <div className="job-config-section">
        <h4 className="job-config-section-title">Search Locations</h4>
        <div className="locations-list">
          {locations.map((loc, index) => (
            <div key={index} className="location-item">
              <div className="job-config-grid">
                <div className="job-config-input-group">
                  <label className="job-config-label">Location</label>
                  <input
                    type="text"
                    value={loc.location}
                    onChange={(e) => handleUpdateLocation(index, 'location', e.target.value)}
                    placeholder="e.g. Netherlands, Remote"
                    className="job-config-input"
                  />
                </div>
                <div className="job-config-input-group">
                  <label className="job-config-label">
                    <input
                      type="checkbox"
                      checked={loc.remote}
                      onChange={(e) => handleUpdateLocation(index, 'remote', e.target.checked)}
                      style={{ marginRight: '0.5rem' }}
                    />
                    Remote Only
                  </label>
                </div>
                <div className="job-config-input-group">
                  <button
                    type="button"
                    onClick={() => handleRemoveLocation(index)}
                    className="remove-location-button"
                    disabled={locations.length === 1}
                  >
                    Remove
                  </button>
                </div>
              </div>
            </div>
          ))}
          <button type="button" onClick={handleAddLocation} className="add-location-button">
            + Add Location
          </button>
        </div>
      </div>

      {/* Queries Section - Simplified: Only show target roles */}
      <div className="job-config-section">
        <h4 className="job-config-section-title">Search Queries</h4>
        
        {profileData?.profile?.target_roles && Object.keys(profileData.profile.target_roles).length > 0 ? (
          <div className="queries-list-container">
            <div className="queries-list">
              {Object.entries(profileData.profile.target_roles).map(([roleKey, role]) => {
                const roleData = role as { name?: string }
                const name = roleData.name || roleKey
                return (
                  <div key={roleKey} className="query-item">
                    <div className="query-item-content">
                      <span className="query-text">{name}</span>
                    </div>
                  </div>
                )
              })}
            </div>
          </div>
        ) : (
          <div className="queries-empty-state">
            <div className="queries-empty-state-text">
              No Target Roles configured. Configure Target Roles in the Profile section.
            </div>
          </div>
        )}
      </div>

      {onSave && (
        <div className="job-config-actions">
          <button
            type="button"
            onClick={handleSave}
            disabled={isSaving || !defaults.location.trim()}
            className="save-config-button"
          >
            <span className="save-config-button-icon">{isSaving ? '⏳' : '💾'}</span>
            <span>{isSaving ? 'Saving...' : 'Save Configuration'}</span>
          </button>
        </div>
      )}
    </div>
  )
}
