"""Original, simple line pictograms (no photos, no logos, no real people) chosen by syllabus topic."""
from markupsafe import Markup

ICONS = {
 "audio": '<path d="M4 14v-2a8 8 0 0 1 16 0v2M4 14h3v6H5a1 1 0 0 1-1-1zM20 14h-3v6h2a1 1 0 0 0 1-1z"/>',
 "scales": '<path d="M12 3v18M6 21h12M5 7h14M5 7l-3 7a3 3 0 0 0 6 0L5 7zM19 7l-3 7a3 3 0 0 0 6 0l-3-7z"/>',
 "parliament": '<path d="M3 21h18M5 21V10M9 21V10M15 21V10M19 21V10M2 10l10-6 10 6z"/>',
 "chart": '<path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/>',
 "leaf": '<path d="M5 19c0-9 5-14 15-14 0 10-5 15-15 14zM5 19l8-8"/>',
 "shield": '<path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z"/>',
 "chip": '<rect x="7" y="7" width="10" height="10"/><path d="M9 3v4M15 3v4M9 17v4M15 17v4M3 9h4M3 15h4M17 9h4M17 15h4"/>',
 "globe": '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c3 3 3 15 0 18M12 3c-3 3-3 15 0 18"/>',
 "people": '<circle cx="9" cy="8" r="3"/><circle cx="17" cy="9" r="2.5"/><path d="M3 20c0-4 3-6 6-6s6 2 6 6M15 14c3 0 6 2 6 6"/>',
 "health": '<path d="M9 3h6v6h6v6h-6v6H9v-6H3V9h6z"/>',
 "wheat": '<path d="M12 21V8M12 8c-3 0-4-2-4-4 3 0 4 2 4 4zM12 8c3 0 4-2 4-4-3 0-4 2-4 4zM12 14c-3 0-4-2-4-4 3 0 4 2 4 4zM12 14c3 0 4-2 4-4-3 0-4 2-4 4z"/>',
 "temple": '<path d="M3 21h18M5 21v-7h14v7M12 3l8 6H4zM9 21v-4h6v4"/>',
 "book": '<path d="M4 5a2 2 0 0 1 2-2h13v16H6a2 2 0 0 0-2 2zM4 19h15"/>',
 "doc": '<path d="M6 3h9l4 4v14H6zM14 3v5h5M9 13h7M9 17h7"/>',
 "compass": '<circle cx="12" cy="12" r="9"/><path d="M15.5 8.5l-2 5-5 2 2-5z"/>',
 "waves": '<path d="M2 14c3-3 5 3 8 0s5 3 8 0 3 1 4 0M2 19c3-3 5 3 8 0s5 3 8 0 3 1 4 0M12 3v6"/>',
 "news": '<path d="M4 5h13v14H6a2 2 0 0 1-2-2zM17 9h3v8a2 2 0 0 1-2 2M7 9h7M7 13h7"/>',
}
# first matching substring (lowercase topic name) wins
RULES = [
 ("disaster", "waves"), ("environment", "leaf"), ("agricultur", "wheat"), ("food", "wheat"), ("land reform", "wheat"),
 ("cyber", "shield"), ("security", "shield"), ("border", "shield"), ("science", "chip"), ("it, space", "chip"),
 ("budget", "chart"), ("economy", "chart"), ("inclusive", "chart"), ("liberalisation", "chart"),
 ("parliament", "parliament"), ("election", "parliament"), ("federal", "parliament"),
 ("separation", "scales"), ("constitution", "scales"), ("executive", "parliament"), ("ethic", "scales"),
 ("probity", "scales"), ("attitude", "people"), ("emotional", "people"), ("aptitude", "people"), ("case stud", "doc"),
 ("neighbour", "globe"), ("bilateral", "globe"), ("international", "globe"), ("policies of other", "globe"),
 ("health", "health"), ("poverty and hunger", "wheat"), ("welfare", "people"), ("women", "people"),
 ("population", "people"), ("society", "people"), ("social empowerment", "people"), ("globalisation", "globe"),
 ("governance", "doc"), ("civil service", "doc"), ("government policies", "doc"), ("regulatory", "doc"),
 ("heritage", "temple"), ("history", "book"), ("freedom", "book"), ("post-independence", "book"),
 ("geograph", "compass"), ("geophysical", "compass"), ("natural resources", "compass"),
]


def icon(topic_name, size=40):
    t = (topic_name or "").lower()
    key = next((k for sub, k in RULES if sub in t), "news")
    return Markup(f'<svg class="ico" width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
                  f'stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{ICONS[key]}</svg>')


def icon_key(key, size=18):
    return Markup(f'<svg class="ico" width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
                  f'stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{ICONS.get(key, ICONS["news"])}</svg>')
