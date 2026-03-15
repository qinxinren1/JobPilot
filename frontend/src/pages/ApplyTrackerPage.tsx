import { useState, useEffect, useRef } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import ReactMarkdown from 'react-markdown'
import { 
  jobsApi, Job, initApi, profileApi, searchConfigApi, pipelineApi, applyApi 
} from '../api/client'
import './ApplyTrackerPage.css'

export default function ApplyTrackerPage() {
  const queryClient = useQueryClient()
  const [activeView, setActiveView] = useState('all')
  const [selectedJob, setSelectedJob] = useState<Job | null>(null)
  const [minScore, setMinScore] = useState<number | undefined>(undefined)
  const [searchQuery, setSearchQuery] = useState('')
  const [isSearching, setIsSearching] = useState(false)
  const [linkedinUrl, setLinkedinUrl] = useState('')
  const [isAddingLinkedIn, setIsAddingLinkedIn] = useState(false)
  const [isApplying, setIsApplying] = useState(false)
  const applyConfig = {
    limit: 10,
    workers: 1,
    min_score: 7,
    model: 'sonnet',
    headless: false,
    dry_run: false,
    continuous: false,
  }
  const applyIntervalRef = useRef<NodeJS.Timeout | null>(null)

  // Query for all jobs (for global stats, not affected by view)
  const { data: allJobsData } = useQuery({
    queryKey: ['jobs', 'all'],
    queryFn: () => jobsApi.getJobs({ limit: 200 }),
  })

  const { data, isLoading, error } = useQuery({
    queryKey: ['jobs', activeView, minScore, searchQuery],
    queryFn: () => {
      const params: {
        limit: number
        stage?: string
        min_score?: number
        status?: string
        search?: string
      } = { limit: 200 }
      
      // Handle status-based views (applied, failed) separately
      if (activeView === 'applied' || activeView === 'failed') {
        params.status = activeView === 'applied' ? 'applied' : activeView
        // Don't set stage for status-based filters
      } else if (activeView !== 'all') {
        // For stage-based views (discovered, enriched, scored, tailored)
        params.stage = activeView
      }
      
      if (minScore !== undefined) {
        params.min_score = minScore
      }
      
      if (searchQuery.trim()) {
        params.search = searchQuery.trim()
      }
      
      return jobsApi.getJobs(params)
    },
  })

  const { data: initStatus } = useQuery({
    queryKey: ['initStatus'],
    queryFn: initApi.getStatus,
  })

  const pipelineMutation = useMutation({
    mutationFn: pipelineApi.runPipeline,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['jobs'] })
      setIsSearching(false)
      alert('Job search started! Jobs will appear here as they are discovered.')
    },
    onError: (error: Error) => {
      setIsSearching(false)
      alert(`Failed to start job search: ${error.message}`)
    },
  })

  const deleteJobMutation = useMutation({
    mutationFn: jobsApi.deleteJob,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['jobs'] })
      setSelectedJob(null)
      alert('Job deleted successfully')
    },
    onError: (error: Error) => {
      alert(`Failed to delete job: ${error.message}`)
    },
  })

  const applyJobMutation = useMutation({
    mutationFn: async (jobUrl: string) => {
      return applyApi.startApply({
        ...applyConfig,
        limit: 1,
        url: jobUrl,
      })
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['jobs'] })
      alert('Application started! The system will process this job application.')
    },
    onError: (error: Error) => {
      alert(`Failed to start application: ${error.message}`)
    },
  })

  const handleDeleteJob = (job: Job, e: React.MouseEvent) => {
    e.stopPropagation() // Prevent selecting the job when clicking delete
    
    if (window.confirm(`Are you sure you want to delete "${job.title || 'this job'}"? This action cannot be undone.`)) {
      deleteJobMutation.mutate(job.url, {
        onSuccess: () => {
          if (selectedJob?.url === job.url) {
            setSelectedJob(null)
          }
        }
      })
    }
  }

  const handleApplyJob = (job: Job, e: React.MouseEvent) => {
    e.stopPropagation() // Prevent selecting the job when clicking apply
    
    if (!job.tailored_resume_path) {
      alert('This job does not have a tailored resume yet. Please run tailoring first.')
      return
    }

    if (job.apply_status === 'applied') {
      alert('This job has already been applied to.')
      return
    }

    if (job.apply_status === 'in_progress') {
      alert('This job is currently being processed.')
      return
    }

    if (window.confirm(`Apply to "${job.title || 'this job'}" at ${job.company || job.site || 'this company'}?`)) {
      applyJobMutation.mutate(job.url)
    }
  }

  const handleAddLinkedInJob = async () => {
    if (!linkedinUrl.trim()) {
      alert('Please enter a LinkedIn job URL')
      return
    }

    setIsAddingLinkedIn(true)
    try {
      const result = await jobsApi.addLinkedInJob(linkedinUrl.trim())
      queryClient.invalidateQueries({ queryKey: ['jobs'] })
      setLinkedinUrl('')
      alert(result.message)
    } catch (error) {
      const errorMessage = error instanceof Error 
        ? error.message 
        : (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail || 'Unknown error'
      alert(`Failed to add LinkedIn job: ${errorMessage}`)
    } finally {
      setIsAddingLinkedIn(false)
    }
  }

  const handleSearchJobs = async () => {
    if (!initStatus) {
      alert('Please wait while we check your setup...')
      return
    }

    // Check if initialization is complete
    if (!initStatus.profile || !initStatus.search_config) {
      // Try to initialize with current data
      try {
        setIsSearching(true)
        
        // Get current profile and search config
        const profileData = await profileApi.getProfile()
        const searchConfigData = await searchConfigApi.getSearchConfig()

        if (!profileData.profile || Object.keys(profileData.profile).length === 0) {
          alert('Please complete your profile first in the Profile Management tab.')
          setIsSearching(false)
          return
        }

        if (!searchConfigData.config) {
          alert('Please configure your search settings first in the Search Config tab.')
          setIsSearching(false)
          return
        }

        // Initialize
        await initApi.initialize(null, profileData.profile, searchConfigData.config)
        
        // Refresh status
        queryClient.invalidateQueries({ queryKey: ['initStatus'] })
      } catch (error) {
        setIsSearching(false)
        const errorMessage = error instanceof Error ? error.message : 'Unknown error'
        alert(`Initialization failed: ${errorMessage}. Please complete your profile and search config first.`)
        return
      }
    }

    // Start pipeline
    setIsSearching(true)
    pipelineMutation.mutate({
      stages: ['discover', 'enrich'],
      workers: 1,
      stream: false,
    })
  }

  const handleStartApply = async () => {
    // Check if there are jobs ready to apply
    const readyJobs = jobs.filter(j => 
      j.tailored_resume_path && 
      j.fit_score !== null && 
      j.fit_score >= applyConfig.min_score &&
      j.apply_status !== 'applied' &&
      j.apply_status !== 'in_progress'
    )

    if (readyJobs.length === 0) {
      alert(`No jobs ready to apply. Please ensure:\n1. You have run scoring and resume tailoring\n2. There are jobs with fit_score >= ${applyConfig.min_score}`)
      return
    }

    if (!window.confirm(`Ready to start auto-apply for ${readyJobs.length} job(s).\n\nConfiguration:\n- Min Score: ${applyConfig.min_score}\n- Max Applications: ${applyConfig.limit}\n- Workers: ${applyConfig.workers}\n- Model: ${applyConfig.model}\n\nContinue?`)) {
      return
    }

    try {
      setIsApplying(true)
      await applyApi.startApply(applyConfig)
      alert('Auto-apply started! The system will begin processing eligible jobs.\n\nNote: The application process may take some time. Check logs for detailed progress.')
      
      // Clear any existing interval
      if (applyIntervalRef.current) {
        clearInterval(applyIntervalRef.current)
      }
      
      // Refresh jobs list periodically
      applyIntervalRef.current = setInterval(() => {
        queryClient.invalidateQueries({ queryKey: ['jobs'] })
      }, 10000) // Refresh every 10 seconds
      
      // Stop refreshing after 5 minutes
      setTimeout(() => {
        if (applyIntervalRef.current) {
          clearInterval(applyIntervalRef.current)
          applyIntervalRef.current = null
        }
        setIsApplying(false)
      }, 300000) // 5 minutes
      
    } catch (error) {
      setIsApplying(false)
      if (applyIntervalRef.current) {
        clearInterval(applyIntervalRef.current)
        applyIntervalRef.current = null
      }
      const errorMessage = error instanceof Error ? error.message : 'Unknown error'
      alert(`Failed to start auto-apply: ${errorMessage}`)
    }
  }

  // Cleanup interval on unmount
  useEffect(() => {
    return () => {
      if (applyIntervalRef.current) {
        clearInterval(applyIntervalRef.current)
      }
    }
  }, [])

  const jobs = data?.jobs || []
  
  // Use all jobs data for global stats (not affected by current view)
  const allJobs = allJobsData?.jobs || []
  const allJobsCount = allJobsData?.count || 0

  // Calculate counts from all jobs (for sidebar view counts)
  const getViewCount = (viewId: string) => {
    if (viewId === 'all') return allJobsCount
    if (viewId === 'discovered') return allJobs.filter(j => !j.full_description).length
    if (viewId === 'enriched') return allJobs.filter(j => j.full_description && !j.fit_score).length
    if (viewId === 'scored') return allJobs.filter(j => j.fit_score !== null).length
    if (viewId === 'tailored') return allJobs.filter(j => j.tailored_resume_path).length
    if (viewId === 'applied') return allJobs.filter(j => j.apply_status === 'applied').length
    if (viewId === 'failed') return allJobs.filter(j => j.apply_status && j.apply_status !== 'applied' && j.apply_status !== null).length
    return 0
  }

  const views = [
    { id: 'all', label: 'All Jobs', icon: '' },
    { id: 'discovered', label: 'Discovered', icon: '' },
    { id: 'enriched', label: 'Enriched', icon: '' },
    { id: 'scored', label: 'Scored', icon: '' },
    { id: 'tailored', label: 'Tailored', icon: '' },
    { id: 'applied', label: 'Applied', icon: '' },
    { id: 'failed', label: 'Failed', icon: '' },
  ]

  const getStatusBadge = (job: Job) => {
    if (job.apply_status === 'applied') {
      return <span className="status-badge status-applied">Applied</span>
    }
    if (job.apply_status && job.apply_status !== 'applied') {
      return <span className="status-badge status-failed">{job.apply_status}</span>
    }
    if (job.tailored_resume_path) {
      return <span className="status-badge status-ready">Ready to Apply</span>
    }
    if (job.fit_score !== null) {
      return <span className="status-badge status-scored">Scored ({job.fit_score}/10)</span>
    }
    if (job.full_description) {
      return <span className="status-badge status-enriched">Enriched</span>
    }
    return <span className="status-badge status-discovered">Discovered</span>
  }

  const formatDate = (dateStr: string | null) => {
    if (!dateStr) return 'N/A'
    try {
      const date = new Date(dateStr)
      return date.toLocaleDateString() + ' ' + date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    } catch {
      return dateStr
    }
  }

  return (
    <div className="apply-tracker-page">
      <div className="tracker-container">
        <div className="tracker-sidebar">
          <div className="tracker-filters">
            <h3>Filters</h3>
            <div className="filter-group">
              <label>Min Fit Score</label>
              <input
                type="number"
                min="0"
                max="10"
                value={minScore || ''}
                onChange={(e) => setMinScore(e.target.value ? parseInt(e.target.value) : undefined)}
                placeholder="Any"
                className="score-input"
              />
            </div>
          </div>

          <nav className="tracker-views">
            <h3>Views</h3>
            {views.map((view) => {
              const viewCount = getViewCount(view.id)
              return (
                <button
                  key={view.id}
                  className={`view-button ${activeView === view.id ? 'active' : ''}`}
                  onClick={() => setActiveView(view.id)}
                >
                  {view.icon && <span className="view-icon">{view.icon}</span>}
                  <span className="view-label">{view.label}</span>
                  {viewCount > 0 && <span className="view-count">{viewCount}</span>}
                </button>
              )
            })}
          </nav>
        </div>

        <div className="tracker-content">
          <div className="tracker-header">
            <h2>Apply Tracker</h2>
            <div className="tracker-actions">
              <div className="search-container">
                <input
                  type="text"
                  placeholder="Search jobs by title or company..."
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  className="search-input"
                />
                {searchQuery && (
                  <button
                    onClick={() => setSearchQuery('')}
                    className="search-clear-button"
                    title="Clear search"
                  >
                    ✕
                  </button>
                )}
              </div>
              <div className="linkedin-add-container">
                <input
                  type="text"
                  placeholder="Paste LinkedIn job URL..."
                  value={linkedinUrl}
                  onChange={(e) => setLinkedinUrl(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' && !isAddingLinkedIn) {
                      handleAddLinkedInJob()
                    }
                  }}
                  className="linkedin-url-input"
                  disabled={isAddingLinkedIn}
                />
                <button
                  onClick={handleAddLinkedInJob}
                  disabled={isAddingLinkedIn || !linkedinUrl.trim()}
                  className="add-linkedin-button"
                >
                  {isAddingLinkedIn ? 'Adding...' : '➕ Add'}
                </button>
              </div>
              <button
                onClick={handleSearchJobs}
                disabled={isSearching || pipelineMutation.isPending}
                className="search-jobs-button"
              >
                {isSearching || pipelineMutation.isPending ? 'Searching...' : '🔍 Search Jobs'}
              </button>
              <button
                onClick={handleStartApply}
                disabled={isApplying}
                className="auto-apply-button"
                title={`Auto-apply (Min Score: ${applyConfig.min_score}, Max: ${applyConfig.limit} jobs)`}
              >
                {isApplying ? 'Applying...' : '🚀 Auto-Apply'}
              </button>
            </div>
            <div className="tracker-stats">
              <span className="stat-item">
                <strong>{allJobsCount}</strong> {allJobsCount === 1 ? 'job' : 'jobs'}
              </span>
              <span className="stat-item">
                <strong>{allJobs.filter(j => j.fit_score !== null).length}</strong> scored
              </span>
              <span className="stat-item">
                <strong>{allJobs.filter(j => j.apply_status === 'applied').length}</strong> applied
              </span>
            </div>
          </div>

          <div className="tracker-main-layout">
            <div className="jobs-list-container">
              {isLoading && (
                <div className="loading-state">
                  <div className="spinner"></div>
                  <p>Loading jobs...</p>
                </div>
              )}

              {error && (
                <div className="error-state">
                  <p>Error loading jobs: {error instanceof Error ? error.message : 'Unknown error'}</p>
                </div>
              )}

              {!isLoading && !error && (
                <>
                  {jobs.length === 0 ? (
                    <div className="empty-state">
                      <p>No jobs found. Start by running the discovery stage to find jobs.</p>
                    </div>
                  ) : (
                    <div className="jobs-list">
                      {jobs.map((job) => (
                        <div
                          key={job.url}
                          className={`job-list-item ${selectedJob?.url === job.url ? 'selected' : ''}`}
                          onClick={() => setSelectedJob(job)}
                        >
                          <div className="job-list-header">
                            <h3 className="job-list-title">{job.title || 'Untitled Job'}</h3>
                            <div className="job-list-actions">
                              {getStatusBadge(job)}
                              {job.tailored_resume_path && 
                               job.apply_status !== 'applied' && 
                               job.apply_status !== 'in_progress' && (
                                <button
                                  className="job-list-apply-button"
                                  onClick={(e) => handleApplyJob(job, e)}
                                  disabled={applyJobMutation.isPending}
                                  title="Apply to this job"
                                >
                                  {applyJobMutation.isPending ? '⏳' : 'Apply'}
                                </button>
                              )}
                            </div>
                          </div>
                          <button
                            className="job-list-delete-button"
                            onClick={(e) => handleDeleteJob(job, e)}
                            disabled={deleteJobMutation.isPending}
                            title="Delete job"
                          >
                            ❌
                          </button>
                          
                          <div className="job-list-meta">
                            {job.company && (
                              <span className="job-meta-item">
                                <span className="meta-icon">🏢</span>
                                {job.company}
                              </span>
                            )}
                            {job.location && (
                              <span className="job-meta-item">
                                <span className="meta-icon">📍</span>
                                {job.location}
                              </span>
                            )}
                            {job.site && (
                              <span className="job-meta-item">
                                <span className="meta-icon">🌐</span>
                                {job.site}
                              </span>
                            )}
                            {job.fit_score !== null && (
                              <span className="job-meta-item">
                                <span className="meta-icon">⭐</span>
                                {job.fit_score}/10
                              </span>
                            )}
                            {job.resume_score !== null && (
                              <span className="job-meta-item">
                                <span className="meta-icon">📄</span>
                                {job.resume_score}/10
                              </span>
                            )}
                          </div>

                          {job.description && (
                            <div className="job-list-description">
                              {job.description.substring(0, 120)}
                              {job.description.length > 120 ? '...' : ''}
                            </div>
                          )}

                          {job.discovered_at && (
                            <div className="job-list-date">
                              {formatDate(job.discovered_at)}
                            </div>
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                </>
              )}
            </div>

            {selectedJob ? (
              <div className="job-detail-panel">
                <div className="job-detail-header">
                  <button className="close-button" onClick={() => setSelectedJob(null)}>×</button>
                </div>
                
                <div className="job-detail-content">
                  <div className="detail-header-section">
                    <div className="detail-header-top">
                      <h2 className="detail-title">{selectedJob.title || 'Untitled Job'}</h2>
                      <div className="detail-meta-top">
                        {selectedJob.company && (
                          <span className="meta-top-item">
                            <span className="meta-top-icon">🏢</span>
                            <span className="meta-top-label">Company:</span>
                            <span className="meta-top-value">{selectedJob.company}</span>
                          </span>
                        )}
                        {selectedJob.location && (
                          <span className="meta-top-item">
                            <span className="meta-top-icon">📍</span>
                            <span className="meta-top-label">Location:</span>
                            <span className="meta-top-value">{selectedJob.location}</span>
                          </span>
                        )}
                        {selectedJob.site && (
                          <span className="meta-top-item">
                            <span className="meta-top-icon">🌐</span>
                            <span className="meta-top-label">Source:</span>
                            <span className="meta-top-value">{selectedJob.site}</span>
                          </span>
                        )}
                        {selectedJob.discovered_at && (
                          <span className="timeline-top-item">Discovered: {formatDate(selectedJob.discovered_at)}</span>
                        )}
                        {selectedJob.detail_scraped_at && (
                          <span className="timeline-top-item">Enriched: {formatDate(selectedJob.detail_scraped_at)}</span>
                        )}
                        {selectedJob.scored_at && (
                          <span className="timeline-top-item">Scored: {formatDate(selectedJob.scored_at)}</span>
                        )}
                        {selectedJob.tailored_at && (
                          <span className="timeline-top-item">Tailored: {formatDate(selectedJob.tailored_at)}</span>
                        )}
                        {selectedJob.applied_at && (
                          <span className="timeline-top-item">Applied: {formatDate(selectedJob.applied_at)}</span>
                        )}
                      </div>
                    </div>
                    <div className="detail-badge-container">
                      {getStatusBadge(selectedJob)}
                    </div>
                  </div>

                  <div className="detail-section">
                    <div className="detail-info-grid">
                      {selectedJob.salary && (
                        <div className="detail-info-item">
                          <div className="detail-info-label">💰 Salary</div>
                          <div className="detail-info-value">{selectedJob.salary}</div>
                        </div>
                      )}
                      {selectedJob.fit_score !== null && (
                        <div className="detail-info-item">
                          <div className="detail-info-label">⭐ Fit Score</div>
                          <div className="detail-info-value">{selectedJob.fit_score}/10</div>
                        </div>
                      )}
                      {selectedJob.resume_score !== null && (
                        <div className="detail-info-item">
                          <div className="detail-info-label">📄 Resume Score</div>
                          <div className="detail-info-value">{selectedJob.resume_score}/10</div>
                        </div>
                      )}
                    </div>
                  </div>

                  {selectedJob.score_reasoning && (
                    <div className="detail-section">
                      <h5 className="detail-section-title">Score Reasoning</h5>
                      <div className="detail-card">
                        <div className="markdown-content">
                          <ReactMarkdown>{selectedJob.score_reasoning}</ReactMarkdown>
                        </div>
                      </div>
                    </div>
                  )}

                  {selectedJob.full_description && (
                    <div className="detail-section">
                      <h5 className="detail-section-title">Full Description</h5>
                      <div className="detail-card description-full">
                        <div className="markdown-content">
                          <ReactMarkdown>{selectedJob.full_description}</ReactMarkdown>
                        </div>
                      </div>
                    </div>
                  )}

                  {selectedJob.description && !selectedJob.full_description && (
                    <div className="detail-section">
                      <h5 className="detail-section-title">Description</h5>
                      <div className="detail-card">
                        <div className="markdown-content">
                          <ReactMarkdown>{selectedJob.description}</ReactMarkdown>
                        </div>
                      </div>
                    </div>
                  )}


                  {selectedJob.apply_error && (
                    <div className="detail-section">
                      <h5 className="detail-section-title">Application Error</h5>
                      <div className="detail-card error-card">
                        <p className="detail-text error-text">{selectedJob.apply_error}</p>
                      </div>
                    </div>
                  )}

                  <div className="detail-section">
                    <h5 className="detail-section-title">Links</h5>
                    <div className="detail-links-compact">
                      {selectedJob.url && (
                        <a href={selectedJob.url} target="_blank" rel="noopener noreferrer" className="detail-link-compact">
                          <span className="link-icon">🔗</span>
                          <span>View Job Posting</span>
                          <span className="link-arrow">→</span>
                        </a>
                      )}
                      {selectedJob.application_url && (
                        <a href={selectedJob.application_url} target="_blank" rel="noopener noreferrer" className="detail-link-compact">
                          <span className="link-icon">📝</span>
                          <span>Application URL</span>
                          <span className="link-arrow">→</span>
                        </a>
                      )}
                    </div>
                  </div>
                </div>
              </div>
            ) : (
              <div className="job-detail-placeholder">
                <div className="placeholder-content">
                  <div className="placeholder-icon">👈</div>
                  <p className="placeholder-text">Select a job to view details</p>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
