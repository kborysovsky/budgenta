"""Reports HTTP endpoints."""
from fastapi import APIRouter
from fastapi import Depends, HTTPException
from backend.services import budget as service
from backend.web.auth import get_user
from backend.persistence.database import get_db
from backend.core.schemas import SetEnabled, ReportPreferences, CurrentStatePreferences, AccountsPagePreferences, MainCurrencySettings, LanguageSettings
from backend.services import rates
from backend.services import scheduler
from backend.services import reporting

router = APIRouter(tags=["reports"])

@router.get('/api/balance')
def balance(dashboard: bool = False, user=Depends(get_user), db=Depends(get_db)):
    return reporting.estimated_balance(db, user.id, dashboard=dashboard)


@router.get('/api/balance/usd')
def usd_balance(dashboard: bool = False, user=Depends(get_user), db=Depends(get_db)):
    accounts = reporting.selected_accounts(db, user.id, reporting.get_preferences(db, user.id)['dashboard']) if dashboard else service.accounts(db, user.id)
    return rates.valuation(accounts)


@router.get('/api/reports/{month}')
def expense_report(month: str, user=Depends(get_user), db=Depends(get_db)):
    return reporting.monthly_report(db, user.id, month)


@router.get('/api/report-settings')
def report_settings(user=Depends(get_user), db=Depends(get_db)):
    return scheduler.report_settings(db, user.id)


@router.post('/api/report-settings')
def update_report_settings(data: SetEnabled, user=Depends(get_user), db=Depends(get_db)):
    scheduler.set_reports(db, user.id, data.enabled)
    return {'ok': True}


@router.get('/api/preferences')
def preferences(user=Depends(get_user), db=Depends(get_db)):
    return reporting.get_preferences(db, user.id)

@router.post('/api/preferences/language')
def save_language(data: LanguageSettings, user=Depends(get_user), db=Depends(get_db)):
    return reporting.save_language(db, user.id, data.language)


@router.post('/api/preferences')
def save_preferences(data: ReportPreferences, user=Depends(get_user), db=Depends(get_db)):
    return reporting.save_preferences(db, user.id, data)


@router.post('/api/preferences/main-currency')
def save_main_currency(data: MainCurrencySettings, user=Depends(get_user), db=Depends(get_db)):
    return reporting.save_main_currency(db, user.id, data.currency)


@router.get('/api/dashboard/{month}')
def dashboard(month: str, user=Depends(get_user), db=Depends(get_db)):
    return reporting.dashboard(db, user.id, month)


@router.get('/api/report-preview/{frequency}')
def preview(frequency: str, user=Depends(get_user), db=Depends(get_db)):
    if frequency == 'current-state':
        return {'text': reporting.current_state(db, user.id)}
    if frequency not in ('daily', 'weekly', 'monthly'):
        raise HTTPException(404)
    return {'text': reporting.report_message(db, user.id, frequency)}


@router.post('/api/preferences/current-state')
def save_current_state_preferences(data: CurrentStatePreferences, user=Depends(get_user), db=Depends(get_db)):
    return reporting.save_section(db, user.id, 'current_state', data)


@router.post('/api/preferences/accounts-page')
def save_accounts_page_preferences(data: AccountsPagePreferences, user=Depends(get_user), db=Depends(get_db)):
    return reporting.save_section(db, user.id, 'accounts_page', data)
