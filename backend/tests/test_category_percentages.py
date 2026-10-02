from datetime import date, datetime, timezone
from decimal import Decimal
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from backend.persistence.database import Base
from backend.persistence.models import User
from backend.services import budget, reporting
from backend.bot import dialogue
from backend.core.schemas import NewAccount, NewEntry, Transfer, ReportPreferences
from backend.core.money import expense_percentage

@pytest.fixture
def db():
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        session.add(User(id=1, telegram_id=111, name='Test')); session.commit()
        yield session


def wallet(db, name, currency='USD', kind='cash'):
    return budget.create_account(db, 1, NewAccount(name=name, kind=kind, currency=currency, opening_balance='1000', date=date(2024,1,1)))


def spend(db, account, category, amount):
    return budget.add_entry(db,1,NewEntry(account_id=account,kind='expense',category=category,amount=amount,date=date(2024,1,31)))


def quote(currency):
    return {'usd_rate':{'EUR':'2','ARS':'0.001','BTC':'50000'}.get(currency,'1'), 'stale':False, 'source':'Test', 'display_rate':currency, 'as_of':'2024-01-31'}


def test_filtered_category_percentages_use_combined_usd_total_and_reverse(db):
    cash=wallet(db,'Cash');eur=wallet(db,'Euros','EUR');saved=wallet(db,'Reserve',kind='savings');other=wallet(db,'Excluded')
    food=spend(db,cash,'Outside Food','30');spend(db,cash,'Grocery','70');spend(db,eur,'Outside Food','10')
    spend(db,saved,'Health','20');spend(db,other,'Rent','500')
    budget.add_entry(db,1,NewEntry(account_id=cash,kind='income',amount='100',date=date(2024,1,31)))
    budget.transfer(db,1,Transfer(source_id=cash,destination_id=saved,amount='100',date=date(2024,1,31)))
    prefs=ReportPreferences()
    prefs.monthly.account_ids=[a['group_id'] for a in budget.accounts(db,1) if a['id'] in (cash,eur,saved)]
    prefs.monthly.include_savings=False
    reporting.save_preferences(db,1,prefs)
    report=reporting.monthly_report(db,1,'2024-01',quote_fn=quote)
    rows={(r['currency'],r['category']):r for r in report['categories']}
    assert rows[('USD','Outside Food')]['percentage']=='25.00'
    assert rows[('USD','Grocery')]['percentage']=='58.33'
    assert rows[('EUR','Outside Food')]['percentage']=='16.67'
    combined={r['category']:r for r in report['category_totals']}
    assert combined['Outside Food']['percentage']=='41.67'
    assert combined['Grocery']['percentage']=='58.33'
    assert len(combined['Outside Food']['amounts'])==2
    assert report['expense_valuation']['total_usd']=='120.00'
    assert len(rows)==3
    assert [r['category'] for r in report['categories'] if r['currency']=='USD']==['Grocery','Outside Food']
    prefs.monthly.excluded_currencies=['EUR'];reporting.save_preferences(db,1,prefs)
    assert all(r['currency']=='USD' for r in reporting.monthly_report(db,1,'2024-01',quote_fn=quote)['categories'])
    budget.delete_transaction(db,1,food)
    assert reporting.monthly_report(db,1,'2024-01',quote_fn=quote)['categories']==[{'currency':'USD','category':'Grocery','amount':'70','percentage':'100.00'}]


@pytest.mark.parametrize('frequency',['daily','weekly','monthly','current_state'])
def test_telegram_reports_show_percentages_and_respect_category_toggle(db,frequency):
    cash=wallet(db,'Cash');spend(db,cash,'Outside Food','25');spend(db,cash,'Grocery','75')
    prefs=ReportPreferences();getattr(prefs,frequency).include_categories=True
    reporting.save_preferences(db,1,prefs)
    def message():
        if frequency=='current_state':return reporting.current_state(db,1,datetime(2024,1,31,15,tzinfo=timezone.utc),quote_fn=quote)
        return reporting.report_message(db,1,frequency,datetime(2024,2,1,15,tzinfo=timezone.utc),quote_fn=quote)
    result=message()
    assert 'Outside Food: 25.00 USD · 25.00%' in result
    assert 'Grocery: 75.00 USD · 75.00%' in result
    assert '% of total expenses across currencies' in result
    getattr(prefs,frequency).include_categories=False;reporting.save_preferences(db,1,prefs)
    assert '25.00%' not in message()


def test_percentage_zero_rounding_and_outside_food_menu(db):
    assert expense_percentage(Decimal('0'),Decimal('0'))=='0.00'
    assert expense_percentage(Decimal('1'),Decimal('3'))=='33.33'
    cash=wallet(db,'Cash')
    prefs=ReportPreferences();reporting.save_preferences(db,1,prefs)
    assert reporting.monthly_report(db,1,'2024-01',quote_fn=quote)['categories']==[]
    user=db.get(User,1)
    for text in ('↑ Expense',f'#{cash}','10'):
        reply=dialogue.handle(db,user,text)
    assert ['Outside Food'] in reply['reply_markup']['keyboard']


@pytest.mark.parametrize('frequency',['daily','weekly','monthly','current_state'])
def test_mixed_currency_bot_categories_share_one_total(db,frequency):
    cash=wallet(db,'Cash'); ars=wallet(db,'Pesos','ARS'); eur=wallet(db,'Euros','EUR')
    spend(db,cash,'Grocery','10'); spend(db,ars,'Grocery','1000'); spend(db,eur,'Rent','5')
    prefs=ReportPreferences();getattr(prefs,frequency).include_categories=True
    getattr(prefs,frequency).include_rates=False
    reporting.save_preferences(db,1,prefs)
    calls=[]
    def quotes(currency):
        calls.append(currency)
        return quote(currency)
    message=(reporting.current_state(db,1,datetime(2024,1,31,15,tzinfo=timezone.utc),quote_fn=quotes)
             if frequency=='current_state' else reporting.report_message(db,1,frequency,datetime(2024,2,1,15,tzinfo=timezone.utc),quote_fn=quotes))
    assert 'Grocery: 1000.00 ARS + 10.00 USD · 52.38%' in message
    assert 'Rent: 5.00 EUR · 47.62%' in message
    assert message.count('Grocery:')==1
    assert all(calls.count(currency)==1 for currency in ('USD','EUR','ARS'))


def test_missing_expense_rate_hides_all_percentages_but_keeps_native_amounts(db):
    cash=wallet(db,'Cash');eur=wallet(db,'Euros','EUR')
    spend(db,cash,'Grocery','10');spend(db,eur,'Rent','5')
    report=reporting.monthly_report(db,1,'2024-01',quote_fn=lambda c:None if c=='EUR' else quote(c))
    assert not report['expense_valuation']['complete']
    assert all(r['percentage'] is None for r in report['categories']+report['category_totals'])
    text='\n'.join(reporting.category_lines(report))
    assert '5.00 EUR' in text and '10.00 USD' in text and 'missing expense exchange rates for EUR' in text
    assert '100.00%' not in text


def test_stale_rate_warning_and_tiny_crypto_share_before_rounding(db):
    btc=budget.create_account(db,1,NewAccount(name='Crypto',kind='crypto',currency='BTC',opening_balance='1',date=date(2024,1,1)))
    usd=wallet(db,'Cash')
    spend(db,btc,'Fees','0.00000001');spend(db,usd,'Grocery','0.01')
    report=reporting.monthly_report(db,1,'2024-01',quote_fn=lambda c:{**quote(c),'stale':c=='BTC'})
    shares={r['category']:r['percentage'] for r in report['category_totals']}
    assert shares=={'Grocery':'95.24','Fees':'4.76'}
    assert 'cached exchange rates' in '\n'.join(reporting.category_lines(report))


def test_disabled_breakdown_does_not_fetch_rates_and_legacy_report_agrees(db):
    usd=wallet(db,'Cash');eur=wallet(db,'Euros','EUR')
    spend(db,usd,'Grocery','10');spend(db,eur,'Grocery','5')
    prefs=ReportPreferences();prefs.monthly.include_categories=False;reporting.save_preferences(db,1,prefs)
    def forbidden(currency): raise AssertionError('Categories disabled; should not fetch rates')
    report=reporting.monthly_report(db,1,'2024-01',quote_fn=forbidden)
    assert report['category_totals']==[]
    legacy=budget.expense_report(db,1,'2024-01',quote_fn=quote)
    assert legacy['category_totals'][0]['percentage']=='100.00'
    assert len(legacy['category_totals'][0]['amounts'])==2
    assert budget.report_text(legacy).count('Grocery:')==1
