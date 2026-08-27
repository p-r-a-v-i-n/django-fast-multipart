import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

with (ROOT / "pyproject.toml").open("rb") as file:
    release = tomllib.load(file)["project"]["version"]

project = "django-fast-multipart"
author = "Pravin"
copyright = "2026, Pravin"
version = release

extensions = []
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]
source_suffix = {".rst": "restructuredtext"}
root_doc = "index"

html_theme = "furo"
html_title = f"django-fast-multipart {release}"
html_theme_options = {
    "source_repository": "https://github.com/p-r-a-v-i-n/django-fast-multipart/",
    "source_branch": "main",
    "source_directory": "docs/",
    "light_css_variables": {
        "color-brand-primary": "#0c4b33",
        "color-brand-content": "#087f5b",
    },
    "dark_css_variables": {
        "color-brand-primary": "#44b78b",
        "color-brand-content": "#62d6a7",
    },
}
