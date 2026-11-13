"""Paginated lists (API contract, section 1.1).

    {"items": [...], "total": 14, "page": 1, "page_size": 8}

`page` starts at 1. Asking for a page past the end returns the last one, and the
response says which page it actually is.
"""

from pydantic import BaseModel

DEFAULT_PAGE_SIZE = 8
MAX_PAGE_SIZE = 500


class PageResponse[T](BaseModel):
    items: list[T]
    total: int
    page: int
    page_size: int
