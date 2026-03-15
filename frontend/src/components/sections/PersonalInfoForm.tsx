import { PersonalInfo } from '../../api/client'
import { useFormData } from '../../hooks/useFormData'
import '../sections/SectionForm.css'

interface PersonalInfoFormProps {
  data: Partial<PersonalInfo>
  onChange: (data: Partial<PersonalInfo>) => void
}

export default function PersonalInfoForm({ data, onChange }: PersonalInfoFormProps) {
  const { formData, handleChange } = useFormData<PersonalInfo>(data, onChange)

  return (
    <div className="section-form">
      <h3>Personal Information</h3>
      <p className="section-description">Enter your basic contact information and online profiles</p>

      <div className="form-grid">
        <div className="form-group">
          <label htmlFor="full_name">Full Name *</label>
          <input
            type="text"
            id="full_name"
            value={formData.full_name || ''}
            onChange={(e) => handleChange('full_name', e.target.value)}
            placeholder="John Doe"
            required
          />
        </div>

        <div className="form-group">
          <label htmlFor="preferred_name">Preferred Name</label>
          <input
            type="text"
            id="preferred_name"
            value={formData.preferred_name || ''}
            onChange={(e) => handleChange('preferred_name', e.target.value)}
            placeholder="John"
          />
        </div>

        <div className="form-group">
          <label htmlFor="email">Email *</label>
          <input
            type="email"
            id="email"
            value={formData.email || ''}
            onChange={(e) => handleChange('email', e.target.value)}
            placeholder="john.doe@example.com"
            required
          />
        </div>

        <div className="form-group">
          <label htmlFor="phone">Phone</label>
          <input
            type="tel"
            id="phone"
            value={formData.phone || ''}
            onChange={(e) => handleChange('phone', e.target.value)}
            placeholder="+1 (555) 123-4567"
          />
        </div>

        <div className="form-group">
          <label htmlFor="address">Street Address</label>
          <input
            type="text"
            id="address"
            value={formData.address || ''}
            onChange={(e) => handleChange('address', e.target.value)}
            placeholder="123 Main St"
          />
        </div>

        <div className="form-group">
          <label htmlFor="city">City *</label>
          <input
            type="text"
            id="city"
            value={formData.city || ''}
            onChange={(e) => handleChange('city', e.target.value)}
            placeholder="New York"
            required
          />
        </div>

        <div className="form-group">
          <label htmlFor="province_state">Province/State</label>
          <input
            type="text"
            id="province_state"
            value={formData.province_state || ''}
            onChange={(e) => handleChange('province_state', e.target.value)}
            placeholder="New York / Ontario"
          />
        </div>

        <div className="form-group">
          <label htmlFor="country">Country *</label>
          <input
            type="text"
            id="country"
            value={formData.country || ''}
            onChange={(e) => handleChange('country', e.target.value)}
            placeholder="United States"
            required
          />
        </div>

        <div className="form-group">
          <label htmlFor="postal_code">Postal/ZIP Code</label>
          <input
            type="text"
            id="postal_code"
            value={formData.postal_code || ''}
            onChange={(e) => handleChange('postal_code', e.target.value)}
            placeholder="10001 / A1B 2C3"
          />
        </div>

        <div className="form-group">
          <label htmlFor="linkedin_url">LinkedIn URL</label>
          <input
            type="url"
            id="linkedin_url"
            value={formData.linkedin_url || ''}
            onChange={(e) => handleChange('linkedin_url', e.target.value)}
            placeholder="https://www.linkedin.com/in/yourprofile"
          />
        </div>

        <div className="form-group">
          <label htmlFor="github_url">GitHub URL</label>
          <input
            type="url"
            id="github_url"
            value={formData.github_url || ''}
            onChange={(e) => handleChange('github_url', e.target.value)}
            placeholder="https://github.com/yourusername"
          />
        </div>

        <div className="form-group">
          <label htmlFor="portfolio_url">Portfolio URL</label>
          <input
            type="url"
            id="portfolio_url"
            value={formData.portfolio_url || ''}
            onChange={(e) => handleChange('portfolio_url', e.target.value)}
            placeholder="https://yourportfolio.com"
          />
        </div>

        <div className="form-group">
          <label htmlFor="website_url">Personal Website URL</label>
          <input
            type="url"
            id="website_url"
            value={formData.website_url || ''}
            onChange={(e) => handleChange('website_url', e.target.value)}
            placeholder="https://yourwebsite.com"
          />
        </div>

        <div className="form-group full-width">
          <label htmlFor="password">Job Site Password</label>
          <input
            type="password"
            id="password"
            value={formData.password || ''}
            onChange={(e) => handleChange('password', e.target.value)}
            placeholder="Used for login during auto-apply"
          />
          <small>This password is used for automatic form filling on job sites that require login</small>
        </div>
      </div>
    </div>
  )
}
