"""Savings HTTP endpoints."""
from fastapi import APIRouter
from fastapi import Depends
from backend.services import budget as service
from backend.web.auth import get_user
from backend.persistence.database import get_db
from backend.core.schemas import NewSavingsRule, SetEnabled, SavingsMove, SetArchived
from backend.services import management

router = APIRouter(tags=["savings"])

@router.get("/api/savings")
def savings(user=Depends(get_user), db=Depends(get_db)):
    return service.savings(db, user.id)


@router.get('/api/savings/rules')
def savings_rules(include_archived: bool = False, user=Depends(get_user), db=Depends(get_db)):
    return service.savings_rules(db, user.id, include_archived=include_archived)


@router.post('/api/savings/rules', status_code=201)
def create_savings_rule(data: NewSavingsRule, user=Depends(get_user), db=Depends(get_db)):
    return {'id': service.create_savings_rule(db, user.id, data)}


@router.post('/api/savings/rules/{rule_id}')
def toggle_savings_rule(rule_id: int, data: SetEnabled, user=Depends(get_user), db=Depends(get_db)):
    service.set_savings_rule(db, user.id, rule_id, data.enabled)
    return {'ok': True}


@router.post('/api/savings/move', status_code=201)
def move_savings(data: SavingsMove, user=Depends(get_user), db=Depends(get_db)):
    return {'operation_id': service.move_savings(db, user.id, data)}


@router.post('/api/savings/rules/{rule_id}/edit')
def edit_savings_rule(rule_id: int, data: NewSavingsRule, user=Depends(get_user), db=Depends(get_db)):
    management.edit_rule(db, user.id, rule_id, data)
    return {'ok': True}


@router.post('/api/savings/rules/{rule_id}/archive')
def archive_savings_rule(rule_id: int, data: SetArchived, user=Depends(get_user), db=Depends(get_db)):
    management.archive_rule(db, user.id, rule_id, data.archived)
    return {'ok': True}

