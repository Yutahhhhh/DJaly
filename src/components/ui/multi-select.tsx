import * as React from "react"
import { ChevronsUpDown, X, Sparkles } from "lucide-react"
import { cn } from "@/lib/utils"
import { Button } from "@/components/ui/button"
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover"
import { Badge } from "@/components/ui/badge"
import { Checkbox } from "@/components/ui/checkbox"
import { Input } from "@/components/ui/input"

export interface Option {
  label: string
  value: string
}

interface MultiSelectProps {
  options: Option[]
  selected: string[]
  onChange: (selected: string[]) => void
  placeholder?: string
  className?: string
  creatable?: boolean
  customPrefix?: string
  createLabel?: string
}

export function MultiSelect({
  options,
  selected,
  onChange,
  placeholder = "Select items...",
  className,
  creatable = false,
  customPrefix = "",
  createLabel = "Create",
}: MultiSelectProps) {
  const [open, setOpen] = React.useState(false)
  const [searchTerm, setSearchTerm] = React.useState("")

  const handleSelect = (value: string) => {
    if (selected.includes(value)) {
      onChange(selected.filter((item) => item !== value))
    } else {
      onChange([...selected, value])
    }
  }

  const handleRemove = (value: string, e: React.MouseEvent) => {
    e.stopPropagation()
    onChange(selected.filter((item) => item !== value))
  }

  const filteredOptions = options.filter((option) =>
    option.label.toLowerCase().includes(searchTerm.toLowerCase())
  )

  const isAllSelected = filteredOptions.length > 0 && filteredOptions.every((option) => selected.includes(option.value))

  const handleSelectAll = () => {
    if (isAllSelected) {
      const newSelected = selected.filter(
        (s) => !filteredOptions.some((o) => o.value === s)
      )
      onChange(newSelected)
    } else {
      const newValues = filteredOptions
        .map((o) => o.value)
        .filter((v) => !selected.includes(v))
      onChange([...selected, ...newValues])
    }
  }

  return (
    <Popover open={open} onOpenChange={setOpen} modal={true}>
      <PopoverTrigger asChild>
        <Button
          variant="outline"
          role="combobox"
          aria-expanded={open}
          className={cn("w-full justify-between h-auto min-h-10", className)}
        >
          <div className="flex gap-1 flex-wrap items-center text-left">
            {selected.length === 0 && <span className="text-muted-foreground">{placeholder}</span>}
            {selected.length > 0 && (
              selected.map((val) => {
                const isCustom = customPrefix && val.startsWith(customPrefix);
                const displayVal = isCustom ? val.slice(customPrefix.length) : val;
                const label = options.find((opt) => opt.value === val)?.label || displayVal;
                
                return (
                  <Badge variant="secondary" key={val} className="mr-1 pr-1 flex items-center gap-1">
                    {isCustom && <Sparkles className="h-3 w-3 opacity-70 mr-0.5" />}
                    {label}
                    <div
                      className="hover:bg-secondary-foreground/20 rounded-full p-0.5 cursor-pointer"
                      onClick={(e) => handleRemove(val, e)}
                    >
                      <X className="h-3 w-3" />
                    </div>
                  </Badge>
                )
              })
            )}
          </div>
          <ChevronsUpDown className="ml-2 h-4 w-4 shrink-0 opacity-50" />
        </Button>
      </PopoverTrigger>
      <PopoverContent 
        className="w-[var(--radix-popover-trigger-width)] p-0 z-[60]" 
        align="start"
      >
        <div className="p-2 border-b flex items-center gap-2">
          <Input
            placeholder="Search..."
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            className="h-8 flex-1"
          />
          <div className="flex items-center justify-center px-1" title="Select All / Deselect All">
            <Checkbox
              checked={isAllSelected}
              onCheckedChange={handleSelectAll}
            />
          </div>
        </div>
        <div 
            className="max-h-[300px] overflow-y-auto p-1"
            onWheel={(e) => e.stopPropagation()}
        >
            {creatable && searchTerm && (
                <div
                    className="flex items-center space-x-2 p-2 hover:bg-accent rounded-sm cursor-pointer border-b mb-1"
                    onClick={() => {
                        const newValue = customPrefix ? customPrefix + searchTerm : searchTerm;
                        handleSelect(newValue);
                        setSearchTerm("");
                    }}
                >
                    <span className="text-sm font-medium text-primary">
                        {createLabel} "{searchTerm}"
                    </span>
                </div>
            )}

            {filteredOptions.length === 0 && (!creatable || !searchTerm) && (
              <div className="p-2 text-sm text-muted-foreground text-center">
                No results found.
              </div>
            )}
            {filteredOptions.map((option) => (
                <div
                    key={option.value}
                    className="flex items-center space-x-2 p-2 hover:bg-accent rounded-sm cursor-pointer"
                    onClick={() => handleSelect(option.value)}
                >
                    <Checkbox 
                        checked={selected.includes(option.value)} 
                        onCheckedChange={() => handleSelect(option.value)}
                        id={`ms-${option.value}`}
                    />
                    <label 
                        htmlFor={`ms-${option.value}`}
                        className="text-sm cursor-pointer flex-1"
                        onClick={(e) => e.stopPropagation()}
                    >
                        {option.label}
                    </label>
                </div>
                ))}
        </div>
      </PopoverContent>
    </Popover>
  )
}
