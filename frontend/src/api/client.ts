import axios from 'axios'

const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

export const apiClient = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
  timeout: 120000, // 120 seconds timeout (2 minutes) for LinkedIn URL parsing
})

// Add request interceptor for debugging
apiClient.interceptors.request.use(
  (config) => {
    console.log(`[API Request] ${config.method?.toUpperCase()} ${config.url}`)
    return config
  },
  (error) => {
    console.error('[API Request Error]', error)
    return Promise.reject(error)
  }
)

// Add response interceptor for debugging
apiClient.interceptors.response.use(
  (response) => {
    console.log(`[API Response] ${response.config.method?.toUpperCase()} ${response.config.url}`, response.status)
    return response
  },
  (error) => {
    console.error('[API Response Error]', error.response?.status, error.response?.data || error.message)
    return Promise.reject(error)
  }
)

export interface TargetRole {
  name: string
  base_resume_path: string
  skills_emphasis?: string[]
  experience_filter?: string[]
  selected_work_experiences?: string[]  // For resume content selection
  selected_projects?: string[]  // For resume content selection
}

export interface Profile {
  personal?: PersonalInfo
  work_authorization?: WorkAuthorization
  availability?: Availability
  compensation?: Compensation
  experience?: Experience
  skills_boundary?: SkillsBoundary
  resume_facts?: ResumeFacts
  eeo_voluntary?: EEOVoluntary
  target_roles?: Record<string, TargetRole>
  [key: string]: unknown
}

export interface PersonalInfo {
  full_name: string
  preferred_name: string
  email: string
  password: string
  phone: string
  address: string
  city: string
  province_state: string
  country: string
  postal_code: string
  linkedin_url: string
  github_url: string
  portfolio_url: string
  website_url: string
}

export interface WorkAuthorization {
  legally_authorized_to_work: string | boolean
  require_sponsorship: string | boolean
  work_permit_type: string
}

export interface Availability {
  earliest_start_date: string
  available_for_full_time?: string | boolean
  available_for_contract?: string | boolean
}

export interface Compensation {
  salary_expectation: string
  salary_currency: string
  salary_range_min: string
  salary_range_max: string
  currency_conversion_note?: string
}

export interface WorkExperience {
  company: string
  title: string
  start_date: string
  end_date: string
  current: boolean
  location?: string
  description?: string
  bullets: string[]
}

export interface ProjectExperience {
  name: string
  description?: string
  tech_stack: string[]
  start_date: string
  end_date: string
  current: boolean
  bullets: string[]
  location?: string
  url?: string
}

export interface EducationExperience {
  school: string
  degree: string
  field?: string
  start_date: string
  end_date: string
  gpa?: string
  honors?: string[]
}

export interface AwardExperience {
  name: string
  category?: string
  issuer?: string
  date?: string
  description?: string
}

export interface Experience {
  years_of_experience_total: string
  education_level: string
  current_job_title?: string
  current_company?: string
  current_title?: string
  target_role: string
  work_experiences?: WorkExperience[]
  projects?: ProjectExperience[]
  education?: EducationExperience[]
  awards?: AwardExperience[]
}

export interface SkillsBoundary {
  // Technical Skills
  languages?: string[]
  programming_languages?: string[]
  frameworks?: string[]
  devops?: string[]
  databases?: string[]
  tools?: string[]
  // Soft Skills
  communication?: string[]
  leadership?: string[]
  problem_solving?: string[]
  teamwork?: string[]
  time_management?: string[]
  // Allow custom categories
  [key: string]: string[] | undefined
}

export interface ResumeFacts {
  preserved_companies: string[]
  preserved_projects: string[]
  preserved_schools: string[]
  preserved_awards: string[]
  real_metrics: string[]
  // Note: categories removed - use target_roles instead (unified category system)
}

export interface EEOVoluntary {
  gender: string
  race_ethnicity: string
  veteran_status: string
  disability_status: string
}

export interface Job {
  url: string
  title: string | null
  company: string | null
  salary: string | null
  description: string | null
  location: string | null
  site: string | null
  strategy: string | null
  discovered_at: string | null
  full_description: string | null
  application_url: string | null
  detail_scraped_at: string | null
  detail_error: string | null
  fit_score: number | null
  resume_score: number | null
  score_reasoning: string | null
  scored_at: string | null
  tailored_resume_path: string | null
  tailored_at: string | null
  tailor_attempts: number | null
  cover_letter_path: string | null
  cover_letter_at: string | null
  cover_attempts: number | null
  applied_at: string | null
  apply_status: string | null
  apply_error: string | null
  apply_attempts: number | null
  agent_id: string | null
  last_attempted_at: string | null
  apply_duration_ms: number | null
  apply_task_id: string | null
  verification_confidence: string | null
}

export const profileApi = {
  getProfile: async (): Promise<{ profile: Profile; exists: boolean }> => {
    const response = await apiClient.get('/api/profile')
    return response.data
  },

  updateProfile: async (profile: Profile): Promise<{ status: string; message: string }> => {
    const response = await apiClient.post('/api/profile', { profile })
    return response.data
  },

  getSection: async (sectionName: string): Promise<Record<string, unknown>> => {
    const response = await apiClient.get(`/api/profile/section/${sectionName}`)
    return response.data
  },

  updateSection: async (sectionName: string, sectionData: Record<string, unknown>): Promise<{ status: string; message: string }> => {
    const response = await apiClient.patch(`/api/profile/section/${sectionName}`, sectionData)
    return response.data
  },

  generateBaseResume: async (roleKey: string): Promise<{ status: string; message: string; path: string }> => {
    const response = await apiClient.post(`/api/profile/generate-base-resume`, { role_key: roleKey })
    return response.data
  },
}

export interface SearchQuery {
  query: string
  tier: number
}

export interface SearchLocation {
  location: string
  remote: boolean
}

export interface SearchDefaults {
  location: string
  distance: number
  hours_old?: number
  results_per_site?: number
  experience_level?: ('entry-level' | 'senior' | 'manager' | 'director' | 'executive')[]
}

export interface CoverLetterConfig {
  enabled: boolean
  min_score: number
  limit: number
  validation_mode: 'strict' | 'normal' | 'lenient'
  role_configs?: Record<string, Partial<CoverLetterConfig>>
}

export interface SearchConfig {
  // Legacy format support (for backward compatibility)
  location?: string
  distance?: number
  roles?: string[]
  
  // Full YAML structure
  defaults?: SearchDefaults
  locations?: SearchLocation[]
  queries?: SearchQuery[]
  cover_letter?: CoverLetterConfig
}

export interface InitStatus {
  resume: boolean
  profile: boolean
  search_config: boolean
  ai_configured: boolean
  tier: number
  tier_label: string
}

export interface InitResponse {
  status: string
  message: string
  tier: number
  tier_label: string
}

export const initApi = {
  initialize: async (
    resumeFile: File | null,
    profile: Profile,
    searchConfig: SearchConfig
  ): Promise<InitResponse> => {
    const formData = new FormData()
    if (resumeFile) {
      formData.append('resume_file', resumeFile)
    }
    formData.append('profile', JSON.stringify(profile))
    formData.append('search_config', JSON.stringify(searchConfig))

    const response = await apiClient.post('/api/init', formData, {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
    })
    return response.data
  },

  getStatus: async (): Promise<InitStatus> => {
    const response = await apiClient.get('/api/init/status')
    return response.data
  },
}

export const searchConfigApi = {
  getSearchConfig: async (): Promise<{ config: SearchConfig | null }> => {
    const response = await apiClient.get('/api/search-config')
    return response.data
  },

  updateSearchConfig: async (config: SearchConfig): Promise<{ status: string; message: string }> => {
    const response = await apiClient.post('/api/search-config', config)
    return response.data
  },
}

export interface PipelineRunRequest {
  stages?: string[]
  min_score?: number
  workers?: number
  stream?: boolean
  validation?: string
}

export interface PipelineRunResponse {
  status: string
  result: {
    stages: unknown[]
    errors: Record<string, unknown>
    elapsed: number
  }
}

export const pipelineApi = {
  runPipeline: async (request: PipelineRunRequest): Promise<PipelineRunResponse> => {
    const response = await apiClient.post('/api/pipeline/run', request)
    return response.data
  },
}

export interface ResumeTemplate {
  id: number
  name: string
  job_position: string | null
  job_type: string | null
  file_path: string
  pdf_path: string | null
  uploaded_at: string
  is_default: boolean
  file_size: number | null
  file_type: string
}

export interface GeneratedResumeResponse {
  status: string
  message: string
  role_category: string
  role_name: string
  pdf_path: string
  html_path: string
  txt_path: string | null
}

export const jobsApi = {
  getJobs: async (params?: {
    stage?: string
    min_score?: number
    limit?: number
    status?: string
    search?: string
  }): Promise<{ jobs: Job[]; count: number }> => {
    // Always use real API to fetch from database
    const response = await apiClient.get('/api/jobs', { params })
    return response.data
  },

  deleteJob: async (jobUrl: string): Promise<{ status: string; message: string }> => {
    // URL encode the job URL since it's used as a path parameter
    const encodedUrl = encodeURIComponent(jobUrl)
    const response = await apiClient.delete(`/api/jobs/${encodedUrl}`)
    return response.data
  },

  addJob: async (url: string, autoScore: boolean = false): Promise<{ 
    status: string
    message: string
    job_url: string
    new: boolean
    enriched?: boolean
    tailored?: boolean
    fit_score?: number
  }> => {
    // Use longer timeout for job URL parsing (may take up to 2 minutes)
    const response = await apiClient.post('/api/jobs/add', { 
      url,
      auto_score: autoScore
    }, {
      timeout: 120000, // 120 seconds
    })
    return response.data
  },

  // Deprecated: Use addJob instead
  addLinkedInJob: async (url: string): Promise<{ status: string; message: string; job_url: string; new: boolean }> => {
    const result = await jobsApi.addJob(url, false)
    return {
      status: result.status,
      message: result.message,
      job_url: result.job_url,
      new: result.new
    }
  },
}

export const resumesApi = {
  getResumes: async (): Promise<{ resumes: ResumeTemplate[] }> => {
    const response = await apiClient.get('/api/resumes')
    return response.data
  },

  uploadResume: async (
    file: File,
    name: string,
    jobPosition: string = '',
    jobType: string = '',
    isDefault: boolean = false
  ): Promise<{ status: string; message: string; resume: ResumeTemplate }> => {
    const formData = new FormData()
    formData.append('file', file)
    formData.append('name', name)
    if (jobPosition) formData.append('job_position', jobPosition)
    if (jobType) formData.append('job_type', jobType)
    formData.append('is_default', isDefault.toString())

    const response = await apiClient.post('/api/resumes/upload', formData, {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
    })
    return response.data
  },

  deleteResume: async (resumeId: number): Promise<{ status: string; message: string }> => {
    const response = await apiClient.delete(`/api/resumes/${resumeId}`)
    return response.data
  },

  setDefaultResume: async (resumeId: number): Promise<{ status: string; message: string }> => {
    const response = await apiClient.patch(`/api/resumes/${resumeId}/default`)
    return response.data
  },

  updateResume: async (
    resumeId: number,
    updates: {
      name?: string
      job_position?: string
      job_type?: string
    }
  ): Promise<{ status: string; message: string; resume: ResumeTemplate }> => {
    const response = await apiClient.patch(`/api/resumes/${resumeId}`, updates)
    return response.data
  },

  generateResumeFromProfile: async (
    name: string,
    jobPosition: string = '',
    jobType: string = '',
    isDefault: boolean = false,
    profileData?: Partial<Profile>, // Optional filtered profile
    roleCategory?: string  // Optional role category key
  ): Promise<GeneratedResumeResponse> => {
    // Unified backend endpoint (JSON): POST /api/resume/generate
    // Old endpoints (multipart form) are deprecated.
    void jobType
    void isDefault

    if (!roleCategory) {
      throw new Error('roleCategory is required to generate a resume')
    }

    const response = await apiClient.post('/api/resume/generate', {
      role_category: roleCategory,
      job_position: jobPosition || name || '',
      profile_data: profileData,
    })

    return response.data as GeneratedResumeResponse
  },
}

export interface CoverLetterTemplate {
  role_category: string
  content: string
}

export const coverLetterTemplatesApi = {
  getTemplates: async (): Promise<{ templates: CoverLetterTemplate[] }> => {
    const response = await apiClient.get('/api/cover-letters')
    return response.data
  },

  getTemplate: async (roleCategory: string): Promise<CoverLetterTemplate> => {
    const response = await apiClient.get(`/api/cover-letters/${encodeURIComponent(roleCategory)}`)
    return response.data
  },

  setTemplate: async (
    roleCategory: string,
    content: string
  ): Promise<{ status: string; message: string; role_category: string }> => {
    const response = await apiClient.put(`/api/cover-letters/${encodeURIComponent(roleCategory)}`, {
      content,
    })
    return response.data
  },

  deleteTemplate: async (roleCategory: string): Promise<{ status: string; message: string }> => {
    const response = await apiClient.delete(`/api/cover-letters/${encodeURIComponent(roleCategory)}`)
    return response.data
  },
}

export interface ApplyRequest {
  limit?: number
  workers?: number
  min_score?: number
  model?: string
  headless?: boolean
  dry_run?: boolean
  continuous?: boolean
  url?: string | null
  poll_interval?: number
}

export interface ApplyResponse {
  status: string
  message: string
  config: ApplyRequest
}

export interface WorkerStatus {
  worker_id: number
  status: string
  job_title: string
  company: string
  score: number
  actions: number
  last_action: string
  jobs_applied: number
  jobs_failed: number
  total_cost: number
}

export interface ApplyStatusResponse {
  status: string
  workers: WorkerStatus[]
  totals: {
    applied: number
    failed: number
    cost: number
  }
}

export const applyApi = {
  startApply: async (request: ApplyRequest): Promise<ApplyResponse> => {
    const response = await apiClient.post('/api/apply/start', request)
    return response.data
  },

  getApplyStatus: async (): Promise<ApplyStatusResponse> => {
    const response = await apiClient.get('/api/apply/status')
    return response.data
  },
}
