import { EEOVoluntary } from '../../api/client'
import { useFormData } from '../../hooks/useFormData'
import './SectionForm.css'

interface EEOVoluntaryFormProps {
  data: Partial<EEOVoluntary>
  onChange: (data: Partial<EEOVoluntary>) => void
}

const EEO_OPTIONS = {
  gender: [
    'Decline to self-identify',
    'Male',
    'Female',
    'Non-binary',
    'Prefer not to say',
  ],
  race_ethnicity: [
    'Decline to self-identify',
    'American Indian or Alaska Native',
    'Asian',
    'Black or African American',
    'Hispanic or Latino',
    'Native Hawaiian or Other Pacific Islander',
    'White',
    'Two or more races',
    'Prefer not to say',
  ],
  veteran_status: [
    'I am not a protected veteran',
    'I am a protected veteran',
    'Decline to self-identify',
  ],
  disability_status: [
    'I do not wish to answer',
    'Yes, I have a disability',
    'No, I do not have a disability',
    'Decline to self-identify',
  ],
}

export default function EEOVoluntaryForm({ data, onChange }: EEOVoluntaryFormProps) {
  const { formData, handleChange } = useFormData<EEOVoluntary>(data, onChange)

  return (
    <div className="section-form">
      <h3>EEO Voluntary Information</h3>
      <p className="section-description">
        This information is voluntarily provided for EEO (Equal Employment Opportunity) reporting. You may choose not to answer.
      </p>

      <div className="form-grid">
        <div className="form-group full-width">
          <label htmlFor="gender">Gender</label>
          <select
            id="gender"
            value={formData.gender || 'Decline to self-identify'}
            onChange={(e) => handleChange('gender', e.target.value)}
          >
            {EEO_OPTIONS.gender.map((option) => (
              <option key={option} value={option}>
                {option}
              </option>
            ))}
          </select>
        </div>

        <div className="form-group full-width">
          <label htmlFor="race_ethnicity">Race/Ethnicity</label>
          <select
            id="race_ethnicity"
            value={formData.race_ethnicity || 'Decline to self-identify'}
            onChange={(e) => handleChange('race_ethnicity', e.target.value)}
          >
            {EEO_OPTIONS.race_ethnicity.map((option) => (
              <option key={option} value={option}>
                {option}
              </option>
            ))}
          </select>
        </div>

        <div className="form-group full-width">
          <label htmlFor="veteran_status">Veteran Status</label>
          <select
            id="veteran_status"
            value={formData.veteran_status || 'I am not a protected veteran'}
            onChange={(e) => handleChange('veteran_status', e.target.value)}
          >
            {EEO_OPTIONS.veteran_status.map((option) => (
              <option key={option} value={option}>
                {option}
              </option>
            ))}
          </select>
        </div>

        <div className="form-group full-width">
          <label htmlFor="disability_status">Disability Status</label>
          <select
            id="disability_status"
            value={formData.disability_status || 'I do not wish to answer'}
            onChange={(e) => handleChange('disability_status', e.target.value)}
          >
            {EEO_OPTIONS.disability_status.map((option) => (
              <option key={option} value={option}>
                {option}
              </option>
            ))}
          </select>
        </div>
      </div>
    </div>
  )
}
