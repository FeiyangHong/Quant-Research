"""Optional provider adapters. Collection is not research-data admission."""

from .baostock import BaoStockAdapter, Query, normalize_history

__all__ = ["BaoStockAdapter", "Query", "normalize_history"]
