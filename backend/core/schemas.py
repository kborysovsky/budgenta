from datetime import date as Date
from decimal import Decimal
from typing import Literal
from pydantic import BaseModel, Field, model_validator, field_validator
from backend.core.calendar import today

Currency = Literal['USD', 'EUR', 'ARS', 'UAH', 'USDT', 'TRX', 'BTC', 'ETH']

class NewAccount(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    kind: Literal["cash", "debit", "card", "paypal", "crypto", "savings"]
    currency: Currency
    opening_balance: Decimal = Field(default=Decimal(0), ge=0, max_digits=26, decimal_places=8)
    date: Date = Field(default_factory=today)

class NewEntry(BaseModel):
    account_id: int
    kind: Literal["income", "expense"]
    amount: Decimal = Field(gt=0, max_digits=26, decimal_places=8)
    date: Date = Field(default_factory=today)
    category: str = Field(default="Other", min_length=1, max_length=60)
    note: str = Field(default="", max_length=300)
    save_category: bool = False

    @field_validator('category')
    @classmethod
    def clean_category(cls, value):
        value = ' '.join(value.split())
        if not value:
            raise ValueError('Enter a category.')
        return value

class Transfer(BaseModel):
    source_id: int
    destination_id: int
    amount: Decimal = Field(gt=0, max_digits=26, decimal_places=8)
    date: Date = Field(default_factory=today)

class Exchange(Transfer):
    # Destination currency received for one unit of source currency.
    rate: Decimal | None = Field(default=None, gt=0, max_digits=36, decimal_places=18)
    received: Decimal | None = Field(default=None, gt=0, max_digits=26, decimal_places=8)

    @model_validator(mode='after')
    def choose_exchange_input(self):
        if (self.rate is None) == (self.received is None):
            raise ValueError('Enter either an exchange rate or an amount received, not both.')
        return self

class CloseMonth(BaseModel):
    month: str = Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")


class NewDebt(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    currency: Currency
    amount: Decimal = Field(gt=0, max_digits=26, decimal_places=8)
    due_date: Date | None = None
    note: str = Field(default='', max_length=300)

class DebtPayment(BaseModel):
    account_id: int
    amount: Decimal = Field(gt=0, max_digits=26, decimal_places=8)
    date: Date = Field(default_factory=today)

class NewGoal(BaseModel):
    savings_account_ids: list[int] = Field(default_factory=list, max_length=100)
    name: str = Field(min_length=1, max_length=80)
    currency: Currency
    target: Decimal = Field(gt=0, max_digits=26, decimal_places=8)
    saved: Decimal = Field(default=Decimal(0), ge=0, max_digits=26, decimal_places=8)
    due_date: Date | None = None
    note: str = Field(default='', max_length=300)

class GoalProgress(BaseModel):
    saved: Decimal = Field(ge=0, max_digits=26, decimal_places=8)


class NewSavingsRule(BaseModel):
    source_id: int
    destination_id: int
    mode: Literal['fixed', 'remainder']
    amount: Decimal | None = Field(default=None, gt=0, max_digits=26, decimal_places=8)
    day: int = Field(default=10, ge=0, le=31)

    @model_validator(mode='after')
    def require_amount(self):
        if self.mode == 'fixed' and self.amount is None:
            raise ValueError('A fixed monthly rule needs an amount.')
        if self.mode == 'remainder':
            self.amount = None
        return self

class SetEnabled(BaseModel):
    enabled: bool

class SavingsMove(BaseModel):
    source_id: int
    destination_id: int
    mode: Literal['fixed', 'remainder'] = 'fixed'
    amount: Decimal | None = Field(default=None, gt=0, max_digits=26, decimal_places=8)
    date: Date = Field(default_factory=today)

    @model_validator(mode='after')
    def require_amount(self):
        if self.mode == 'fixed' and self.amount is None:
            raise ValueError('Enter an amount to move.')
        return self


class CurrencyBalance(BaseModel):
    currency: Currency
    opening_balance: Decimal = Field(default=Decimal(0), ge=0, max_digits=26, decimal_places=8)

class NewAccountGroup(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    kind: Literal['cash', 'debit', 'card', 'paypal', 'crypto', 'savings']
    balances: list[CurrencyBalance] = Field(min_length=1, max_length=8)
    date: Date = Field(default_factory=today)

class AddCurrency(CurrencyBalance):
    date: Date = Field(default_factory=today)

class MergeAccounts(BaseModel):
    source_id: int
    destination_id: int

class AccountFilter(BaseModel):
    include_rates: bool = True
    excluded_currencies: list[Currency] = Field(default_factory=list, max_length=8)
    account_ids: list[int] | None = None
    include_savings: bool = True

class ReportSchedule(AccountFilter):
    enabled: bool = True
    time: str = Field(default='09:15', pattern=r'^([01]\d|2[0-3]):[0-5]\d$')
    weekday: int = Field(default=0, ge=0, le=6)
    month_day: int = Field(default=1, ge=1, le=31)
    include_categories: bool = True

class CurrentStatePreferences(AccountFilter):
    include_categories: bool = True
    include_debts: bool = True
    include_goals: bool = True
    include_monthly_summary: bool = True

class AccountsPagePreferences(BaseModel):
    show_debit: bool = True
    show_credit: bool = True
    show_savings: bool = True
    order: list[int] = Field(default_factory=list, max_length=10000)

class MainCurrencySettings(BaseModel):
    currency: Currency

class ReportPreferences(BaseModel):
    main_currency: Currency = 'USD'
    timezone: str = 'America/Argentina/Buenos_Aires'
    daily: ReportSchedule = Field(default_factory=lambda: ReportSchedule(include_categories=False))
    weekly: ReportSchedule = Field(default_factory=lambda: ReportSchedule(enabled=False))
    monthly: ReportSchedule = Field(default_factory=lambda: ReportSchedule(time='09:00'))
    dashboard: AccountFilter = Field(default_factory=AccountFilter)
    current_state: CurrentStatePreferences = Field(default_factory=CurrentStatePreferences)
    accounts_page: AccountsPagePreferences = Field(default_factory=AccountsPagePreferences)

    @model_validator(mode='after')
    def valid_timezone(self):
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
        try:
            ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError('Use a valid IANA timezone, such as America/Argentina/Buenos_Aires.')
        return self


class EditAccountGroup(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    kind: Literal['cash', 'debit', 'card', 'paypal', 'crypto', 'savings']

class SetArchived(BaseModel):
    archived: bool

class BalanceCorrection(BaseModel):
    balance: Decimal = Field(max_digits=26, decimal_places=8)
    date: Date = Field(default_factory=today)
    note: str = Field(default='', max_length=300)
