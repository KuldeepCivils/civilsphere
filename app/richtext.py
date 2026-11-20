"""Tiny safe formatter for AI notes: escape everything, then turn **key term** into bold. Nothing else is allowed through."""
import re

from markupsafe import Markup, escape


def rich(text):
    out = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", str(escape(text or "")))
    if out.startswith("\u2605"):  # a leading star marks the highest-yield point, like the star in handwritten notes
        out = '<span class="star">\u2605</span><span class="starred">' + out[1:].lstrip() + "</span>"
    return Markup(out)
