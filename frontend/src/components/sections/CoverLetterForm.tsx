import { useState, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { searchConfigApi, profileApi, coverLetterTemplatesApi, SearchConfig, CoverLetterTemplate } from '../../api/client'
import './SectionForm.css'
import './JobConfigForm.css'
import './CoverLetterForm.css'

interface CoverLetterFormProps {
  onSave?: (config: SearchConfig) => void
  isSaving?: boolean
}

export default function CoverLetterForm({ onSave, isSaving }: CoverLetterFormProps) {
  const queryClient = useQueryClient()
  
  const { data: configData } = useQuery({
    queryKey: ['searchConfig'],
    queryFn: searchConfigApi.getSearchConfig,
  })

  const { data: profileData } = useQuery({
    queryKey: ['profile'],
    queryFn: profileApi.getProfile,
  })

  const { data: templatesData, isLoading: templatesLoading } = useQuery({
    queryKey: ['coverLetterTemplates'],
    queryFn: coverLetterTemplatesApi.getTemplates,
  })

  // Get target_roles from profile
  const targetRoles = profileData?.profile?.target_roles || {}
  const targetRolesList = Object.entries(targetRoles)

  // Simple enabled/disabled toggle
  const [enabled, setEnabled] = useState(true)

  // Template creation/editing state
  const [showCreateModal, setShowCreateModal] = useState(false)
  const [editingTemplate, setEditingTemplate] = useState<CoverLetterTemplate | null>(null)
  const [templateContent, setTemplateContent] = useState('')
  const [templateRoleCategory, setTemplateRoleCategory] = useState('')

  // Load existing config
  useEffect(() => {
    if (configData?.config?.cover_letter) {
      const clConfig = configData.config.cover_letter
      if (typeof clConfig === 'object' && 'enabled' in clConfig) {
        setEnabled(clConfig.enabled !== false)
      }
    }
  }, [configData])

  const handleSave = () => {
    if (onSave) {
      const config: SearchConfig = {
        ...configData?.config,
        cover_letter: {
          enabled,
          min_score: 7,
          limit: 20,
          validation_mode: 'normal',
        },
      }
      onSave(config)
    }
  }

  const createMutation = useMutation({
    mutationFn: () => {
      if (!templateRoleCategory || !templateContent) {
        throw new Error('Category and content are required')
      }
      return coverLetterTemplatesApi.setTemplate(templateRoleCategory, templateContent)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['coverLetterTemplates'] })
      setShowCreateModal(false)
      resetForm()
      alert('Cover letter template created successfully!')
    },
    onError: (error: unknown) => {
      const message = error instanceof Error ? error.message : 'Unknown error'
      const detail = (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      alert(`Failed to create template: ${detail || message}`)
    },
  })

  const updateMutation = useMutation({
    mutationFn: () => {
      if (!editingTemplate) throw new Error('No template selected')
      if (!templateRoleCategory || !templateContent) {
        throw new Error('Category and content are required')
      }
      return coverLetterTemplatesApi.setTemplate(templateRoleCategory, templateContent)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['coverLetterTemplates'] })
      setEditingTemplate(null)
      resetForm()
      alert('Cover letter template updated successfully!')
    },
    onError: (error: unknown) => {
      const message = error instanceof Error ? error.message : 'Unknown error'
      const detail = (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      alert(`Failed to update template: ${detail || message}`)
    },
  })

  const resetForm = () => {
    setTemplateContent('')
    setTemplateRoleCategory('')
  }

  const handleEdit = (template: CoverLetterTemplate) => {
    setEditingTemplate(template)
    setTemplateContent(template.content)
    setTemplateRoleCategory(template.role_category || '')
    setShowCreateModal(true)
  }

  const handleCreate = () => {
    setEditingTemplate(null)
    resetForm()
    setShowCreateModal(true)
  }

  const handleSaveTemplate = () => {
    if (editingTemplate) {
      updateMutation.mutate()
    } else {
      createMutation.mutate()
    }
  }

  const deleteMutation = useMutation({
    mutationFn: (roleCategory: string) => coverLetterTemplatesApi.deleteTemplate(roleCategory),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['coverLetterTemplates'] })
      alert('Template deleted successfully!')
    },
    onError: (error: unknown) => {
      const message = error instanceof Error ? error.message : 'Unknown error'
      const detail = (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      alert(`Failed to delete template: ${detail || message}`)
    },
  })

  const templates = templatesData?.templates || []

  return (
    <div className="section-form cover-letter-container">
      <div className="cover-letter-header">
        <h3>Cover Letter Configuration</h3>
        <p className="section-description">
          Create cover letter templates for different target roles, or enable AI-generated cover letters.
          Templates will be automatically selected based on the job's role category.
        </p>
      </div>

      {/* Enable/Disable AI Generation */}
      <div className="cover-letter-section">
        <h4 className="cover-letter-section-title">AI Generation</h4>
        <div className="job-config-input-group" style={{ maxWidth: '600px' }}>
          <label className="job-config-label" style={{ display: 'flex', alignItems: 'center', cursor: 'pointer', fontSize: '1.1rem' }}>
            <input
              type="checkbox"
              checked={enabled}
              onChange={(e) => setEnabled(e.target.checked)}
              style={{ marginRight: '0.75rem', width: '20px', height: '20px', cursor: 'pointer' }}
            />
            <span>Enable AI-generated cover letters (when no template matches)</span>
          </label>
          <div className="job-config-hint" style={{ marginTop: '0.75rem', marginLeft: '2rem' }}>
            When enabled, AI will generate cover letters for jobs with fit score ≥ 7 if no matching template is found.
          </div>
        </div>
      </div>

      {/* Templates Section */}
      <div className="cover-letter-section">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
          <h4 className="cover-letter-section-title">Templates</h4>
          <button
            type="button"
            onClick={handleCreate}
            className="save-config-button"
            style={{ padding: '0.5rem 1rem', fontSize: '0.9rem' }}
          >
            + Create Template
          </button>
        </div>

        {templatesLoading ? (
          <div className="empty-state">Loading templates...</div>
        ) : templates.length === 0 ? (
          <div className="empty-state">
            <p>No cover letter templates created yet.</p>
            <p>Create templates for different target roles to use custom cover letters.</p>
          </div>
        ) : (
          <div className="templates-list">
            {templates.map((template) => {
              const roleName = template.role_category 
                ? (targetRoles[template.role_category] as { name?: string })?.name || template.role_category
                : 'General'
              
              return (
                <div key={template.role_category} className="template-card">
                  <div className="template-header">
                    <div>
                      <h5>{roleName}</h5>
                      {template.content && (
                        <div className="template-preview" style={{ marginTop: '0.5rem', fontSize: '0.85rem', maxHeight: '100px', overflow: 'hidden' }}>
                          {template.content.substring(0, 150)}{template.content.length > 150 ? '...' : ''}
                        </div>
                      )}
                    </div>
                    <div className="template-actions">
                      <button
                        type="button"
                        onClick={() => handleEdit(template)}
                        className="template-action-btn"
                      >
                        Edit
                      </button>
                      <button
                        type="button"
                        onClick={() => {
                          if (confirm(`Delete template for "${roleName}"?`)) {
                            deleteMutation.mutate(template.role_category)
                          }
                        }}
                        className="template-action-btn delete"
                        disabled={deleteMutation.isPending}
                      >
                        Delete
                      </button>
                    </div>
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </div>

      {/* Create/Edit Modal */}
      {showCreateModal && (
        <div className="upload-modal-overlay" onClick={() => { setShowCreateModal(false); resetForm(); setEditingTemplate(null) }}>
          <div className="upload-modal" onClick={(e) => e.stopPropagation()} style={{ maxWidth: '700px', width: '90%' }}>
            <div className="upload-modal-header">
              <h4>{editingTemplate ? 'Edit' : 'Create'} Cover Letter Template</h4>
              <button type="button" onClick={() => { setShowCreateModal(false); resetForm(); setEditingTemplate(null) }}>×</button>
            </div>
            <div className="upload-modal-content">
              <div className="job-config-input-group">
                <label className="job-config-label">
                  Target Role
                  <span className="required">*</span>
                </label>
                <select
                  value={templateRoleCategory}
                  onChange={(e) => setTemplateRoleCategory(e.target.value)}
                  className="job-config-input"
                  required
                >
                  <option value="">Select a role...</option>
                  {targetRolesList.map(([key, role]) => {
                    const roleData = role as { name?: string }
                    return (
                      <option key={key} value={key}>
                        {roleData.name || key}
                      </option>
                    )
                  })}
                </select>
                <div className="job-config-hint">
                  Select a target role. This template will be used for jobs matching this role category.
                </div>
              </div>
              <div className="job-config-input-group" style={{ gridColumn: '1 / -1' }}>
                <label className="job-config-label">
                  Content
                  <span className="required">*</span>
                </label>
                <textarea
                  value={templateContent}
                  onChange={(e) => setTemplateContent(e.target.value)}
                  placeholder="Enter your cover letter template content here..."
                  className="job-config-input"
                  style={{ minHeight: '300px', fontFamily: 'monospace', fontSize: '0.9rem' }}
                  rows={15}
                />
                <div className="job-config-hint">
                  Enter the cover letter content. You can use placeholders like {`{job_title}`}, {`{company_name}`}, etc. if needed.
                </div>
              </div>
              <div className="upload-modal-actions">
                <button
                  type="button"
                  onClick={() => { setShowCreateModal(false); resetForm(); setEditingTemplate(null) }}
                  className="template-action-btn"
                >
                  Cancel
                </button>
                <button
                  type="button"
                  onClick={handleSaveTemplate}
                  disabled={!templateRoleCategory || !templateContent || createMutation.isPending || updateMutation.isPending}
                  className="save-config-button"
                >
                  {createMutation.isPending || updateMutation.isPending ? 'Saving...' : (editingTemplate ? 'Update' : 'Create')}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Save Button */}
      {onSave && (
        <div className="cover-letter-actions">
          <button
            type="button"
            onClick={handleSave}
            disabled={isSaving}
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
