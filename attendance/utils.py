"""Shared day-cell status vocabulary for attendance calendars.

Used by both the console (admin/PM) monthly grids and the employee
portal's own monthly view so the icon for a given status is identical
everywhere it appears.
"""

CELL_ICONS = {
    "present": "fa-check",
    "absent": "fa-xmark",
    "leave": "fa-plane-departure",
    "weekend": "fa-umbrella-beach",
    "future": "fa-minus",
}

CELL_LABELS = {
    "present": "Present",
    "absent": "Absent",
    "leave": "On Leave",
    "weekend": "Weekend",
    "future": "Upcoming",
}
