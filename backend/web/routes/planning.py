"""Planning HTTP endpoints."""
from fastapi import APIRouter
from fastapi import Depends
from backend.services import budget as service
from backend.web.auth import get_user
from backend.persistence.database import get_db
from backend.core.schemas import NewDebt, DebtPayment, NewGoal, GoalProgress, SetArchived
from backend.services import management

router = APIRouter(tags=["planning"])

@router.get('/api/debts')
def debts(include_archived: bool = False, user=Depends(get_user), db=Depends(get_db)):
    return service.debts(db, user.id, include_archived=include_archived)


@router.post('/api/debts', status_code=201)
def create_debt(data: NewDebt, user=Depends(get_user), db=Depends(get_db)):
    return {'id': service.create_debt(db, user.id, data)}


@router.post('/api/debts/{debt_id}/payments', status_code=201)
def repay_debt(debt_id: int, data: DebtPayment, user=Depends(get_user), db=Depends(get_db)):
    return {'entry_id': service.repay_debt(db, user.id, debt_id, data)}


@router.get('/api/goals')
def goals(include_archived: bool = False, user=Depends(get_user), db=Depends(get_db)):
    return service.goals(db, user.id, include_archived=include_archived)


@router.post('/api/goals', status_code=201)
def create_goal(data: NewGoal, user=Depends(get_user), db=Depends(get_db)):
    return {'id': service.create_goal(db, user.id, data)}


@router.post('/api/goals/{goal_id}/progress')
def update_goal(goal_id: int, data: GoalProgress, user=Depends(get_user), db=Depends(get_db)):
    service.update_goal(db, user.id, goal_id, data)
    return {'ok': True}


@router.post('/api/debts/{debt_id}/edit')
def edit_debt(debt_id: int, data: NewDebt, user=Depends(get_user), db=Depends(get_db)):
    management.edit_debt(db, user.id, debt_id, data)
    return {'ok': True}


@router.post('/api/debts/{debt_id}/archive')
def archive_debt(debt_id: int, data: SetArchived, user=Depends(get_user), db=Depends(get_db)):
    from backend.persistence.models import Debt
    management.archive_planning(db, user.id, Debt, debt_id, data.archived)
    return {'ok': True}


@router.post('/api/goals/{goal_id}/edit')
def edit_goal(goal_id: int, data: NewGoal, user=Depends(get_user), db=Depends(get_db)):
    management.edit_goal(db, user.id, goal_id, data)
    return {'ok': True}


@router.post('/api/goals/{goal_id}/archive')
def archive_goal(goal_id: int, data: SetArchived, user=Depends(get_user), db=Depends(get_db)):
    from backend.persistence.models import Goal
    management.archive_planning(db, user.id, Goal, goal_id, data.archived)
    return {'ok': True}

