import { WorkAuthorization } from '../../api/client'
import { useFormData } from '../../hooks/useFormData'
import './SectionForm.css'

interface WorkAuthorizationFormProps {
  data: Partial<WorkAuthorization>
  onChange: (data: Partial<WorkAuthorization>) => void
}

export default function WorkAuthorizationForm({ data, onChange }: WorkAuthorizationFormProps) {
  const { formData, handleChange } = useFormData<WorkAuthorization>(data, onChange)

  const normalizeBoolean = (value: unknown): boolean => {
    if (typeof value === 'boolean') return value
    if (typeof value === 'string') {
      return value.toLowerCase() === 'yes' || value.toLowerCase() === 'true'
    }
    return false
  }

  return (
    <div className="section-form">
      <h3>Work Authorization</h3>
      <p className="section-description">Provide your work authorization status information</p>

      <div className="form-grid">
        <div className="form-group full-width">
          <div className="checkbox-group">
            <input
              type="checkbox"
              id="legally_authorized"
              checked={normalizeBoolean(formData.legally_authorized_to_work)}
              onChange={(e) => handleChange('legally_authorized_to_work', e.target.checked)}
            />
            <label htmlFor="legally_authorized">
              I am legally authorized to work in the target country
            </label>
          </div>
        </div>

        <div className="form-group full-width">
          <div className="checkbox-group">
            <input
              type="checkbox"
              id="require_sponsorship"
              checked={normalizeBoolean(formData.require_sponsorship)}
              onChange={(e) => handleChange('require_sponsorship', e.target.checked)}
            />
            <label htmlFor="require_sponsorship">
              I will now or in the future need work visa sponsorship
            </label>
          </div>
        </div>

        <div className="form-group full-width">
          <label htmlFor="work_permit_type">Work Permit Type</label>
          <input
            type="text"
            id="work_permit_type"
            value={formData.work_permit_type || ''}
            onChange={(e) => handleChange('work_permit_type', e.target.value)}
            placeholder="e.g., Citizen, PR, Open Work Permit"
          />
          <small>If applicable, specify your work permit type</small>
        </div>
      </div>
    </div>
  )
}
