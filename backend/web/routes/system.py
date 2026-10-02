"""System HTTP endpoints."""
from fastapi import APIRouter
import os
from backend.services import budget as service

router = APIRouter(tags=["system"])

@router.get("/api/config")
def config():
    return {"currencies": service.CURRENCIES, "expense_categories": service.EXPENSE_CATEGORIES, "telegram_username": os.getenv("TELEGRAM_BOT_USERNAME", "")}

