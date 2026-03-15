import { Compensation } from '../../api/client'
import { useFormData } from '../../hooks/useFormData'
import './SectionForm.css'

interface CompensationFormProps {
  data: Partial<Compensation>
  onChange: (data: Partial<Compensation>) => void
}

export default function CompensationForm({ data, onChange }: CompensationFormProps) {
  const { formData, handleChange } = useFormData<Compensation>(data, onChange)

  return (
    <div className="section-form">
      <h3>Compensation</h3>
      <p className="section-description">Set your salary expectations and range</p>

      <div className="form-grid">
        <div className="form-group">
          <label htmlFor="salary_expectation">Expected Annual Salary</label>
          <input
            type="text"
            id="salary_expectation"
            value={formData.salary_expectation || ''}
            onChange={(e) => handleChange('salary_expectation', e.target.value)}
            placeholder="85000"
          />
        </div>

        <div className="form-group">
          <label htmlFor="salary_currency">Currency</label>
          <select
            id="salary_currency"
            value={formData.salary_currency || 'USD'}
            onChange={(e) => handleChange('salary_currency', e.target.value)}
          >
            <option value="USD">USD - US Dollar</option>
            <option value="CAD">CAD - Canadian Dollar</option>
            <option value="EUR">EUR - Euro</option>
            <option value="GBP">GBP - British Pound</option>
            <option value="CNY">CNY - Chinese Yuan</option>
          </select>
        </div>

        <div className="form-group">
          <label htmlFor="salary_range_min">Salary Range - Minimum</label>
          <input
            type="text"
            id="salary_range_min"
            value={formData.salary_range_min || ''}
            onChange={(e) => handleChange('salary_range_min', e.target.value)}
            placeholder="80000"
          />
        </div>

        <div className="form-group">
          <label htmlFor="salary_range_max">Salary Range - Maximum</label>
          <input
            type="text"
            id="salary_range_max"
            value={formData.salary_range_max || ''}
            onChange={(e) => handleChange('salary_range_max', e.target.value)}
            placeholder="100000"
          />
        </div>

        <div className="form-group full-width">
          <label htmlFor="currency_conversion_note">Currency Conversion Note</label>
          <textarea
            id="currency_conversion_note"
            value={formData.currency_conversion_note || ''}
            onChange={(e) => handleChange('currency_conversion_note', e.target.value)}
            placeholder="Any special notes regarding currency conversion"
          />
        </div>
      </div>
    </div>
  )
}
