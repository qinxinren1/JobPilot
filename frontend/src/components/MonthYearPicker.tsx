import DatePicker from 'react-datepicker'
import 'react-datepicker/dist/react-datepicker.css'
import './MonthYearPicker.css'

interface MonthYearPickerProps {
  value: string // Format: "YYYY-MM"
  onChange: (value: string) => void
  disabled?: boolean
  required?: boolean
  placeholder?: string
}

export default function MonthYearPicker({
  value,
  onChange,
  disabled = false,
  required = false,
  placeholder = 'Select month and year'
}: MonthYearPickerProps) {
  // Convert "YYYY-MM" string to Date object (first day of the month)
  const dateValue = value ? new Date(value + '-01') : null

  const handleDateChange = (date: Date | null) => {
    if (date) {
      const year = date.getFullYear()
      const month = String(date.getMonth() + 1).padStart(2, '0')
      onChange(`${year}-${month}`)
    } else {
      onChange('')
    }
  }

  return (
    <DatePicker
      selected={dateValue}
      onChange={handleDateChange}
      dateFormat="MMMM yyyy"
      showMonthYearPicker
      disabled={disabled}
      required={required}
      placeholderText={placeholder}
      className="month-year-picker"
      wrapperClassName="month-year-picker-wrapper"
    />
  )
}
