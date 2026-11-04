"""HTML sanitizing for rich text produced by the Quill editor."""
import nh3

ALLOWED_TAGS = {
    'p', 'br', 'strong', 'em', 'u', 's', 'blockquote', 'pre', 'code',
    'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'ol', 'ul', 'li', 'a', 'img',
    'span', 'sub', 'sup',
}

# Quill formats with ``ql-*`` classes (alignment, indent, font...), so ``class`` is
# allowed on block elements. ``rel`` is not listed for <a>: nh3 sets it via ``link_rel``.
_CLASS_TAGS = ('p', 'span', 'li', 'ol', 'ul', 'pre', 'blockquote', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6')
ALLOWED_ATTRIBUTES = {
    **{tag: {'class'} for tag in _CLASS_TAGS},
    'a': {'href', 'target'},
    'img': {'src', 'alt', 'width', 'height'},
    'li': {'class', 'data-list'},
}

ALLOWED_URL_SCHEMES = {'http', 'https', 'mailto'}


def _url_filter(tag, attr, value):
    """Allow absolute http(s)/mailto URLs and site-root paths; drop protocol-relative ones."""
    if attr not in ('href', 'src'):
        return value
    url = value.strip()
    if url.startswith('/'):
        return None if url.startswith(('//', '/\\')) else value
    if url.lower().startswith(('http://', 'https://', 'mailto:')):
        return value
    return None


def clean_html(html: str) -> str:
    """Return ``html`` reduced to the allowlist; safe to render with ``|safe``."""
    return nh3.clean(
        html or '',
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRIBUTES,
        url_schemes=ALLOWED_URL_SCHEMES,
        attribute_filter=_url_filter,
        link_rel='noopener noreferrer',
    )


def sanitize_queryset(qs) -> int:
    """Re-sanitize ``contenido`` of every row in ``qs``; return how many rows changed."""
    changed = 0
    for pk, contenido in qs.values_list('pk', 'contenido').iterator():
        cleaned = clean_html(contenido)
        if cleaned != contenido:
            # update() skips save() side effects such as the updatedat timestamp.
            qs.model.objects.filter(pk=pk).update(contenido=cleaned)
            changed += 1
    return changed
