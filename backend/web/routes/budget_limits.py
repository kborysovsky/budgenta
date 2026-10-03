"""Authenticated, owner-scoped optional budget tracking."""
from fastapi import APIRouter, Depends
from backend.core.schemas import BudgetLimitInput, BudgetLimitSettings
from backend.persistence.database import get_db
from backend.web.auth import get_user
from backend.services import budget_limits

router = APIRouter(tags=['budget limits'])


@router.get('/api/budget-limits')
def overview(month: str | None = None, user=Depends(get_user), db=Depends(get_db)):
    return budget_limits.overview(db, user.id, month)


@router.post('/api/budget-limits/settings')
def settings(data: BudgetLimitSettings, user=Depends(get_user), db=Depends(get_db)):
    return budget_limits.save_settings(db, user.id, data)


@router.post('/api/budget-limits', status_code=201)
def create(data: BudgetLimitInput, user=Depends(get_user), db=Depends(get_db)):
    return budget_limits.save(db, user.id, data)


@router.post('/api/budget-limits/{identifier}/edit')
def edit(identifier: int, data: BudgetLimitInput, user=Depends(get_user), db=Depends(get_db)):
    return budget_limits.save(db, user.id, data, identifier)


@router.post('/api/budget-limits/{identifier}/delete')
def remove(identifier: int, user=Depends(get_user), db=Depends(get_db)):
    budget_limits.remove(db, user.id, identifier)
    return {'ok': True}


@router.post('/api/budget-limits/{identifier}/reset-alerts')
def reset(identifier: int, user=Depends(get_user), db=Depends(get_db)):
    return budget_limits.reset_alerts(db, user.id, identifier)
