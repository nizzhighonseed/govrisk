"""Plain-text guard for assistant/AI replies.

The frontend renders every assistant reply as React text (never as raw
HTML), so the client is the primary trust boundary. This module is an
explicit defense-in-depth measure applied to *user-controlled* strings
(project names, states, sectors, AI-derived titles) at the exact point
where they are interpolated into server-generated replies: the backend
must never be able to emit attacker markup that some future HTML renderer
could execute.

It deliberately does NOT HTML-escape (e.g. turn `<` into `&lt;`): the
frontend renders text nodes, so escaping would show the entity literally
(double-encoding). Stripping angle-bracket tag syntax neutralises markup
while preserving the visible text, so normal names, bold markers and
line breaks are untouched.
"""

import re

_TAG_PATTERN = re.compile(r"<[^>]*>")


def strip_html_tags(value) -> str:
    """Return ``value`` as text with HTML tag syntax removed.

    Only angle-bracket tag syntax is removed; everything else (including
    characters such as ``&``, ``"`` and ``{``) is preserved verbatim so
    legitimate text is never altered and content is never double-escaped.
    """
    text = "" if value is None else str(value)
    return _TAG_PATTERN.sub("", text)