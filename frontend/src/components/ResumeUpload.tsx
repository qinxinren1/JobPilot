import { useState } from 'react'
import { apiClient } from '../api/client'
import { Profile } from '../api/client'
import './ResumeUpload.css'

interface ResumeUploadProps {
  onDataExtracted: (data: Partial<Profile>) => void
  onClose: () => void
}

export default function ResumeUpload({ onDataExtracted, onClose }: ResumeUploadProps) {
  const [file, setFile] = useState<File | null>(null)
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [preview, setPreview] = useState<string | null>(null)

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const selectedFile = e.target.files?.[0]
    if (selectedFile) {
      if (selectedFile.size > 10 * 1024 * 1024) {
        setError('File size must be less than 10MB')
        return
      }
      setFile(selectedFile)
      setError(null)
      
      // Preview text files
      if (selectedFile.type === 'text/plain') {
        const reader = new FileReader()
        reader.onload = (e) => {
          setPreview(e.target?.result as string)
        }
        reader.readAsText(selectedFile)
      } else {
        setPreview(null)
      }
    }
  }

  const handleUpload = async () => {
    if (!file) {
      setError('Please select a file')
      return
    }

    setUploading(true)
    setError(null)

    try {
      const formData = new FormData()
      formData.append('file', file)

      const response = await apiClient.post('/api/resume/upload', formData, {
        headers: {
          'Content-Type': 'multipart/form-data',
        },
      })

      const { merged_data, extracted_data } = response.data

      // Use merged_data (already merged by backend) instead of extracted_data
      // This ensures all existing data is preserved
      onDataExtracted(merged_data || extracted_data)
      
      alert('Resume uploaded and parsed successfully! The profile has been updated with merged data.')
      onClose()
    } catch (err: any) {
      setError(err.response?.data?.detail || err.message || 'Failed to upload resume')
    } finally {
      setUploading(false)
    }
  }

  return (
    <div className="resume-upload-overlay" onClick={onClose}>
      <div className="resume-upload-modal" onClick={(e) => e.stopPropagation()}>
        <div className="resume-upload-header">
          <h3>Upload Resume</h3>
          <button className="close-button" onClick={onClose}>×</button>
        </div>

        <div className="resume-upload-content">
          <div className="upload-section">
            <label htmlFor="resume-file" className="upload-label">
              <div className="upload-area">
                {file ? (
                  <div className="file-selected">
                    <span className="file-icon">📄</span>
                    <span className="file-name">{file.name}</span>
                    <span className="file-size">
                      {(file.size / 1024).toFixed(1)} KB
                    </span>
                  </div>
                ) : (
                  <div className="upload-placeholder">
                    <span className="upload-icon">📤</span>
                    <p>Click to select or drag and drop</p>
                    <p className="upload-hint">PDF or TXT files up to 10MB</p>
                  </div>
                )}
              </div>
              <input
                id="resume-file"
                type="file"
                accept=".pdf,.txt"
                onChange={handleFileChange}
                className="file-input"
              />
            </label>
          </div>

          {preview && (
            <div className="preview-section">
              <h4>Preview (first 500 characters):</h4>
              <div className="preview-text">
                {preview.substring(0, 500)}
                {preview.length > 500 && '...'}
              </div>
            </div>
          )}

          <div className="info-section">
            <small className="info-hint">
              💡 Resume will be parsed using AI (LLM) to extract structured information.
            </small>
          </div>

          {error && (
            <div className="error-message">
              {error}
            </div>
          )}

          <div className="upload-actions">
            <button
              className="cancel-button"
              onClick={onClose}
              disabled={uploading}
            >
              Cancel
            </button>
            <button
              className="upload-button"
              onClick={handleUpload}
              disabled={!file || uploading}
            >
              {uploading ? 'Uploading...' : 'Upload & Parse'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
