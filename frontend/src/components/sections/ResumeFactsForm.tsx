import { useState, useEffect } from 'react'
import { isAxiosError } from 'axios'
import {
  ResumeFacts,
  TargetRole,
  Experience,
  Profile,
  resumesApi,
  profileApi,
  WorkExperience,
  ProjectExperience,
} from '../../api/client'
import { apiClient } from '../../api/client'
import { useQueryClient } from '@tanstack/react-query'
import './SectionForm.css'
import './ResumeFactsForm.css'

function apiErrorMessage(err: unknown): string {
  if (isAxiosError(err)) {
    const data = err.response?.data as { detail?: string } | undefined
    return data?.detail ?? err.message
  }
  return err instanceof Error ? err.message : String(err)
}

type WorkExperienceRow = WorkExperience & { _id?: string }
type ProjectExperienceRow = ProjectExperience & { _id?: string }

interface ResumeFactsFormProps {
  data: Partial<ResumeFacts>
  onChange: (data: Partial<ResumeFacts>) => void
  experience?: Partial<Experience>
  profile?: Profile
}

export default function ResumeFactsForm({ data, onChange: _onChange, experience, profile }: ResumeFactsFormProps) {
  const [, setFormData] = useState<Partial<ResumeFacts>>(data)
  const [previewHtml, setPreviewHtml] = useState<string>('')
  const [previewLoadingRoleKey, setPreviewLoadingRoleKey] = useState<string | null>(null)
  const [savingTemplateRoleKey, setSavingTemplateRoleKey] = useState<string | null>(null)
  const [previewingRoleKey, setPreviewingRoleKey] = useState<string | null>(null)
  const [expandedRoles, setExpandedRoles] = useState<Record<string, boolean>>({})
  const queryClient = useQueryClient()
  void _onChange
  
  // Get target_roles from profile (unified category system)
  const targetRoles = profile?.target_roles || {}
  const targetRolesList = Object.entries(targetRoles)

  useEffect(() => {
    setFormData(data)
  }, [data])

  const slugifyRoleKey = (name: string) => {
    const base = name
      .trim()
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, '_')
      .replace(/^_+|_+$/g, '')
    return base || 'role'
  }

  const generateUniqueRoleKey = (baseName: string) => {
    const base = slugifyRoleKey(baseName)
    let key = base
    let i = 2
    while (Object.prototype.hasOwnProperty.call(targetRoles, key)) {
      key = `${base}_${i}`
      i += 1
    }
    return key
  }

  // Update target role
  const updateTargetRole = async (roleKey: string, updates: Partial<TargetRole>) => {
    if (!profile) return
    
    const updatedTargetRoles = {
      ...targetRoles,
      [roleKey]: {
        ...targetRoles[roleKey],
        ...updates
      }
    }
    
    try {
      await profileApi.updateSection('target_roles', updatedTargetRoles)
      queryClient.invalidateQueries({ queryKey: ['profile'] })
    } catch (error: unknown) {
      console.error('Failed to update target role:', error)
      alert('Failed to update target role: ' + apiErrorMessage(error))
    }
  }

  const addTargetRole = async () => {
    if (!profile) {
      alert('Profile not loaded yet. Please try again in a moment.')
      return
    }

    const proposedName = window.prompt('New target role name (e.g., "Frontend", "Data", "ML")', 'New Role')
    if (proposedName === null) return
    const name = proposedName.trim()
    if (!name) {
      alert('Role name cannot be empty.')
      return
    }

    const roleKey = generateUniqueRoleKey(name)
    const updatedTargetRoles = {
      ...targetRoles,
      [roleKey]: {
        name,
        base_resume_path: '',
        selected_work_experiences: [],
        selected_projects: [],
      },
    }

    try {
      await profileApi.updateSection('target_roles', updatedTargetRoles)
      setExpandedRoles(prev => ({ ...prev, [roleKey]: true }))
      queryClient.invalidateQueries({ queryKey: ['profile'] })
    } catch (error: unknown) {
      console.error('Failed to add target role:', error)
      alert('Failed to add target role: ' + apiErrorMessage(error))
    }
  }

  const removeTargetRole = async (roleKey: string) => {
    if (!profile) return
    const roleName = targetRoles[roleKey]?.name || roleKey
    const ok = window.confirm(`Delete target role "${roleName}"? This cannot be undone.`)
    if (!ok) return

    const updatedTargetRoles = { ...targetRoles }
    delete updatedTargetRoles[roleKey]

    try {
      await profileApi.updateSection('target_roles', updatedTargetRoles)
      setExpandedRoles(prev => {
        const next = { ...prev }
        delete next[roleKey]
        return next
      })
      setPreviewingRoleKey(prev => (prev === roleKey ? null : prev))
      queryClient.invalidateQueries({ queryKey: ['profile'] })
    } catch (error: unknown) {
      console.error('Failed to remove target role:', error)
      alert('Failed to remove target role: ' + apiErrorMessage(error))
    }
  }

  // Toggle experience selection in target role
  const toggleWorkExperience = (roleKey: string, expId: string) => {
    const role = targetRoles[roleKey]
    if (!role) return
    
    const selected = role.selected_work_experiences || []
    const newSelected = selected.includes(expId)
      ? selected.filter(id => id !== expId)
      : [...selected, expId]
    
    updateTargetRole(roleKey, { selected_work_experiences: newSelected })
  }

  const toggleProject = (roleKey: string, projId: string) => {
    const role = targetRoles[roleKey]
    if (!role) return
    
    const selected = role.selected_projects || []
    const newSelected = selected.includes(projId)
      ? selected.filter(id => id !== projId)
      : [...selected, projId]
    
    updateTargetRole(roleKey, { selected_projects: newSelected })
  }

  // Build filtered profile for a target role
  const buildFilteredProfile = (role: TargetRole) => {
    const workExperiences = (experience?.work_experiences || []).filter((exp: WorkExperienceRow, idx: number) => {
      const expId = exp._id || idx.toString()
      return role.selected_work_experiences?.includes(expId)
    })

    const projects = (experience?.projects || []).filter((proj: ProjectExperienceRow, idx: number) => {
      const projId = proj._id || idx.toString()
      return role.selected_projects?.includes(projId)
    })

    // Education and awards are always included
    const education = experience?.education || []
    const awards = experience?.awards || []

    return {
      ...profile,
      experience: {
        ...experience,
        work_experiences: workExperiences,
        projects: projects,
        education: education,
        awards: awards,
        target_role: role.name
      }
    }
  }

  // Generate preview
  const generatePreview = async (roleKey: string) => {
    if (savingTemplateRoleKey !== null) return
    const role = targetRoles[roleKey]
    if (!role || !role.name) {
      alert('Please configure the target role name first')
      return
    }

    setPreviewLoadingRoleKey(roleKey)
    try {
      const previewProfile = buildFilteredProfile(role)

      const response = await apiClient.post('/api/resume/preview', {
        profile: previewProfile,
        job_position: role.name
      })

      setPreviewHtml(response.data.html)
      setPreviewingRoleKey(roleKey)
    } catch (error: unknown) {
      console.error('Failed to generate preview:', error)
      alert('Failed to generate preview: ' + apiErrorMessage(error))
    } finally {
      setPreviewLoadingRoleKey(null)
    }
  }

  // Generate and save as template
  const generateAndSaveTemplate = async (roleKey: string) => {
    if (previewLoadingRoleKey !== null || savingTemplateRoleKey !== null) return
    const role = targetRoles[roleKey]
    if (!role || !role.name) {
      alert('Please configure the target role name first')
      return
    }

    setSavingTemplateRoleKey(roleKey)
    try {
      const filteredProfile = buildFilteredProfile(role)

      await resumesApi.generateResumeFromProfile(
        role.name,
        role.name,
        '',
        false,
        filteredProfile as Partial<Profile>,
        roleKey // role_category
      )

      alert(`Resume template "${role.name}" saved successfully!`)
      
      if (previewingRoleKey === roleKey) {
        await generatePreview(roleKey)
      }
    } catch (error: unknown) {
      console.error('Failed to generate template:', error)
      alert('Failed to generate template: ' + apiErrorMessage(error))
    } finally {
      setSavingTemplateRoleKey(null)
    }
  }

  const workExperiences = experience?.work_experiences || []
  const projects = experience?.projects || []

  const toggleRole = (roleKey: string) => {
    setExpandedRoles(prev => ({
      ...prev,
      [roleKey]: !prev[roleKey]
    }))
  }

  const isRoleExpanded = (roleKey: string) => {
    return expandedRoles[roleKey] !== false
  }

  return (
    <div className="section-form resume-facts-container">
      <div className="resume-facts-header">
        <h3>Target Roles (Resume Organization)</h3>
        <p className="section-description">
          Organize your experiences into target roles and preview customized resumes. Select work experiences and projects for each target role.
          <br />
          <strong>Note:</strong> Target roles are also used for job search queries and resume template matching.
        </p>
      </div>

      <div className="resume-facts-layout">
        {/* Left: Target Roles section */}
        <div className="resume-categories-section">
          <div className="section-header">
            <h4>Roles</h4>
            <button
              type="button"
              className="add-category-button"
              onClick={addTargetRole}
            >
              + Add role
            </button>
          </div>
          {targetRolesList.length === 0 ? (
            <div className="empty-state">
              <p>No target roles configured yet.</p>
              <p>Configure target roles in the Profile section to organize your resume content.</p>
            </div>
          ) : (
            targetRolesList.map(([roleKey, role]) => (
              <div key={roleKey} className="category-card">
                <div className="category-header">
                  <button
                    type="button"
                    className="category-expand-button"
                    onClick={() => toggleRole(roleKey)}
                    aria-label={isRoleExpanded(roleKey) ? 'Collapse' : 'Expand'}
                  >
                    {isRoleExpanded(roleKey) ? '▼' : '▶'}
                  </button>
                  <input
                    type="text"
                    className="category-name-input"
                    value={role.name || ''}
                    onChange={(e) => updateTargetRole(roleKey, { name: e.target.value })}
                    placeholder="Target role name"
                    onClick={() => {
                      if (!isRoleExpanded(roleKey)) {
                        toggleRole(roleKey)
                      }
                    }}
                  />
                  <div className="category-actions">
                    <button
                      type="button"
                      className="preview-button"
                      onClick={() => generatePreview(roleKey)}
                      disabled={previewLoadingRoleKey === roleKey}
                    >
                      {previewLoadingRoleKey === roleKey ? 'Generating...' : 'Preview'}
                    </button>
                    <button
                      type="button"
                      className="save-template-button"
                      onClick={() => generateAndSaveTemplate(roleKey)}
                      disabled={savingTemplateRoleKey === roleKey || !role.name}
                      title="Generate PDF and save as template"
                    >
                      {savingTemplateRoleKey === roleKey ? 'Saving...' : 'Save as Template'}
                    </button>
                  </div>
                  <button
                    type="button"
                    className="remove-category-button"
                    onClick={(e) => {
                      e.stopPropagation()
                      removeTargetRole(roleKey)
                    }}
                    title="Delete role"
                    aria-label="Delete role"
                  >
                    ×
                  </button>
                </div>

                {role.name && isRoleExpanded(roleKey) && (
                  <div className="category-content">
                    {/* Work Experiences */}
                    {workExperiences.length > 0 && (
                      <div className="experience-section">
                        <h5>Work Experiences</h5>
                        <div className="experience-cards">
                          {workExperiences.map((exp: WorkExperienceRow, idx: number) => {
                            const expId = exp._id || idx.toString()
                            const isSelected = role.selected_work_experiences?.includes(expId) || false
                            return (
                              <div
                                key={idx}
                                className={`experience-card ${isSelected ? 'selected' : ''}`}
                                onClick={() => toggleWorkExperience(roleKey, expId)}
                              >
                                <div className="card-checkbox">
                                  <input
                                    type="checkbox"
                                    checked={isSelected}
                                    onChange={() => {}}
                                    onClick={(e) => e.stopPropagation()}
                                  />
                                </div>
                                <div className="card-content">
                                  <div className="card-title">{exp.title || 'Untitled'}</div>
                                  <div className="card-subtitle">{exp.company || 'No company'}</div>
                                  <div className="card-dates">
                                    {exp.start_date} - {exp.current ? 'Present' : exp.end_date || 'N/A'}
                                  </div>
                                </div>
                              </div>
                            )
                          })}
                        </div>
                      </div>
                    )}

                    {/* Projects */}
                    {projects.length > 0 && (
                      <div className="experience-section">
                        <h5>Projects</h5>
                        <div className="experience-cards">
                          {projects.map((proj: ProjectExperienceRow, idx: number) => {
                            const projId = proj._id || idx.toString()
                            const isSelected = role.selected_projects?.includes(projId) || false
                            return (
                              <div
                                key={idx}
                                className={`experience-card ${isSelected ? 'selected' : ''}`}
                                onClick={() => toggleProject(roleKey, projId)}
                              >
                                <div className="card-checkbox">
                                  <input
                                    type="checkbox"
                                    checked={isSelected}
                                    onChange={() => {}}
                                    onClick={(e) => e.stopPropagation()}
                                  />
                                </div>
                                <div className="card-content">
                                  <div className="card-title">{proj.name || 'Untitled Project'}</div>
                                  <div className="card-subtitle">
                                    {proj.tech_stack?.join(', ') || 'No tech stack'}
                                  </div>
                                  <div className="card-dates">
                                    {proj.start_date} - {proj.current ? 'Present' : proj.end_date || 'N/A'}
                                  </div>
                                </div>
                              </div>
                            )
                          })}
                        </div>
                      </div>
                    )}
                  </div>
                )}
              </div>
            ))
          )}
        </div>

        {/* Right: Preview section */}
        <div className="resume-preview-section">
          {previewHtml && previewingRoleKey !== null ? (
            <div className="preview-content">
              <iframe
                srcDoc={previewHtml}
                className="preview-iframe"
                title="Resume Preview"
              />
            </div>
          ) : (
            <div className="preview-placeholder">
              <p>Click "Preview Resume" on any target role to see the preview here</p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
