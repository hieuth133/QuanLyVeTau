"""Template filter dùng chung cho giao diện."""
from decimal import Decimal, InvalidOperation

from django import template
from django.utils.safestring import mark_safe

register = template.Library()


@register.filter
def vnd(value):
    """Định dạng tiền Việt Nam: 450000 -> '450.000 đ'."""
    if value is None or value == "":
        return "—"
    try:
        so = int(Decimal(value).quantize(Decimal(1)))
    except (InvalidOperation, ValueError, TypeError):
        return value
    return f"{so:,}".replace(",", ".") + " đ"


@register.filter
def bs(field, extra=""):
    """Hiển thị trường form với class Bootstrap (form-control / form-select / form-check-input)."""
    widget = field.field.widget
    input_type = getattr(widget, "input_type", "")
    if input_type == "checkbox":
        css = "form-check-input"
    elif input_type == "select":
        css = "form-select"
    else:
        css = "form-control"
    if field.errors:
        css += " is-invalid"
    if extra:
        css += " " + extra
    attrs = dict(widget.attrs)
    attrs["class"] = (attrs.get("class", "") + " " + css).strip()
    return mark_safe(field.as_widget(attrs=attrs))


@register.filter
def phan_tram(value):
    """Giá trị giảm: bỏ phần thập phân thừa (10.00 -> 10)."""
    try:
        return format(Decimal(value).normalize(), "f")
    except (InvalidOperation, TypeError, ValueError):
        return value


@register.filter
def lay(mapping, key):
    try:
        return mapping.get(key)
    except AttributeError:
        return None
