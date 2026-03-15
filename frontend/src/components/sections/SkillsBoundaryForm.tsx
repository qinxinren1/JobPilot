import { useState } from 'react'
import { SkillsBoundary } from '../../api/client'
import { useFormData } from '../../hooks/useFormData'
import './SectionForm.css'

interface SkillsBoundaryFormProps {
  data: Partial<SkillsBoundary>
  onChange: (data: Partial<SkillsBoundary>) => void
}

// Predefined categories
const TECHNICAL_CATEGORIES = [
  { key: 'programming_languages', label: 'Programming Languages', placeholder: 'e.g., Python, JavaScript, Java' },
  { key: 'frameworks', label: 'Frameworks & Libraries', placeholder: 'e.g., React, FastAPI, Flask' },
  { key: 'devops', label: 'DevOps & Infrastructure', placeholder: 'e.g., Docker, AWS, CI/CD' },
  { key: 'databases', label: 'Databases', placeholder: 'e.g., PostgreSQL, MongoDB, Redis' },
  { key: 'tools', label: 'Tools & Platforms', placeholder: 'e.g., Git, Linux, Docker' },
  { key: 'languages', label: 'Languages (Legacy)', placeholder: 'e.g., Python, JavaScript' },
]

const SOFT_SKILLS_CATEGORIES = [
  { key: 'communication', label: 'Communication', placeholder: 'e.g., Public Speaking, Technical Writing' },
  { key: 'leadership', label: 'Leadership', placeholder: 'e.g., Team Management, Mentoring' },
  { key: 'problem_solving', label: 'Problem Solving', placeholder: 'e.g., Analytical Thinking, Debugging' },
  { key: 'teamwork', label: 'Teamwork', placeholder: 'e.g., Collaboration, Cross-functional' },
  { key: 'time_management', label: 'Time Management', placeholder: 'e.g., Agile, Scrum, Prioritization' },
]

export default function SkillsBoundaryForm({ data, onChange }: SkillsBoundaryFormProps) {
  const { formData, handleChange } = useFormData<SkillsBoundary>(data, onChange)
  const [newCategoryName, setNewCategoryName] = useState('')
  const [showAddCategory, setShowAddCategory] = useState(false)

  // Get all custom categories (not in predefined lists)
  const allPredefinedKeys = new Set([
    ...TECHNICAL_CATEGORIES.map(c => c.key),
    ...SOFT_SKILLS_CATEGORIES.map(c => c.key)
  ])
  
  const customCategories = Object.keys(formData || {})
    .filter(key => !allPredefinedKeys.has(key) && Array.isArray(formData[key]))
    .map(key => ({
      key,
      label: key.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase()),
      placeholder: 'e.g., Add skills...'
    }))

  const handleArrayChange = (category: string, items: string[]) => {
    handleChange(category as keyof SkillsBoundary, items)
  }

  const addItem = (category: string) => {
    const current = (formData[category] as string[]) || []
    handleArrayChange(category, [...current, ''])
  }

  const updateItem = (category: string, index: number, value: string) => {
    const current = (formData[category] as string[]) || []
    const updated = [...current]
    updated[index] = value
    handleArrayChange(category, updated.filter(item => item.trim() !== ''))
  }

  const removeItem = (category: string, index: number) => {
    const current = (formData[category] as string[]) || []
    const updated = current.filter((_, i) => i !== index)
    handleArrayChange(category, updated)
  }

  const removeCategory = (category: string) => {
    const updated = { ...formData }
    delete updated[category]
    onChange(updated)
  }

  const addCustomCategory = () => {
    const categoryKey = newCategoryName.trim().toLowerCase().replace(/\s+/g, '_')
    if (categoryKey && !formData[categoryKey]) {
      handleChange(categoryKey as keyof SkillsBoundary, [])
      setNewCategoryName('')
      setShowAddCategory(false)
    }
  }

  const renderArrayInput = (category: { key: string; label: string; placeholder: string }, isCustom: boolean = false) => {
    const items = (formData[category.key] as string[]) || []

    return (
      <div key={category.key} className="form-group full-width">
        <div className="category-header">
          <label>{category.label}</label>
          {isCustom && (
            <button
              type="button"
              className="remove-category-btn"
              onClick={() => removeCategory(category.key)}
              title="Remove this category"
            >
              Remove Category
            </button>
          )}
        </div>
        <div className="array-input">
          {items.map((item, index) => (
            <div key={index} className="array-item">
              <input
                type="text"
                value={item}
                onChange={(e) => updateItem(category.key, index, e.target.value)}
                placeholder={category.placeholder}
              />
              <button type="button" onClick={() => removeItem(category.key, index)}>
                Remove
              </button>
            </div>
          ))}
          <button
            type="button"
            className="add-item-button"
            onClick={() => addItem(category.key)}
          >
            + Add {category.label}
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="section-form">
      <h3>Skills Boundary</h3>
      <p className="section-description">
        List your real skills (both technical and soft skills), which will be preserved during resume tailoring.
        You can add custom categories for any type of skill.
      </p>

      <div className="form-grid">
        {/* Technical Skills Section */}
        <div className="form-group full-width">
          <h4 className="section-subtitle">Technical Skills</h4>
        </div>
        {TECHNICAL_CATEGORIES.map(category => renderArrayInput(category))}

        {/* Soft Skills Section */}
        <div className="form-group full-width">
          <h4 className="section-subtitle">Soft Skills</h4>
        </div>
        {SOFT_SKILLS_CATEGORIES.map(category => renderArrayInput(category))}

        {/* Custom Categories Section */}
        {customCategories.length > 0 && (
          <>
            <div className="form-group full-width">
              <h4 className="section-subtitle">Custom Categories</h4>
            </div>
            {customCategories.map(category => renderArrayInput(category, true))}
          </>
        )}

        {/* Add Custom Category */}
        <div className="form-group full-width">
          {!showAddCategory ? (
            <button
              type="button"
              className="add-category-button"
              onClick={() => setShowAddCategory(true)}
            >
              + Add Custom Category
            </button>
          ) : (
            <div className="add-category-form">
              <input
                type="text"
                className="category-name-input"
                placeholder="Category name (e.g., Design Tools, Cloud Services)"
                value={newCategoryName}
                onChange={(e) => setNewCategoryName(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') {
                    e.preventDefault()
                    addCustomCategory()
                  } else if (e.key === 'Escape') {
                    setShowAddCategory(false)
                    setNewCategoryName('')
                  }
                }}
                autoFocus
              />
              <div className="category-form-actions">
                <button
                  type="button"
                  className="add-item-button"
                  onClick={addCustomCategory}
                >
                  Add Category
                </button>
                <button
                  type="button"
                  className="cancel-button"
                  onClick={() => {
                    setShowAddCategory(false)
                    setNewCategoryName('')
                  }}
                >
                  Cancel
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
