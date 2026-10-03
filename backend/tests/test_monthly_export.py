import csv
import io
import zipfile
import xml.etree.ElementTree as ET
from datetime import date
from decimal import Decimal
import pytest
from sqlalchemy import select
from backend.tests.test_budget import db, account, DAY
from backend.core.schemas import NewEntry, Transfer, Exchange, NewDebt, DebtPayment, BalanceCorrection, ReportPreferences, BudgetLimitInput, BudgetLimitSettings
from backend.persistence.models import Account, Entry
from backend.services import budget, reporting, monthly_export as export, management, exchanges, budget_limits


def quote(currency):
    return dict(usd_rate={'USD':'1','EUR':'2','ARS':'.001','USDT':'1','BTC':'50000'}[currency],stale=False,as_of='2024-01-15',source='Test',display_rate=currency)


def entry(db, wallet, amount, category='Grocery', kind='expense', uid=1, **kwargs):
    return budget.add_entry(db, uid, NewEntry(account_id=wallet,amount=amount,kind=kind,category=category,date=DAY,**kwargs))


def tables(db, **kwargs):
    return export.monthly_tables(db,1,'2024-01',quote_fn=kwargs.get('quote_fn',quote))


def named(result, name): return next(t for t in result if t['name']==name)


def test_export_all_activity_links_repayments_omits_corrections_deleted_other_users(db):
    cash=account(db,opening='1000');other=account(db,opening='0');eur=account(db,currency='EUR',opening='100')
    foreign=account(db,user=2,opening='1000')
    eid=entry(db,cash,'50');entry(db,cash,'100',kind='income',category='Salary')
    mistake=entry(db,cash,'10');budget.delete_transaction(db,1,mistake)
    entry(db,foreign,'999',uid=2)
    transfer=budget.transfer(db,1,Transfer(source_id=cash,destination_id=other,amount='20',date=DAY))
    exchange=exchanges.exchange(db,1,Exchange(source_id=eur,destination_id=cash,amount='10',received='20',date=DAY))
    debt=budget.create_debt(db,1,NewDebt(name='Loan',currency='USD',amount='100'))
    payment=budget.repay_debt(db,1,debt,DebtPayment(account_id=cash,amount='25',date=DAY))
    management.correct_balance(db,1,cash,BalanceCorrection(balance='0',date=DAY,note='Manual correction'))
    management.archive_account(db,1,db.get(Account,cash).group_id,True)
    result=tables(db);rows=named(result,'Transactions')['rows']
    assert len(rows)==7 and {r[1] for r in rows}=={'Income','Expense','Transfer','Exchange'}
    assert eid in {r[7] for r in rows} and mistake not in {r[7] for r in rows}
    assert all(r[9]!=foreign for r in rows)
    assert len([r for r in rows if r[8]==transfer])==2
    assert len([r for r in rows if r[8]==exchange['operation_id']])==2
    assert next(r for r in rows if r[7]==payment)[10]==debt
    usd=next(r for r in named(result,'Monthly totals')['rows'] if r[0]=='USD')
    assert usd[1:]==[Decimal('100'),Decimal('75'),Decimal('25'),Decimal('20'),Decimal('40')]
    assert named(result,'Account activity')['rows']
    assert named(result,'Daily activity')['rows'][0][0]=='2024-01-15'
    assert b'Manual correction' not in export.csv_bytes(result)
    assert export.monthly_tables(db,2,'2024-01',quote_fn=quote)[-1]['rows'][0][4]==Decimal('-999')


def test_multi_currency_category_shares_main_currency_and_missing_rates(db):
    usd=account(db);ars=account(db,currency='ARS',opening='10000');eur=account(db,currency='EUR')
    entry(db,usd,'10');entry(db,ars,'1000');entry(db,eur,'5',category='Rent')
    prefs=ReportPreferences(main_currency='EUR');reporting.save_preferences(db,1,prefs)
    result=tables(db);categories=named(result,'Spending by category')
    assert categories['headers'][2]=='Estimated spending (EUR)'
    values={r[0]:r for r in categories['rows']}
    assert values['Grocery'][2:]==[Decimal('5.50'),Decimal('52.38')]
    assert values['Rent'][2:]==[Decimal('5.00'),Decimal('47.62')]
    missing=tables(db,quote_fn=lambda c: None if c=='ARS' else quote(c))
    assert all(row[3] is None for row in named(missing,'Spending by category')['rows'])
    assert next(row for row in named(missing,'Spending by category')['rows'] if row[0]=='Grocery')[2] is None
    assert 'xl/charts/chart1.xml' not in zipfile.ZipFile(io.BytesIO(export.xlsx_bytes(missing))).namelist()
    assert 'Missing exchange rates' in str(named(missing,'Report information')['rows'])


def test_month_filters_savings_currency_accounts_and_optional_sections(db):
    cash=account(db);savings=account(db,kind='savings');eur=account(db,currency='EUR')
    entry(db,cash,'10');entry(db,savings,'15');entry(db,eur,'20')
    budget.add_entry(db,1,NewEntry(account_id=cash,kind='expense',amount='9',date=date(2023,12,31)))
    prefs=ReportPreferences();prefs.monthly.excluded_currencies=['EUR'];prefs.monthly.include_savings=False
    prefs.monthly.include_categories=False;prefs.monthly.include_rates=False
    reporting.save_preferences(db,1,prefs)
    result=tables(db)
    assert len(named(result,'Transactions')['rows'])==1
    assert {'Exchange rates','Spending by category','Budget Limits'}.isdisjoint(t['name'] for t in result)
    budget_limits.save_settings(db,1,BudgetLimitSettings(enabled=True))
    budget_limits.save(db,1,BudgetLimitInput(category='Grocery',amount='100',currency='USD'))
    prefs.monthly.include_budgets=True;reporting.save_preferences(db,1,prefs)
    assert named(tables(db),'Budget Limits')['rows'][0][3]==10
    prefs.monthly.account_ids=[];reporting.save_preferences(db,1,prefs)
    assert named(tables(db),'Transactions')['rows']==[]
    assert export.csv_bytes(tables(db)).startswith(b'\xef\xbb\xbf')
    with pytest.raises(budget.BudgetError): export.monthly_tables(db,1,'2024-13',quote_fn=quote)


@pytest.mark.parametrize('dangerous',['=1+1','+1','-cmd','@SUM(A1)', ' \t=1+1','\x00=1+1','\ufeff=1+1','\ntext'])
def test_csv_formula_protection(dangerous):
    assert export.safe_csv_cell(dangerous)=="'"+dangerous
    assert export.safe_csv_cell(Decimal('-1.00000001'))=='-1.00000001'


def test_csv_escaping_localization_and_crypto_precision(db):
    wallet=account(db,currency='BTC',kind='crypto',opening='1')
    entry(db,wallet,'0.00000001',category='=Private purpose',note='=HYPERLINK("https://example.invalid")\nline, "two"')
    reporting.save_language(db,1,'ru')
    result=tables(db);content=export.csv_bytes(result)
    parsed=list(csv.reader(io.StringIO(content.decode('utf-8-sig'))))
    assert any('Операции' in row for row in parsed)
    transaction=result[-1]['rows'][0]
    assert transaction[1]=='Расход' and transaction[4]==Decimal('-0.00000001')
    exported=next(row for row in parsed if row and row[0]=='2024-01-15' and len(row)==11)
    assert exported[4]=='-0.00000001' and exported[5]=="'=Private purpose" and exported[6].startswith("'=HYPERLINK")
    assert '\nline, "two"' in exported[6]


def test_excel_sheets_chart_data_no_formulas_or_links_and_exact_large_values(db):
    wallet=account(db,opening='1000');entry(db,wallet,'50',note='=1+1');entry(db,wallet,'150',category='Rent',note='https://example.invalid')
    result=tables(db)
    # Preserve a legitimate value beyond Excel's numeric precision as text.
    result[-1]['rows'][0][4]=Decimal('-123456789012345.67')
    file=zipfile.ZipFile(io.BytesIO(export.xlsx_bytes(result)))
    ns={'s':'http://schemas.openxmlformats.org/spreadsheetml/2006/main','c':'http://schemas.openxmlformats.org/drawingml/2006/chart'}
    assert 'xl/charts/chart1.xml' in file.namelist()
    chart=ET.fromstring(file.read('xl/charts/chart1.xml'))
    chart_values=[e.text for e in chart.findall('.//c:numCache/c:pt/c:v',ns)]
    assert [Decimal(v) for v in chart_values]==[75,25]
    strings=ET.fromstring(file.read('xl/sharedStrings.xml'))
    values=[''.join(e.itertext()) for e in strings]
    assert '-123456789012345.67' in values and '=1+1' in values and 'https://example.invalid' in values
    for name in file.namelist():
        if name.startswith('xl/worksheets/sheet') and name.endswith('.xml'):
            sheet=ET.fromstring(file.read(name))
            assert sheet.find('.//s:f',ns) is None and sheet.find('.//s:hyperlink',ns) is None
    assert not any('externalLink' in name for name in file.namelist())


@pytest.mark.parametrize('language',['en','ru','uk','es'])
def test_workbook_locales_and_empty_report(db,language):
    reporting.save_language(db,1,language)
    data=export.xlsx_bytes(tables(db))
    assert zipfile.is_zipfile(io.BytesIO(data))
    assert 'xl/charts/chart1.xml' not in zipfile.ZipFile(io.BytesIO(data)).namelist()


def test_export_http_auth_and_attachment_headers(telegram_login):
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from sqlalchemy.pool import StaticPool
    from backend.persistence.database import Base,get_db
    from backend.web.main import app
    engine=create_engine('sqlite://',connect_args={'check_same_thread':False},poolclass=StaticPool);Base.metadata.create_all(engine)
    def session():
        with Session(engine) as db: yield db
    app.dependency_overrides[get_db]=session
    try:
        with TestClient(app) as client:
            for format in ['csv','xlsx']:
                assert client.get(f'/api/reports/2024-01/export.{format}').status_code==401
            telegram_login(client)
            for format in ['csv','xlsx']:
                response=client.get(f'/api/reports/2024-01/export.{format}')
                assert response.status_code==200
                assert response.headers['Content-Disposition']==f'attachment; filename="budgenta-2024-01.{format}"'
                assert response.headers['Cache-Control']=='no-store'
                assert response.headers['X-Content-Type-Options']=='nosniff'
                assert client.get(f'/api/reports/invalid/export.{format}').status_code==400
    finally: app.dependency_overrides.clear()
