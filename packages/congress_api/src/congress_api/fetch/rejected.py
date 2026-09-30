"""Compatibility import; rejected-page retention belongs to production."""
from congress_api.retention.rejected_pages import retain_rejected_page

__all__ = ["retain_rejected_page"]
