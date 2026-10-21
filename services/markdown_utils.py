import html
import re
import uuid

import bleach
import markdown
from markupsafe import Markup


MATH_DELIMITER_PATTERN = re.compile(
    r'(\$\$[\s\S]*?\$\$|\\\[[\s\S]*?\\\]|\\\([\s\S]*?\\\)|\$[^$\n]*\$)'
)
ALLOWED_MARKDOWN_TAGS = set(bleach.sanitizer.ALLOWED_TAGS) | {
    'blockquote', 'br', 'caption', 'dd', 'del', 'dl', 'dt', 'h1', 'h2', 'h3',
    'h4', 'h5', 'h6', 'hr', 'li', 'ol', 'p', 'pre', 'table', 'tbody', 'td',
    'tfoot', 'th', 'thead', 'tr', 'ul',
}


def render_markdown(value):
    """Render common Markdown formatting while sanitizing user-authored HTML."""
    if not value:
        return Markup('')

    math_expressions = []

    def protect_math(match):
        placeholder = f'EXAMMATH{uuid.uuid4().hex}TOKEN'
        math_expressions.append((placeholder, match.group(0)))
        return placeholder

    protected_value = MATH_DELIMITER_PATTERN.sub(protect_math, str(value))
    rendered = markdown.markdown(
        protected_value,
        extensions=['extra', 'sane_lists', 'nl2br'],
        output_format='html',
    )
    safe_html = bleach.clean(
        rendered,
        tags=ALLOWED_MARKDOWN_TAGS,
        attributes={
            'a': ['href', 'title'],
            'code': ['class'],
        },
        protocols={'http', 'https', 'mailto'},
        strip=True,
    )
    for placeholder, expression in math_expressions:
        safe_html = safe_html.replace(placeholder, html.escape(expression, quote=False))
    return Markup(safe_html)
