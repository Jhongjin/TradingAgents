"""Vertical shorts built from the site's own record.

The channel's promise is that a prediction is published before its result and
the result is published whichever way it went. That only survives if making a
video costs nothing, so the cut is generated from the same payload the site
renders, and no step of it waits on a person.
"""

from .render import Rendered, render, write_caption, write_poster
from .stories import STORIES, Storyboard, build

__all__ = ["Rendered", "STORIES", "Storyboard", "build", "render", "write_caption", "write_poster"]
