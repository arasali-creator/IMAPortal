from django import template
from django.utils.html import format_html


register = template.Library()


@register.filter
def get_item(value, key):
    if isinstance(value, dict):
        return value.get(key)
    return None


@register.filter
def label_with_required(bound_field):
    if not bound_field:
        return ""
    label = bound_field.label or ""
    required = bound_field.field.required
    if required:
        return format_html(
            '<label for="{}" class="required">{} <span class="req-star">*</span></label>',
            bound_field.id_for_label,
            label,
        )
    return format_html('<label for="{}">{}</label>', bound_field.id_for_label, label)
