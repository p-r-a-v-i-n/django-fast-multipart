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

html_theme = "alabaster"
html_title = f"django-fast-multipart {release}"
html_theme_options = {
    "description": "Rust-backed multipart parsing for Django",
    "github_button": True,
    "github_repo": "django-fast-multipart",
    "github_user": "p-r-a-v-i-n",
}
