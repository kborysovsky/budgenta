from datetime import date as Date, datetime, timezone
from decimal import Decimal
from sqlalchemy import BigInteger, ForeignKey, String, Text, Boolean, false
from sqlalchemy.orm import Mapped, mapped_column
from backend.persistence.database import Base
from backend.core.encryption import Encrypted, identity_default

class User(Base):
    __tablename__ = 'users'
    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_id: Mapped[int] = mapped_column(Encrypted('int'))
    telegram_key: Mapped[str] = mapped_column(String(64), unique=True, default=identity_default)
    name: Mapped[str] = mapped_column(Encrypted())

class AccountGroup(Base):
    __tablename__ = 'account_groups'
    archived: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'), index=True)
    name: Mapped[str] = mapped_column(Encrypted())
    kind: Mapped[str] = mapped_column(Encrypted())

class Account(Base):
    __tablename__ = 'accounts'
    group_id: Mapped[int | None] = mapped_column(ForeignKey('account_groups.id'), nullable=True, index=True)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'), index=True)
    name: Mapped[str] = mapped_column(Encrypted())
    kind: Mapped[str] = mapped_column(Encrypted())
    currency: Mapped[str] = mapped_column(Encrypted())

class Entry(Base):
    __tablename__ = 'entries'
    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey('accounts.id'), index=True)
    kind: Mapped[str] = mapped_column(Encrypted())
    amount: Mapped[Decimal] = mapped_column(Encrypted('decimal'))
    date: Mapped[Date] = mapped_column(Encrypted('date'))
    category: Mapped[str] = mapped_column(Encrypted(), default='Other')
    note: Mapped[str] = mapped_column(Encrypted(), default='')
    operation_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    debt_id: Mapped[int | None] = mapped_column(ForeignKey('debts.id'), nullable=True)
    deleted: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    reversal_issue: Mapped[str | None] = mapped_column(Encrypted(), nullable=True)

class MonthClose(Base):
    __tablename__ = 'month_closes'
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'), index=True)
    month: Mapped[str] = mapped_column(Encrypted())
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(timezone.utc))

class Debt(Base):
    __tablename__ = 'debts'
    archived: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'), index=True)
    name: Mapped[str] = mapped_column(Encrypted())
    currency: Mapped[str] = mapped_column(Encrypted())
    amount: Mapped[Decimal] = mapped_column(Encrypted('decimal'))
    paid: Mapped[Decimal] = mapped_column(Encrypted('decimal'), default=Decimal(0))
    due_date: Mapped[Date | None] = mapped_column(Encrypted('date'), nullable=True)
    note: Mapped[str] = mapped_column(Encrypted(), default='')

class Goal(Base):
    __tablename__ = 'goals'
    archived: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'), index=True)
    name: Mapped[str] = mapped_column(Encrypted())
    currency: Mapped[str] = mapped_column(Encrypted())
    target: Mapped[Decimal] = mapped_column(Encrypted('decimal'))
    saved: Mapped[Decimal] = mapped_column(Encrypted('decimal'), default=Decimal(0))
    due_date: Mapped[Date | None] = mapped_column(Encrypted('date'), nullable=True)
    note: Mapped[str] = mapped_column(Encrypted(), default='')

class BotState(Base):
    __tablename__ = 'bot_states'
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'), primary_key=True)
    payload: Mapped[str] = mapped_column(Encrypted())

class SavedCategory(Base):
    __tablename__ = 'saved_categories'
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'), index=True)
    kind: Mapped[str] = mapped_column(Encrypted())
    name: Mapped[str] = mapped_column(Encrypted())

class BotReceipt(Base):
    __tablename__ = 'bot_receipts'
    update_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    payload: Mapped[str] = mapped_column(Encrypted())
    sent: Mapped[bool] = mapped_column(default=False)

class LoginChallenge(Base):
    __tablename__ = 'login_challenges'
    id: Mapped[str] = mapped_column(String(48), primary_key=True)
    browser_key: Mapped[str] = mapped_column(String(64))
    user_id: Mapped[int | None] = mapped_column(ForeignKey('users.id'), nullable=True)
    expires_at: Mapped[datetime] = mapped_column()
    consumed: Mapped[bool] = mapped_column(default=False)


class SavingsRule(Base):
    __tablename__ = 'savings_rules'
    archived: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'), index=True)
    source_id: Mapped[int] = mapped_column(ForeignKey('accounts.id'))
    destination_id: Mapped[int] = mapped_column(ForeignKey('accounts.id'))
    mode: Mapped[str] = mapped_column(Encrypted())
    amount: Mapped[Decimal | None] = mapped_column(Encrypted('decimal'), nullable=True)
    day: Mapped[int] = mapped_column(Encrypted('int'))
    next_run: Mapped[Date] = mapped_column(Encrypted('date'))
    active: Mapped[int] = mapped_column(Encrypted('int'), default=1)

class SavingsRun(Base):
    __tablename__ = 'savings_runs'
    id: Mapped[int] = mapped_column(primary_key=True)
    rule_id: Mapped[int] = mapped_column(ForeignKey('savings_rules.id'), index=True)
    run_key: Mapped[str] = mapped_column(String(64), unique=True)
    scheduled_date: Mapped[Date] = mapped_column(Encrypted('date'))
    result: Mapped[str] = mapped_column(Encrypted())
    operation_id: Mapped[str | None] = mapped_column(String(36), nullable=True)

class ReportSettings(Base):
    __tablename__ = 'report_settings'
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'), primary_key=True)
    enabled: Mapped[int] = mapped_column(Encrypted('int'), default=1)
    next_report: Mapped[Date] = mapped_column(Encrypted('date'))

class Notification(Base):
    __tablename__ = 'notifications'
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'), index=True)
    job_key: Mapped[str] = mapped_column(String(64), unique=True)
    payload: Mapped[str] = mapped_column(Encrypted())
    sent: Mapped[bool] = mapped_column(default=False)
    budget_id: Mapped[int | None] = mapped_column(ForeignKey('budget_limits.id'), nullable=True, index=True)
    budget_context: Mapped[str | None] = mapped_column(Encrypted(), nullable=True)


class BudgetLimit(Base):
    __tablename__ = 'budget_limits'
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'), index=True)
    category_key: Mapped[str] = mapped_column(String(64), unique=True)
    category: Mapped[str] = mapped_column(Encrypted())
    amount: Mapped[Decimal] = mapped_column(Encrypted('decimal'))
    currency: Mapped[str] = mapped_column(Encrypted())
    expense_currencies: Mapped[str] = mapped_column(Encrypted(), default='null')
    enabled: Mapped[int] = mapped_column(Encrypted('int'), default=1)
    deleted: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())


class BudgetAlertState(Base):
    __tablename__ = 'budget_alert_states'
    id: Mapped[int] = mapped_column(primary_key=True)
    budget_id: Mapped[int] = mapped_column(ForeignKey('budget_limits.id'), index=True)
    state_key: Mapped[str] = mapped_column(String(64), unique=True)
    payload: Mapped[str] = mapped_column(Encrypted())


class Preferences(Base):
    __tablename__ = 'preferences'
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'), primary_key=True)
    payload: Mapped[str] = mapped_column(Encrypted())

class MarketQuote(Base):
    __tablename__ = 'market_quotes'
    currency: Mapped[str] = mapped_column(String(8), primary_key=True)
    payload: Mapped[str] = mapped_column(Text)
    fetched_at: Mapped[datetime] = mapped_column()
    checked_day: Mapped[str] = mapped_column(String(10))


class GoalSavings(Base):
    __tablename__ = 'goal_savings'
    id: Mapped[int] = mapped_column(primary_key=True)
    goal_id: Mapped[int] = mapped_column(ForeignKey('goals.id'), index=True)
    account_id: Mapped[int] = mapped_column(ForeignKey('accounts.id'), unique=True)
