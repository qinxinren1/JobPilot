import { useState, useEffect } from 'react'

/**
 * Custom hook for managing form data state
 * 
 * @template T - The type of the form data object
 * @param initialData - Initial form data from props
 * @param onChange - Callback function to notify parent component of changes
 * @returns Object containing formData state and handleChange function
 * 
 * @example
 * ```tsx
 * const { formData, handleChange } = useFormData<PersonalInfo>(data, onChange)
 * 
 * <input
 *   value={formData.full_name || ''}
 *   onChange={(e) => handleChange('full_name', e.target.value)}
 * />
 * ```
 */
export function useFormData<T>(
  initialData: Partial<T>,
  onChange: (data: Partial<T>) => void
) {
  const [formData, setFormData] = useState<Partial<T>>(initialData)

  // Sync formData when initialData changes from parent
  useEffect(() => {
    setFormData(initialData)
  }, [initialData])

  /**
   * Handle field changes in the form
   * Updates local state and notifies parent component
   * 
   * @param field - The field name to update
   * @param value - The new value for the field
   */
  const handleChange = (field: keyof T, value: any) => {
    const updated = { ...formData, [field]: value }
    setFormData(updated)
    onChange(updated)
  }

  return { formData, handleChange }
}
