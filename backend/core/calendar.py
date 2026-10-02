import os
import calendar
from datetime import datetime, date
from zoneinfo import ZoneInfo

def timezone_name():
    return os.getenv('APP_TIMEZONE', 'America/Argentina/Buenos_Aires')

def today():
    return datetime.now(ZoneInfo(timezone_name())).date()

def next_month(day):
    return date(day.year + (day.month == 12), day.month % 12 + 1, 1)

def scheduled_date(month, day):
    last = calendar.monthrange(month.year, month.month)[1]
    return month.replace(day=last if day == 0 else min(day, last))
