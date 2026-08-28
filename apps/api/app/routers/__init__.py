"""API routers module."""

from app.routers.accounts import router as accounts_router
from app.routers.csv import router as csv_router
from app.routers.dashboard import router as dashboard_router
from app.routers.export import router as export_router
from app.routers.mappings import router as mappings_router
from app.routers.oms import router as oms_router
from app.routers.paypal import router as paypal_router
from app.routers.receipts import router as receipts_router
from app.routers.settings import router as settings_router
from app.routers.sources import router as sources_router
from app.routers.tags import router as tags_router
from app.routers.transactions import router as transactions_router

__all__ = [
    "accounts_router",
    "dashboard_router",
    "csv_router",
    "export_router",
    "mappings_router",
    "oms_router",
    "paypal_router",
    "receipts_router",
    "settings_router",
    "sources_router",
    "tags_router",
    "transactions_router",
]
