"""Input sanitization helpers.

Every public function takes a raw input string and returns a safely
cleaned version. Sanitization is distinct from validation: a sanitizer
attempts to salvage input by removing dangerous parts, while a validator
rejects invalid input outright.
"""

import html as _html
import os
import re

from utils.security.constants import MAX_FILE_NAME_LENGTH, SAFE_FILENAME_PATTERN, HTML_TAG_PATTERN


def sanitize_html(text: str) -> str:
    """Strip HTML tags and escape special characters.

    This is a two-pass sanitizer:
    1. Remove anything that looks like an HTML tag (``<...>``).
    2. Escape the remaining ``&``, ``<``, ``>``, ``"``, ``'`` characters.

    Args:
        text: The raw user-supplied text.

    Returns:
        A plain-text string safe for inclusion in HTML output.
    """
    if not text:
        return ""
    no_tags = HTML_TAG_PATTERN.sub("", text)
    return _html.escape(no_tags, quote=True)


def sanitize_filename(filename: str) -> str:
    """Sanitize a filename to prevent path-traversal attacks while preserving Unicode/Arabic names.

    Removes directory separators and dangerous OS characters. Preserves Arabic,
    Unicode characters, spaces, hyphens, underscores, and file extensions.

    Args:
        filename: The raw filename (may include full path).

    Returns:
        A safe filename string.
    """
    if not filename:
        return "document"

    safe = os.path.basename(filename).strip()
    # Strip directory traversal, control chars, and forbidden filesystem characters
    safe = re.sub(r'[\r\n\t\x00-\x1f\\/*?:"<>|]', '_', safe)
    safe = re.sub(r'\.{2,}', '.', safe)  # collapse multiple dots
    safe = safe.lstrip('. ')

    root, ext = os.path.splitext(safe)
    if not root:
        root = "document"

    if len(root) > 100:
        root = root[:100]

    return f"{root}{ext.lower()}"



def sanitize_display_text(text: str) -> str:
    """Sanitize text for safe display in the user interface.

    Currently an alias for :func:`sanitize_html`.  This function exists
    so that display-specific policies (e.g. allowing limited markdown)
    can be added in one place later.

    Args:
        text: The raw user-supplied text.

    Returns:
        A plain-text string safe for display.
    """
    return sanitize_html(text)
