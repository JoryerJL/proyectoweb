from django import template

register = template.Library()


@register.simple_tag(takes_context=True)
def absolute_url(context, path):
    """Absolute URL for ``path`` on the current host (canonical and Open Graph links)."""
    return context['request'].build_absolute_uri(path)
