import { Availability } from '../../api/client'
import { useFormData } from '../../hooks/useFormData'
import './SectionForm.css'

interface AvailabilityFormProps {
  data: Partial<Availability>
  onChange: (data: Partial<Availability>) => void
}

export default function AvailabilityForm({ data, onChange }: AvailabilityFormProps) {
  const { formData, handleChange } = useFormData<Availability>(data, onChange)

  const normalizeBoolean = (value: unknown): boolean => {
    if (typeof value === 'boolean') return value
    if (typeof value === 'string') {
      return value.toLowerCase() === 'yes' || value.toLowerCase() === 'true'
    }
    return false
  }

  return (
    <div className="section-form">
      <h3>Availability</h3>
      <p className="section-description">Specify your work availability and preferences</p>

      <div className="form-grid">
        <div className="form-group full-width">
          <label htmlFor="earliest_start_date">Earliest Start Date *</label>
          <input
            type="text"
            id="earliest_start_date"
            value={formData.earliest_start_date || ''}
            onChange={(e) => handleChange('earliest_start_date', e.target.value)}
            placeholder="e.g., Immediately, 2024-03-01"
            required
          />
          <small>The earliest date you can start working</small>
        </div>

        <div className="form-group full-width">
          <div className="checkbox-group">
            <input
              type="checkbox"
              id="available_for_full_time"
              checked={normalizeBoolean(formData.available_for_full_time ?? true)}
              onChange={(e) => handleChange('available_for_full_time', e.target.checked)}
            />
            <label htmlFor="available_for_full_time">
              Available for full-time work
            </label>
          </div>
        </div>

        <div className="form-group full-width">
          <div className="checkbox-group">
            <input
              type="checkbox"
              id="available_for_contract"
              checked={normalizeBoolean(formData.available_for_contract ?? false)}
              onChange={(e) => handleChange('available_for_contract', e.target.checked)}
            />
            <label htmlFor="available_for_contract">
              Available for contract work
            </label>
          </div>
        </div>
      </div>
    </div>
  )
}
