from django import template
from django.utils.safestring import mark_safe

from ..rendering import render_import_map, render_stylesheets

register = template.Library()


@register.simple_tag(name="pyesm_importmap")
def pyesm_importmap():
    """Render the ``<script type="importmap">…</script>`` tag (plus shims)."""
    return mark_safe(render_import_map())  # noqa: S308 - we control the content


@register.simple_tag(name="pyesm_stylesheets")
def pyesm_stylesheets():
    """Render the vendored ``<link rel="stylesheet">`` tags."""
    return mark_safe(render_stylesheets())  # noqa: S308 - we control the content
