import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  profileApi,
  searchConfigApi,
  Profile,
  SearchConfig,
  WorkExperience,
  ProjectExperience,
  EducationExperience,
} from '../api/client'
import ProfileForm from '../components/ProfileForm'
import ResumeUpload from '../components/ResumeUpload'
import './ProfilePage.css'

export default function ProfilePage() {
  const queryClient = useQueryClient()
  const [activeTab, setActiveTab] = useState('personal')
  const [showUpload, setShowUpload] = useState(false)

  const { data, isLoading, error } = useQuery({
    queryKey: ['profile'],
    queryFn: profileApi.getProfile,
    retry: 1,
    refetchOnWindowFocus: false,
  })

  const updateMutation = useMutation({
    mutationFn: profileApi.updateProfile,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['profile'] })
      // Don't show alert, just silently update
    },
    onError: (error: unknown) => {
      alert(`Failed to update profile: ${error instanceof Error ? error.message : String(error)}`)
    },
  })

  const updateJobConfigMutation = useMutation({
    mutationFn: searchConfigApi.updateSearchConfig,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['searchConfig'] })
      queryClient.invalidateQueries({ queryKey: ['initStatus'] })
      alert('Job configuration saved successfully!')
    },
    onError: (error: unknown) => {
      alert(`Failed to save job config: ${error instanceof Error ? error.message : String(error)}`)
    },
  })

  const handleSave = (profile: Profile) => {
    updateMutation.mutate(profile)
  }

  const handleSaveJobConfig = (config: SearchConfig) => {
    updateJobConfigMutation.mutate(config)
  }

  const handleDataExtracted = (mergedData: Partial<Profile>) => {
    // Backend already merged the data using LLM, so we can use it directly
    // The merged_data from backend contains all existing + new data, intelligently merged
    const uploadExtras = mergedData as Partial<Profile> & {
      work_experiences?: WorkExperience[]
      projects?: ProjectExperience[]
      education?: EducationExperience[]
    }
    const mergedProfile = {
      ...data?.profile,
      ...mergedData,
      // Ensure nested objects are properly merged
      personal: { ...data?.profile?.personal, ...mergedData.personal },
      experience: {
        ...data?.profile?.experience,
        ...mergedData.experience,
        // Use merged arrays from backend (already intelligently merged)
        work_experiences:
          mergedData.experience?.work_experiences ||
          uploadExtras.work_experiences ||
          data?.profile?.experience?.work_experiences,
        projects:
          mergedData.experience?.projects ||
          uploadExtras.projects ||
          data?.profile?.experience?.projects,
        education:
          mergedData.experience?.education ||
          uploadExtras.education ||
          data?.profile?.experience?.education,
      },
      skills_boundary: {
        ...data?.profile?.skills_boundary,
        ...mergedData.skills_boundary,
      },
    } as Profile
    
    // Update profile with merged data (backend already saved it, but we update UI)
    updateMutation.mutate(mergedProfile)
    
    // Refresh the query to show updated data from backend
    queryClient.invalidateQueries({ queryKey: ['profile'] })
  }

  if (isLoading) {
    return (
      <div className="profile-page">
        <div className="loading">Loading profile...</div>
      </div>
    )
  }

  if (error) {
    console.error('Profile loading error:', error)
    return (
      <div className="profile-page">
        <div className="error">
          <h3>Error loading profile</h3>
          <p>{error instanceof Error ? error.message : 'Unknown error'}</p>
          <p style={{ fontSize: '0.9em', marginTop: '1rem', color: '#666' }}>
            Make sure the backend server is running on http://localhost:8000
          </p>
        </div>
      </div>
    )
  }

  const profile = data?.profile || {}
  const exists = data?.exists || false

  const profileTabs = [
    { id: 'personal', label: 'Personal Info', icon: '👤' },
    { id: 'work_authorization', label: 'Work Authorization', icon: '🛂' },
    { id: 'availability', label: 'Availability', icon: '📅' },
    { id: 'compensation', label: 'Compensation', icon: '💰' },
    { id: 'experience', label: 'Experience', icon: '💼' },
    { id: 'skills_boundary', label: 'Skills', icon: '🛠️' },
    { id: 'eeo_voluntary', label: 'EEO Info', icon: '📝' },
  ]

  const resumeFactsTab = { id: 'resume_facts', label: 'Resumes', icon: '📋' }
  const jobConfigTab = { id: 'job_config', label: 'Job Config', icon: '⚙️' }
  const coverLetterTab = { id: 'cover_letter', label: 'Cover Letter', icon: '📝' }

  return (
    <div className="profile-page">
      {showUpload && (
        <ResumeUpload
          onDataExtracted={handleDataExtracted}
          onClose={() => setShowUpload(false)}
        />
      )}

      <div className="profile-container">
        <div className="profile-sidebar">
          <button
            className="upload-resume-button"
            onClick={() => setShowUpload(true)}
          >
            📄 Upload Resume
          </button>
          {!exists && (
            <div className="warning-banner">
              ⚠️ Profile not found. Upload your resume to get started.
            </div>
          )}
          <nav className="profile-tabs">
            {profileTabs.map((tab) => (
              <button
                key={tab.id}
                className={`tab-button ${activeTab === tab.id ? 'active' : ''}`}
                onClick={() => setActiveTab(tab.id)}
              >
                <span className="tab-icon">{tab.icon}</span>
                <span className="tab-label">{tab.label}</span>
              </button>
            ))}
          </nav>
          <div className="resume-separator"></div>
          <nav className="profile-tabs resume-section">
            <button
              className={`tab-button ${activeTab === resumeFactsTab.id ? 'active' : ''}`}
              onClick={() => setActiveTab(resumeFactsTab.id)}
            >
              <span className="tab-icon">{resumeFactsTab.icon}</span>
              <span className="tab-label">{resumeFactsTab.label}</span>
            </button>
            <button
              className={`tab-button ${activeTab === coverLetterTab.id ? 'active' : ''}`}
              onClick={() => setActiveTab(coverLetterTab.id)}
            >
              <span className="tab-icon">{coverLetterTab.icon}</span>
              <span className="tab-label">{coverLetterTab.label}</span>
            </button>
            <button
              className={`tab-button ${activeTab === jobConfigTab.id ? 'active' : ''}`}
              onClick={() => setActiveTab(jobConfigTab.id)}
            >
              <span className="tab-icon">{jobConfigTab.icon}</span>
              <span className="tab-label">{jobConfigTab.label}</span>
            </button>
          </nav>
        </div>

        <div className="profile-content">
          <ProfileForm
            profile={profile}
            activeSection={activeTab}
            onSave={handleSave}
            onSaveJobConfig={handleSaveJobConfig}
            isSaving={updateMutation.isPending}
          />
        </div>
      </div>
    </div>
  )
}
