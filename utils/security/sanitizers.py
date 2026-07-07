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
    """Sanitize a filename to prevent path-traversal attacks.

    Removes directory separators and restricts the result to alphanumeric
    characters, underscores, hyphens, and dots.  If the result is empty
    or too long the original basename is returned as a fallback (with
    path components removed).

    Args:
        filename: The raw filename (may include full path).

    Returns:
        A safe filename string.
    """
    if not filename:
        return "untitled"

    # Strip any leading path components
    safe = os.path.basename(filename)

    # Remove anything that isn't alphanumeric, underscore, hyphen, or dot
    safe = re.sub(r'[^a-zA-Z0-9_\-\.]', '', safe)

    # If sanitization emptied the name, fall back to basename stripped of paths
    if not safe:
        safe = re.sub(r'[^a-zA-Z0-9_\-\.]', '', os.path.basename(filename))

    # Truncate to maximum length while preserving extension
    if len(safe) > MAX_FILE_NAME_LENGTH:
        root, ext = os.path.splitext(safe)
        safe = root[:MAX_FILE_NAME_LENGTH - len(ext)] + ext

    return safe or "untitled"


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
