"""Book categories and their 'cloth binding' colours, used for spines, chips and charts."""

CATEGORY_COLORS = {
    "Programming": "#24406B",
    "Artificial Intelligence": "#1F6A70",
    "Data Science": "#3F4E63",
    "Mathematics": "#5B3A6B",
    "Science": "#2F5D46",
    "Finance & Economics": "#8A6418",
    "Fiction": "#7A2E2E",
    "History": "#8E4A26",
    "Biography": "#5E5E26",
    "Self-Help": "#94475B",
}

CATEGORIES = list(CATEGORY_COLORS)
FALLBACK_COLOR = "#4A5160"


def category_color(name):
    return CATEGORY_COLORS.get(name, FALLBACK_COLOR)
