import { useState, useEffect, useMemo } from 'react'
import { Profile } from '../api/client'
import PersonalInfoForm from './sections/PersonalInfoForm'
import WorkAuthorizationForm from './sections/WorkAuthorizationForm'
import AvailabilityForm from './sections/AvailabilityForm'
import CompensationForm from './sections/CompensationForm'
import ExperienceForm from './sections/ExperienceForm'
import SkillsBoundaryForm from './sections/SkillsBoundaryForm'
import ResumeFactsForm from './sections/ResumeFactsForm'
import EEOVoluntaryForm from './sections/EEOVoluntaryForm'
import JobConfigForm from './sections/JobConfigForm'
import CoverLetterForm from './sections/CoverLetterForm'
import './ProfileForm.css'

interface ProfileFormProps {
  profile: Profile
  activeSection: string
  onSave: (profile: Profile) => void
  onSaveJobConfig?: (config: any) => void
  isSaving: boolean
}

// Deep comparison function to detect changes
function deepEqual(obj1: any, obj2: any): boolean {
  if (obj1 === obj2) return true
  
  if (obj1 == null || obj2 == null) return false
  
  if (typeof obj1 !== 'object' || typeof obj2 !== 'object') return false
  
  const keys1 = Object.keys(obj1)
  const keys2 = Object.keys(obj2)
  
  if (keys1.length !== keys2.length) return false
  
  for (const key of keys1) {
    if (!keys2.includes(key)) return false
    
    // Handle arrays
    if (Array.isArray(obj1[key]) && Array.isArray(obj2[key])) {
      if (obj1[key].length !== obj2[key].length) return false
      for (let i = 0; i < obj1[key].length; i++) {
        if (!deepEqual(obj1[key][i], obj2[key][i])) return false
      }
    } else if (typeof obj1[key] === 'object' && typeof obj2[key] === 'object' && 
               obj1[key] !== null && obj2[key] !== null &&
               !Array.isArray(obj1[key]) && !Array.isArray(obj2[key])) {
      if (!deepEqual(obj1[key], obj2[key])) return false
    } else if (obj1[key] !== obj2[key]) {
      return false
    }
  }
  
  return true
}

export default function ProfileForm({ profile, activeSection, onSave, onSaveJobConfig, isSaving }: ProfileFormProps) {
  const [localProfile, setLocalProfile] = useState<Profile>(profile)
  const [originalProfile, setOriginalProfile] = useState<Profile>(profile)

  useEffect(() => {
    setLocalProfile(profile)
    setOriginalProfile(profile)
  }, [profile])

  // Detect if there are any changes
  const hasChanges = useMemo(() => {
    return !deepEqual(localProfile, originalProfile)
  }, [localProfile, originalProfile])

  const updateSection = (sectionName: string, sectionData: any) => {
    setLocalProfile((prev) => ({
      ...prev,
      [sectionName]: sectionData,
    }))
  }

  const handleSave = () => {
    onSave(localProfile)
    // Update original profile after save to reset change detection
    setOriginalProfile(localProfile)
  }

  const renderSection = () => {
    switch (activeSection) {
      case 'personal':
        return (
          <PersonalInfoForm
            data={localProfile.personal || {}}
            onChange={(data) => updateSection('personal', data)}
          />
        )
      case 'work_authorization':
        return (
          <WorkAuthorizationForm
            data={localProfile.work_authorization || {}}
            onChange={(data) => updateSection('work_authorization', data)}
          />
        )
      case 'availability':
        return (
          <AvailabilityForm
            data={localProfile.availability || {}}
            onChange={(data) => updateSection('availability', data)}
          />
        )
      case 'compensation':
        return (
          <CompensationForm
            data={localProfile.compensation || {}}
            onChange={(data) => updateSection('compensation', data)}
          />
        )
      case 'experience':
        return (
          <ExperienceForm
            data={localProfile.experience || {}}
            onChange={(data) => updateSection('experience', data)}
          />
        )
      case 'skills_boundary':
        return (
          <SkillsBoundaryForm
            data={localProfile.skills_boundary || {}}
            onChange={(data) => updateSection('skills_boundary', data)}
          />
        )
      case 'resume_facts':
        return (
          <ResumeFactsForm
            data={localProfile.resume_facts || {}}
            onChange={(data) => updateSection('resume_facts', data)}
            experience={localProfile.experience}
            profile={localProfile}
          />
        )
      case 'job_config':
        return (
          <JobConfigForm
            onSave={onSaveJobConfig}
            isSaving={isSaving}
          />
        )
      case 'cover_letter':
        return (
          <CoverLetterForm
            onSave={onSaveJobConfig}
            isSaving={isSaving}
          />
        )
      case 'eeo_voluntary':
        return (
          <EEOVoluntaryForm
            data={localProfile.eeo_voluntary || {}}
            onChange={(data) => updateSection('eeo_voluntary', data)}
          />
        )
      default:
        return <div>Unknown section</div>
    }
  }

  return (
    <div className="profile-form">
      {activeSection !== 'job_config' && activeSection !== 'cover_letter' && (
        <div className="form-header">
          {hasChanges && (
            <span className="changes-indicator">
              • Unsaved changes
            </span>
          )}
          <button
            type="button"
            onClick={handleSave}
            disabled={isSaving || !hasChanges}
            className="save-button"
          >
            {isSaving ? 'Saving...' : 'Save Profile'}
          </button>
        </div>
      )}
      <div className="form-content">{renderSection()}</div>
    </div>
  )
}
