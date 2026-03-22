import { useState, useEffect, useRef } from 'react'
import {
  Experience,
  WorkExperience,
  ProjectExperience,
  EducationExperience,
  AwardExperience,
} from '../../api/client'

/** UI rows may carry a stable client-side id for React keys and selection */
type WorkExperienceRow = WorkExperience & { _id?: string }
type ProjectExperienceRow = ProjectExperience & { _id?: string }
import MonthYearPicker from '../MonthYearPicker'
import './SectionForm.css'

interface ExperienceFormProps {
  data: Partial<Experience>
  onChange: (data: Partial<Experience>) => void
}

// Helper function to auto-resize textarea
const autoResizeTextarea = (textarea: HTMLTextAreaElement) => {
  textarea.style.height = 'auto'
  textarea.style.height = textarea.scrollHeight + 'px'
}

export default function ExperienceForm({ data, onChange }: ExperienceFormProps) {
  const [formData, setFormData] = useState<Partial<Experience>>(data)
  const [activeTab, setActiveTab] = useState<'summary' | 'work' | 'projects' | 'education' | 'awards'>('summary')
  const isInternalUpdate = useRef(false)
  const idCounter = useRef(0)
  
  // Ensure all experiences and projects have unique IDs on initial load
  useEffect(() => {
    const experiences = formData.work_experiences || []
    const projects = formData.projects || []
    
    let needsUpdate = false
    const updatedExperiences = experiences.map((exp: WorkExperienceRow) => {
      if (!exp._id) {
        needsUpdate = true
        return { ...exp, _id: `exp_${Date.now()}_${idCounter.current++}` }
      }
      return exp
    })
    
    const updatedProjects = projects.map((proj: ProjectExperienceRow) => {
      if (!proj._id) {
        needsUpdate = true
        return { ...proj, _id: `proj_${Date.now()}_${idCounter.current++}` }
      }
      return proj
    })
    
    if (needsUpdate) {
      isInternalUpdate.current = true
      const updated = {
        ...formData,
        work_experiences: updatedExperiences,
        projects: updatedProjects
      }
      setFormData(updated)
      onChange(updated)
      isInternalUpdate.current = false
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []) // Only run once on mount

  useEffect(() => {
    // Only update if the change came from outside (not from our own onChange)
    if (!isInternalUpdate.current) {
      // Ensure IDs are preserved when data comes from outside
      const experiences = (data.work_experiences || []).map((exp: WorkExperienceRow) => {
        if (!exp._id) {
          return { ...exp, _id: `exp_${Date.now()}_${idCounter.current++}` }
        }
        return exp
      })
      
      const projects = (data.projects || []).map((proj: ProjectExperienceRow) => {
        if (!proj._id) {
          return { ...proj, _id: `proj_${Date.now()}_${idCounter.current++}` }
        }
        return proj
      })
      
      setFormData({
        ...data,
        work_experiences: experiences,
        projects: projects
      })
    }
    isInternalUpdate.current = false
    
    // Auto-resize all textareas after data update
    setTimeout(() => {
      const textareas = document.querySelectorAll('.array-item textarea')
      textareas.forEach((textarea) => {
        autoResizeTextarea(textarea as HTMLTextAreaElement)
      })
    }, 0)
  }, [data])

  const handleChange = (field: keyof Experience, value: Experience[keyof Experience]) => {
    isInternalUpdate.current = true
    const updated = { ...formData, [field]: value }
    setFormData(updated)
    onChange(updated)
  }

  // Work Experience handlers
  const addWorkExperience = () => {
    const newExp: WorkExperienceRow = {
      company: '',
      title: '',
      start_date: '',
      end_date: '',
      current: false,
      bullets: [],
      _id: `exp_${Date.now()}_${idCounter.current++}`,
    }
    const experiences = formData.work_experiences || []
    handleChange('work_experiences', [...experiences, newExp])
  }

  const updateWorkExperience = (index: number, field: keyof WorkExperience, value: WorkExperience[keyof WorkExperience]) => {
    const experiences = [...(formData.work_experiences || [])]
    const currentExp = experiences[index] || { company: '', title: '', start_date: '', end_date: '', current: false, bullets: [] }
    experiences[index] = { ...currentExp, [field]: value }
    handleChange('work_experiences', experiences)
  }

  const removeWorkExperience = (index: number) => {
    const experiences = formData.work_experiences || []
    handleChange('work_experiences', experiences.filter((_, i) => i !== index))
  }

  const moveWorkExperience = (index: number, direction: 'up' | 'down') => {
    const experiences = [...(formData.work_experiences || [])]
    if (direction === 'up' && index === 0) return
    if (direction === 'down' && index === experiences.length - 1) return
    
    const newIndex = direction === 'up' ? index - 1 : index + 1
    const [moved] = experiences.splice(index, 1)
    experiences.splice(newIndex, 0, moved)
    handleChange('work_experiences', experiences)
  }

  const addWorkBullet = (index: number) => {
    const experiences = [...(formData.work_experiences || [])]
    const updatedBullets = [...(experiences[index].bullets || []), '']
    experiences[index] = { ...experiences[index], bullets: updatedBullets }
    handleChange('work_experiences', experiences)
  }

  // Helper function to parse bullet string into category and detail
  const parseBullet = (bullet: string): { category: string; detail: string } => {
    const colonIndex = bullet.indexOf(':');
    if (colonIndex > 0) {
      const category = bullet.substring(0, colonIndex).trim();
      const detail = bullet.substring(colonIndex + 1).trimStart();
      return { category, detail };
    }
    return { category: '', detail: bullet };
  }

  // Store bullets as objects internally, but convert to strings when saving
  const getBulletData = (bullets: string[]): Array<{ category: string; detail: string }> => {
    return bullets.map(bullet => parseBullet(bullet));
  }

  const updateWorkBulletCategory = (expIndex: number, bulletIndex: number, category: string) => {
    const experiences = [...(formData.work_experiences || [])]
    const bulletData = getBulletData(experiences[expIndex].bullets || [])
    bulletData[bulletIndex] = { ...bulletData[bulletIndex], category }
    // Convert back to string array for storage (only when saving, but we'll do it here for consistency)
    // Actually, we'll store as string but only combine when needed
    const updatedBullets = bulletData.map(b => {
      if (b.category.trim() && b.detail) {
        return `${b.category}: ${b.detail}`;
      }
      return b.detail;
    })
    experiences[expIndex] = { ...experiences[expIndex], bullets: updatedBullets }
    handleChange('work_experiences', experiences)
  }

  const updateWorkBulletDetail = (expIndex: number, bulletIndex: number, detail: string) => {
    const experiences = [...(formData.work_experiences || [])]
    const bulletData = getBulletData(experiences[expIndex].bullets || [])
    bulletData[bulletIndex] = { ...bulletData[bulletIndex], detail }
    // Convert back to string array
    const updatedBullets = bulletData.map(b => {
      if (b.category.trim() && b.detail) {
        return `${b.category}: ${b.detail}`;
      }
      return b.detail;
    })
    experiences[expIndex] = { ...experiences[expIndex], bullets: updatedBullets }
    handleChange('work_experiences', experiences)
  }

  const removeWorkBullet = (expIndex: number, bulletIndex: number) => {
    const experiences = [...(formData.work_experiences || [])]
    const updatedBullets = (experiences[expIndex].bullets || []).filter((_, i) => i !== bulletIndex)
    experiences[expIndex] = { ...experiences[expIndex], bullets: updatedBullets }
    handleChange('work_experiences', experiences)
  }

  // Project handlers
  const addProject = () => {
    const newProject: ProjectExperienceRow = {
      name: '',
      tech_stack: [],
      start_date: '',
      end_date: '',
      current: false,
      bullets: [],
      _id: `proj_${Date.now()}_${idCounter.current++}`,
    }
    const projects = formData.projects || []
    handleChange('projects', [...projects, newProject])
  }

  const updateProject = (index: number, field: keyof ProjectExperience, value: ProjectExperience[keyof ProjectExperience]) => {
    const projects = [...(formData.projects || [])]
    const currentProject = projects[index] || { name: '', tech_stack: [], start_date: '', end_date: '', current: false, bullets: [] }
    projects[index] = { ...currentProject, [field]: value }
    handleChange('projects', projects)
  }

  const removeProject = (index: number) => {
    const projects = formData.projects || []
    handleChange('projects', projects.filter((_, i) => i !== index))
  }

  const moveProject = (index: number, direction: 'up' | 'down') => {
    const projects = [...(formData.projects || [])]
    if (direction === 'up' && index === 0) return
    if (direction === 'down' && index === projects.length - 1) return
    
    const newIndex = direction === 'up' ? index - 1 : index + 1
    const [moved] = projects.splice(index, 1)
    projects.splice(newIndex, 0, moved)
    handleChange('projects', projects)
  }

  const addProjectBullet = (index: number) => {
    const projects = [...(formData.projects || [])]
    const updatedBullets = [...(projects[index].bullets || []), '']
    projects[index] = { ...projects[index], bullets: updatedBullets }
    handleChange('projects', projects)
  }

  const updateProjectBulletCategory = (projIndex: number, bulletIndex: number, category: string) => {
    const projects = [...(formData.projects || [])]
    const bulletData = getBulletData(projects[projIndex].bullets || [])
    bulletData[bulletIndex] = { ...bulletData[bulletIndex], category }
    const updatedBullets = bulletData.map(b => {
      if (b.category.trim() && b.detail) {
        return `${b.category}: ${b.detail}`;
      }
      return b.detail;
    })
    projects[projIndex] = { ...projects[projIndex], bullets: updatedBullets }
    handleChange('projects', projects)
  }

  const updateProjectBulletDetail = (projIndex: number, bulletIndex: number, detail: string) => {
    const projects = [...(formData.projects || [])]
    const bulletData = getBulletData(projects[projIndex].bullets || [])
    bulletData[bulletIndex] = { ...bulletData[bulletIndex], detail }
    const updatedBullets = bulletData.map(b => {
      if (b.category.trim() && b.detail) {
        return `${b.category}: ${b.detail}`;
      }
      return b.detail;
    })
    projects[projIndex] = { ...projects[projIndex], bullets: updatedBullets }
    handleChange('projects', projects)
  }

  const removeProjectBullet = (projIndex: number, bulletIndex: number) => {
    const projects = [...(formData.projects || [])]
    const updatedBullets = (projects[projIndex].bullets || []).filter((_, i) => i !== bulletIndex)
    projects[projIndex] = { ...projects[projIndex], bullets: updatedBullets }
    handleChange('projects', projects)
  }

  // Education handlers
  const addEducation = () => {
    const newEdu: EducationExperience = {
      school: '',
      degree: '',
      start_date: '',
      end_date: '',
    }
    const education = formData.education || []
    handleChange('education', [...education, newEdu])
  }

  const updateEducation = (index: number, field: keyof EducationExperience, value: EducationExperience[keyof EducationExperience]) => {
    const education = [...(formData.education || [])]
    education[index] = { ...education[index], [field]: value }
    handleChange('education', education)
  }

  const removeEducation = (index: number) => {
    const education = formData.education || []
    handleChange('education', education.filter((_, i) => i !== index))
  }

  // Awards handlers
  const addAward = () => {
    const newAward: AwardExperience = {
      name: '',
      category: '',
    }
    const awards = formData.awards || []
    handleChange('awards', [...awards, newAward])
  }

  const updateAward = (index: number, field: keyof AwardExperience, value: AwardExperience[keyof AwardExperience]) => {
    const awards = [...(formData.awards || [])]
    awards[index] = { ...awards[index], [field]: value }
    handleChange('awards', awards)
  }

  const removeAward = (index: number) => {
    const awards = formData.awards || []
    handleChange('awards', awards.filter((_, i) => i !== index))
  }

  return (
    <div className="section-form">
      <h3>Experience</h3>
      <p className="section-description">Manage your work experience, projects, and education</p>

      {/* Tabs */}
      <div className="experience-tabs">
        <button
          className={`tab-btn ${activeTab === 'summary' ? 'active' : ''}`}
          onClick={() => setActiveTab('summary')}
        >
          Summary
        </button>
        <button
          className={`tab-btn ${activeTab === 'work' ? 'active' : ''}`}
          onClick={() => setActiveTab('work')}
        >
          Work Experience ({formData.work_experiences?.length || 0})
        </button>
        <button
          className={`tab-btn ${activeTab === 'projects' ? 'active' : ''}`}
          onClick={() => setActiveTab('projects')}
        >
          Projects ({formData.projects?.length || 0})
        </button>
        <button
          className={`tab-btn ${activeTab === 'education' ? 'active' : ''}`}
          onClick={() => setActiveTab('education')}
        >
          Education ({formData.education?.length || 0})
        </button>
        <button
          className={`tab-btn ${activeTab === 'awards' ? 'active' : ''}`}
          onClick={() => setActiveTab('awards')}
        >
          Awards ({formData.awards?.length || 0})
        </button>
      </div>

      {/* Summary Tab */}
      {activeTab === 'summary' && (
        <div className="form-grid">
          <div className="form-group">
            <label htmlFor="years_of_experience_total">Total Years of Experience</label>
            <input
              type="text"
              id="years_of_experience_total"
              value={formData.years_of_experience_total || ''}
              onChange={(e) => handleChange('years_of_experience_total', e.target.value)}
              placeholder="3"
            />
          </div>

          <div className="form-group">
            <label htmlFor="education_level">Highest Education Level</label>
            <select
              id="education_level"
              value={formData.education_level || ''}
              onChange={(e) => handleChange('education_level', e.target.value)}
            >
              <option value="">Please select</option>
              <option value="High School">High School</option>
              <option value="Associate's Degree">Associate's Degree</option>
              <option value="Bachelor's Degree">Bachelor's Degree</option>
              <option value="Master's Degree">Master's Degree</option>
              <option value="PhD">PhD</option>
              <option value="Self-taught">Self-taught</option>
            </select>
          </div>

          <div className="form-group">
            <label htmlFor="current_job_title">Current Job Title</label>
            <input
              type="text"
              id="current_job_title"
              value={formData.current_job_title || formData.current_title || ''}
              onChange={(e) => {
                const value = e.target.value
                const updated = { ...formData, current_job_title: value, current_title: value }
                setFormData(updated)
                onChange(updated)
              }}
              placeholder="Senior Software Engineer"
            />
          </div>

          <div className="form-group">
            <label htmlFor="current_company">Current Company</label>
            <input
              type="text"
              id="current_company"
              value={formData.current_company || ''}
              onChange={(e) => handleChange('current_company', e.target.value)}
              placeholder="Company Name"
            />
          </div>
        </div>
      )}

      {/* Work Experience Tab */}
      {activeTab === 'work' && (
        <div className="experience-list">
          {(formData.work_experiences || []).map((exp: WorkExperienceRow, index) => (
            <div key={exp._id || index} className="experience-item">
              <div className="experience-item-header">
                <h4>Work Experience #{index + 1}</h4>
                <div className="experience-item-actions">
                  <div className="reorder-buttons">
                    <button
                      type="button"
                      className="reorder-btn"
                      onClick={() => moveWorkExperience(index, 'up')}
                      disabled={index === 0}
                      title="Move up"
                    >
                      ↑
                    </button>
                    <button
                      type="button"
                      className="reorder-btn"
                      onClick={() => moveWorkExperience(index, 'down')}
                      disabled={index === (formData.work_experiences || []).length - 1}
                      title="Move down"
                    >
                      ↓
                    </button>
                  </div>
                  <button
                    type="button"
                    className="remove-btn"
                    onClick={() => removeWorkExperience(index)}
                  >
                    Remove
                  </button>
                </div>
              </div>
              <div className="form-grid">
                <div className="form-group">
                  <label>Company *</label>
                  <input
                    type="text"
                    value={exp.company}
                    onChange={(e) => updateWorkExperience(index, 'company', e.target.value)}
                    placeholder="Company Name"
                    required
                  />
                </div>
                <div className="form-group">
                  <label>Job Title *</label>
                  <input
                    type="text"
                    value={exp.title}
                    onChange={(e) => updateWorkExperience(index, 'title', e.target.value)}
                    placeholder="Software Engineer"
                    required
                  />
                </div>
                <div className="form-group">
                  <label>Start Date *</label>
                  <MonthYearPicker
                    value={exp.start_date || ''}
                    onChange={(value) => updateWorkExperience(index, 'start_date', value)}
                    required
                    placeholder="Select start month"
                  />
                </div>
                <div className="form-group">
                  <label>End Date</label>
                  <MonthYearPicker
                    value={exp.current ? '' : (exp.end_date || '')}
                    onChange={(value) => updateWorkExperience(index, 'end_date', value)}
                    disabled={exp.current}
                    placeholder="Select end month"
                  />
                </div>
                <div className="form-group">
                  <div className="checkbox-group">
                    <input
                      type="checkbox"
                      checked={exp.current || false}
                      onChange={(e) => {
                        const isChecked = e.target.checked
                        const experiences = [...(formData.work_experiences || [])]
                        const currentExp = experiences[index] || { company: '', title: '', start_date: '', end_date: '', current: false, bullets: [] }
                        experiences[index] = { 
                          ...currentExp, 
                          current: isChecked,
                          end_date: isChecked ? '' : currentExp.end_date
                        }
                        handleChange('work_experiences', experiences)
                      }}
                    />
                    <label>Current Position</label>
                  </div>
                </div>
                <div className="form-group">
                  <label>Location</label>
                  <input
                    type="text"
                    value={exp.location || ''}
                    onChange={(e) => updateWorkExperience(index, 'location', e.target.value)}
                    placeholder="City, Country"
                  />
                </div>
                <div className="form-group full-width">
                  <label>Responsibilities & Achievements</label>
                  {exp.bullets.map((bullet, bulletIndex) => {
                    const parsed = parseBullet(bullet);
                    return (
                      <div key={bulletIndex} className="array-item" style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                        <div style={{ display: 'flex', gap: '8px', width: '100%' }}>
                          <input
                            type="text"
                            value={parsed.category}
                            onChange={(e) => {
                              updateWorkBulletCategory(index, bulletIndex, e.target.value);
                            }}
                            placeholder="Category (e.g., Product Discovery & Execution)"
                            style={{ flex: '0 0 40%', padding: '8px', borderRadius: '4px', border: '1px solid #ddd' }}
                          />
                          <textarea
                            value={parsed.detail}
                            onChange={(e) => {
                              updateWorkBulletDetail(index, bulletIndex, e.target.value);
                              autoResizeTextarea(e.target);
                            }}
                            onInput={(e) => {
                              autoResizeTextarea(e.target as HTMLTextAreaElement);
                            }}
                            ref={(textarea) => {
                              if (textarea) {
                                autoResizeTextarea(textarea);
                              }
                            }}
                            placeholder="Details (e.g., Identified user needs through extensive interviews and led end-to-end delivery)"
                            rows={1}
                            style={{ flex: '1', padding: '8px', borderRadius: '4px', border: '1px solid #ddd', resize: 'vertical', minHeight: '36px' }}
                          />
                          <button
                            type="button"
                            onClick={() => removeWorkBullet(index, bulletIndex)}
                            style={{ flex: '0 0 auto', padding: '8px 12px', height: 'fit-content' }}
                          >
                            Remove
                          </button>
                        </div>
                      </div>
                    );
                  })}
                  <button
                    type="button"
                    className="add-item-button"
                    onClick={() => addWorkBullet(index)}
                  >
                    + Add Bullet Point
                  </button>
                </div>
              </div>
            </div>
          ))}
          <button type="button" className="add-item-button" onClick={addWorkExperience}>
            + Add Work Experience
          </button>
        </div>
      )}

      {/* Projects Tab */}
      {activeTab === 'projects' && (
        <div className="experience-list">
          {(formData.projects || []).map((project: ProjectExperienceRow, index) => (
            <div key={project._id || index} className="experience-item">
              <div className="experience-item-header">
                <h4>Project #{index + 1}</h4>
                <div className="experience-item-actions">
                  <div className="reorder-buttons">
                    <button
                      type="button"
                      className="reorder-btn"
                      onClick={() => moveProject(index, 'up')}
                      disabled={index === 0}
                      title="Move up"
                    >
                      ↑
                    </button>
                    <button
                      type="button"
                      className="reorder-btn"
                      onClick={() => moveProject(index, 'down')}
                      disabled={index === (formData.projects || []).length - 1}
                      title="Move down"
                    >
                      ↓
                    </button>
                  </div>
                  <button
                    type="button"
                    className="remove-btn"
                    onClick={() => removeProject(index)}
                  >
                    Remove
                  </button>
                </div>
              </div>
              <div className="form-grid">
                <div className="form-group">
                  <label>Project Name *</label>
                  <input
                    type="text"
                    value={project.name}
                    onChange={(e) => updateProject(index, 'name', e.target.value)}
                    placeholder="E-commerce Platform"
                    required
                  />
                </div>
                <div className="form-group">
                  <label>Start Date *</label>
                  <MonthYearPicker
                    value={project.start_date || ''}
                    onChange={(value) => updateProject(index, 'start_date', value)}
                    required
                    placeholder="Select start month"
                  />
                </div>
                <div className="form-group">
                  <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                    End Date
                    <input
                      type="checkbox"
                      checked={project.current || false}
                      onChange={(e) => {
                        const isChecked = e.target.checked
                        const projects = [...(formData.projects || [])]
                        const currentProject = projects[index] || { name: '', tech_stack: [], start_date: '', end_date: '', current: false, bullets: [] }
                        projects[index] = { 
                          ...currentProject, 
                          current: isChecked,
                          end_date: isChecked ? '' : currentProject.end_date
                        }
                        handleChange('projects', projects)
                      }}
                      style={{ width: '16px', height: '16px', margin: 0, cursor: 'pointer' }}
                    />
                    <span style={{ fontSize: '0.875rem', fontWeight: 400 }}>Ongoing</span>
                  </label>
                  <MonthYearPicker
                    value={project.current ? '' : (project.end_date || '')}
                    onChange={(value) => updateProject(index, 'end_date', value)}
                    disabled={project.current}
                    placeholder="Select end month"
                  />
                </div>
                <div className="form-group">
                  <label>Location</label>
                  <input
                    type="text"
                    value={project.location || ''}
                    onChange={(e) => updateProject(index, 'location', e.target.value)}
                    placeholder="City, Country"
                  />
                </div>
                <div className="form-group full-width">
                  <label>Project Description & Achievements</label>
                  {project.bullets.map((bullet, bulletIndex) => {
                    const parsed = parseBullet(bullet);
                    return (
                      <div key={bulletIndex} className="array-item" style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                        <div style={{ display: 'flex', gap: '8px', width: '100%' }}>
                          <input
                            type="text"
                            value={parsed.category}
                            onChange={(e) => {
                              updateProjectBulletCategory(index, bulletIndex, e.target.value);
                            }}
                            placeholder="Category (e.g., Product Discovery & Execution)"
                            style={{ flex: '0 0 40%', padding: '8px', borderRadius: '4px', border: '1px solid #ddd' }}
                          />
                          <textarea
                            value={parsed.detail}
                            onChange={(e) => {
                              updateProjectBulletDetail(index, bulletIndex, e.target.value);
                              autoResizeTextarea(e.target);
                            }}
                            onInput={(e) => {
                              autoResizeTextarea(e.target as HTMLTextAreaElement);
                            }}
                            ref={(textarea) => {
                              if (textarea) {
                                autoResizeTextarea(textarea);
                              }
                            }}
                            placeholder="Details (e.g., Identified user needs through extensive interviews and led end-to-end delivery)"
                            rows={1}
                            style={{ flex: '1', padding: '8px', borderRadius: '4px', border: '1px solid #ddd', resize: 'vertical', minHeight: '36px' }}
                          />
                          <button
                            type="button"
                            onClick={() => removeProjectBullet(index, bulletIndex)}
                            style={{ flex: '0 0 auto', padding: '8px 12px', height: 'fit-content' }}
                          >
                            Remove
                          </button>
                        </div>
                      </div>
                    );
                  })}
                  <button
                    type="button"
                    className="add-item-button"
                    onClick={() => addProjectBullet(index)}
                  >
                    + Add Bullet Point
                  </button>
                </div>
                <div className="form-group full-width">
                  <label>Tech Stack</label>
                  <div className="tags-input-container">
                    <div className="tags-display">
                      {(project.tech_stack || []).map((tech, techIndex) => (
                        <span key={techIndex} className="tag">
                          {tech}
                          <button
                            type="button"
                            className="tag-remove"
                            onClick={() => {
                              const updatedTech = (project.tech_stack || []).filter((_, i) => i !== techIndex)
                              const projects = [...(formData.projects || [])]
                              projects[index] = { ...project, tech_stack: updatedTech }
                              handleChange('projects', projects)
                            }}
                            aria-label={`Remove ${tech}`}
                          >
                            ×
                          </button>
                        </span>
                      ))}
                    </div>
                    <input
                      type="text"
                      className="tags-input"
                      placeholder="Type a technology and press Enter or comma (e.g., Python, React, AWS)"
                      onKeyDown={(e) => {
                        if (e.key === 'Enter' || e.key === ',') {
                          e.preventDefault()
                          const input = e.currentTarget
                          const value = input.value.trim()
                          if (value) {
                            const currentTech = project.tech_stack || []
                            
                            // Handle comma-separated values
                            const newTech = value.includes(',')
                              ? value.split(',').map(t => t.trim()).filter(t => t)
                              : [value]
                            
                            const updatedTech = [...currentTech, ...newTech]
                            const projects = [...(formData.projects || [])]
                            projects[index] = { ...project, tech_stack: updatedTech }
                            handleChange('projects', projects)
                            input.value = ''
                          }
                        }
                      }}
                      onBlur={(e) => {
                        const value = e.target.value.trim()
                        if (value) {
                          const currentTech = project.tech_stack || []
                          
                          // Handle comma-separated values
                          const newTech = value.includes(',')
                            ? value.split(',').map(t => t.trim()).filter(t => t)
                            : [value]
                          
                          const updatedTech = [...currentTech, ...newTech]
                          const projects = [...(formData.projects || [])]
                          projects[index] = { ...project, tech_stack: updatedTech }
                          handleChange('projects', projects)
                          e.target.value = ''
                        }
                      }}
                    />
                  </div>
                  <small>Add technologies used in this project</small>
                </div>
                <div className="form-group full-width">
                  <label>Project URL</label>
                  <input
                    type="url"
                    value={project.url || ''}
                    onChange={(e) => updateProject(index, 'url', e.target.value)}
                    placeholder="https://github.com/username/project"
                  />
                </div>
              </div>
            </div>
          ))}
          <button type="button" className="add-item-button" onClick={addProject}>
            + Add Project
          </button>
        </div>
      )}

      {/* Education Tab */}
      {activeTab === 'education' && (
        <div className="experience-list">
          {(formData.education || []).map((edu, index) => (
            <div key={index} className="experience-item">
              <div className="experience-item-header">
                <h4>Education #{index + 1}</h4>
                <button
                  type="button"
                  className="remove-btn"
                  onClick={() => removeEducation(index)}
                >
                  Remove
                </button>
              </div>
              <div className="form-grid">
                <div className="form-group">
                  <label>School/University *</label>
                  <input
                    type="text"
                    value={edu.school}
                    onChange={(e) => updateEducation(index, 'school', e.target.value)}
                    placeholder="MIT"
                    required
                  />
                </div>
                <div className="form-group">
                  <label>Degree *</label>
                  <input
                    type="text"
                    value={edu.degree}
                    onChange={(e) => updateEducation(index, 'degree', e.target.value)}
                    placeholder="Bachelor of Science in Computer Science"
                    required
                  />
                </div>
                <div className="form-group">
                  <label>Field of Study</label>
                  <input
                    type="text"
                    value={edu.field || ''}
                    onChange={(e) => updateEducation(index, 'field', e.target.value)}
                    placeholder="Computer Science"
                  />
                </div>
                <div className="form-group">
                  <label>Start Date</label>
                  <MonthYearPicker
                    value={edu.start_date || ''}
                    onChange={(value) => updateEducation(index, 'start_date', value)}
                    placeholder="Select start month"
                  />
                </div>
                <div className="form-group">
                  <label>End Date / Graduation</label>
                  <MonthYearPicker
                    value={edu.end_date || ''}
                    onChange={(value) => updateEducation(index, 'end_date', value)}
                    placeholder="Select graduation month"
                  />
                </div>
                <div className="form-group">
                  <label>GPA</label>
                  <input
                    type="text"
                    value={edu.gpa || ''}
                    onChange={(e) => updateEducation(index, 'gpa', e.target.value)}
                    placeholder="3.8 / 4.0"
                  />
                </div>
                <div className="form-group full-width">
                  <label>Honors & Awards</label>
                  <textarea
                    value={(edu.honors || []).join(', ')}
                    onChange={(e) => updateEducation(index, 'honors', e.target.value.split(',').map(h => h.trim()).filter(h => h))}
                    placeholder="Dean's List, Summa Cum Laude (comma-separated)"
                    rows={2}
                  />
                </div>
              </div>
            </div>
          ))}
          <button type="button" className="add-item-button" onClick={addEducation}>
            + Add Education
          </button>
        </div>
      )}

      {/* Awards Tab */}
      {activeTab === 'awards' && (
        <div>
          <div className="array-input">
            {(formData.awards || []).map((award, index) => (
              <div key={index} className="array-item" style={{ position: 'relative' }}>
                <button 
                  type="button" 
                  onClick={() => removeAward(index)}
                  className="array-item button"
                  style={{ 
                    position: 'absolute', 
                    top: '10px', 
                    right: '10px',
                    zIndex: 10
                  }}
                >
                  Remove
                </button>
                <div className="form-grid" style={{ width: '100%', paddingRight: '80px' }}>
                  <div className="form-group">
                    <label>Category</label>
                    <select
                      value={award.category || ''}
                      onChange={(e) => updateAward(index, 'category', e.target.value)}
                    >
                      <option value="">Select category</option>
                      <option value="Academic Awards">Academic Awards</option>
                      <option value="Competitions & Forums">Competitions & Forums</option>
                      <option value="Other">Other</option>
                    </select>
                  </div>
                  <div className="form-group full-width">
                    <label>Award Name *</label>
                    <input
                      type="text"
                      value={award.name || ''}
                      onChange={(e) => updateAward(index, 'name', e.target.value)}
                      placeholder="2021/22 University Academic Excellence Award"
                      required
                    />
                  </div>
                </div>
              </div>
            ))}
            <button type="button" className="add-item-button" onClick={addAward}>
              + Add Award
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
