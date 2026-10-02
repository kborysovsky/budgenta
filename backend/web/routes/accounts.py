"""Accounts HTTP endpoints."""
from fastapi import APIRouter
from fastapi import Depends
from backend.services import budget as service
from backend.web.auth import get_user
from backend.persistence.database import get_db
from backend.core.schemas import NewAccount, NewAccountGroup, AddCurrency, MergeAccounts, EditAccountGroup, SetArchived, BalanceCorrection
from backend.services import management

router = APIRouter(tags=["accounts"])

@router.get("/api/accounts")
def accounts(user=Depends(get_user), db=Depends(get_db)):
    return service.accounts(db, user.id)


@router.post("/api/accounts", status_code=201)
def create_account(data: NewAccount, user=Depends(get_user), db=Depends(get_db)):
    return {"id": service.create_account(db, user.id, data)}


@router.get('/api/account-groups')
def groups(include_archived: bool = False, user=Depends(get_user), db=Depends(get_db)):
    return service.account_groups(db, user.id, include_archived=include_archived)


@router.post('/api/account-groups', status_code=201)
def create_group(data: NewAccountGroup, user=Depends(get_user), db=Depends(get_db)):
    return {'id': service.create_account_group(db, user.id, data)}


@router.post('/api/account-groups/merge')
def merge_groups(data: MergeAccounts, user=Depends(get_user), db=Depends(get_db)):
    return {'id': service.merge_accounts(db, user.id, data)}


@router.post('/api/account-groups/{group_id}/currencies', status_code=201)
def add_group_currency(group_id: int, data: AddCurrency, user=Depends(get_user), db=Depends(get_db)):
    return {'id': service.add_currency(db, user.id, group_id, data)}


@router.post('/api/account-groups/{group_id}/edit')
def edit_group(group_id: int, data: EditAccountGroup, user=Depends(get_user), db=Depends(get_db)):
    management.edit_account(db, user.id, group_id, data)
    return {'ok': True}


@router.post('/api/account-groups/{group_id}/archive')
def archive_group(group_id: int, data: SetArchived, user=Depends(get_user), db=Depends(get_db)):
    management.archive_account(db, user.id, group_id, data.archived)
    return {'ok': True}


@router.post('/api/accounts/{account_id}/balance')
def correct_account_balance(account_id: int, data: BalanceCorrection, user=Depends(get_user), db=Depends(get_db)):
    management.correct_balance(db, user.id, account_id, data)
    return {'ok': True}

