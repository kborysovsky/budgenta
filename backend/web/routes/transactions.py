"""Transactions HTTP endpoints."""
from fastapi import APIRouter
from fastapi import Depends
from backend.services import budget as service
from backend.services import exchanges
from backend.services import categories
from backend.web.auth import get_user
from backend.persistence.database import get_db
from backend.core.schemas import NewEntry, Transfer, Exchange, CloseMonth

router = APIRouter(tags=["transactions"])

@router.get('/api/categories')
def category_choices(user=Depends(get_user), db=Depends(get_db)):
    return categories.choices(db, user.id)

@router.post("/api/entries", status_code=201)
def add_entry(data: NewEntry, user=Depends(get_user), db=Depends(get_db)):
    return {"id": service.add_entry(db, user.id, data)}


@router.post("/api/transfers", status_code=201)
def transfer(data: Transfer, user=Depends(get_user), db=Depends(get_db)):
    service.transfer(db, user.id, data)
    return {"ok": True}


@router.get("/api/months/{month}")
def monthly(month: str, user=Depends(get_user), db=Depends(get_db)):
    return service.monthly(db, user.id, month)


@router.post('/api/exchanges/preview')
def preview_exchange(data: Exchange, user=Depends(get_user), db=Depends(get_db)):
    return exchanges.preview(db, user.id, data)


@router.post('/api/exchanges', status_code=201)
def exchange(data: Exchange, user=Depends(get_user), db=Depends(get_db)):
    return exchanges.exchange(db, user.id, data)


@router.post("/api/months/close")
def close_month(data: CloseMonth, user=Depends(get_user), db=Depends(get_db)):
    return service.close_month(db, user.id, data.month)


@router.post('/api/entries/{entry_id}/delete')
def delete_entry(entry_id: int, user=Depends(get_user), db=Depends(get_db)):
    service.delete_transaction(db, user.id, entry_id)
    return {'ok': True}
