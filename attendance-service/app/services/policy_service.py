from sqlalchemy.orm import Session
from uuid import UUID
from datetime import date
import httpx
from app.models.attendance import CompanyPolicy, HolidayCalendar
from app.core.config import settings


def default_policy() -> dict:
    return {
        'timezone': settings.DEFAULT_TIMEZONE,
        'daily_target_hours': 8,
        'weekly_hours': 40,
        'max_daily_hours': 10,
        'max_weekly_average_hours': 48,
        'break_after_6h_minutes': 30,
        'break_after_9h_minutes': 45,
        'rest_period_hours': 11,
        'late_grace_minutes': 15,
        'auto_insert_breaks': False,
        'sunday_justification_required': True,
        'require_geofence_on_mobile': False,
        'lock_after_days': 30,
        'payroll_round_to_minutes': 15,
        'daily_grace_early_departure_minutes': 0,
        'federal_state': '',
    }


def _coerce_uuid(value):
    if isinstance(value, UUID) or value is None:
        return value
    return UUID(str(value))


def get_company_policy(db: Session, company_id: str) -> CompanyPolicy:
    company_uuid = _coerce_uuid(company_id)
    row = db.query(CompanyPolicy).filter(CompanyPolicy.company_id == company_uuid).first()
    if not row:
        row = CompanyPolicy(company_id=company_uuid, **default_policy())
        db.add(row)
        db.flush()
    return row


def update_company_policy(db: Session, company_id: str, payload: dict) -> CompanyPolicy:
    row = get_company_policy(db, company_id)
    for key, value in payload.items():
        if value is not None:
            setattr(row, key, value)
    db.flush()
    return row


def list_holidays(db: Session, company_id: str):
    return db.query(HolidayCalendar).filter(HolidayCalendar.company_id == _coerce_uuid(company_id)).order_by(HolidayCalendar.holiday_date.asc()).all()


def upsert_holiday(db: Session, company_id: str, payload: dict):
    company_uuid = _coerce_uuid(company_id)
    row = db.query(HolidayCalendar).filter(
        HolidayCalendar.company_id == company_uuid,
        HolidayCalendar.holiday_date == payload['holiday_date'],
        HolidayCalendar.name == payload['name'],
    ).first()
    if not row:
        row = HolidayCalendar(company_id=company_uuid, **payload)
        db.add(row)
    else:
        for key, value in payload.items():
            setattr(row, key, value)
    db.flush()
    return row


def update_holiday(db: Session, company_id: str, holiday_id: str, payload: dict):
    row = db.query(HolidayCalendar).filter(
        HolidayCalendar.company_id == _coerce_uuid(company_id),
        HolidayCalendar.id == _coerce_uuid(holiday_id),
    ).first()
    if not row:
        raise ValueError('Holiday not found')
    for key, value in payload.items():
        setattr(row, key, value)
    db.flush()
    return row


def delete_holiday(db: Session, company_id: str, holiday_id: str):
    row = db.query(HolidayCalendar).filter(
        HolidayCalendar.company_id == _coerce_uuid(company_id),
        HolidayCalendar.id == _coerce_uuid(holiday_id),
    ).first()
    if not row:
        raise ValueError('Holiday not found')
    db.delete(row)
    db.flush()


def import_public_holidays(db: Session, company_id: str, country_code: str, state_code: str, year: int):
    country = (country_code or 'DE').strip().upper()
    state = (state_code or '').strip().upper()
    if not state:
        raise ValueError('state_code is required')
    if year < 1970 or year > 2100:
        raise ValueError('year must be between 1970 and 2100')

    url = f'https://date.nager.at/api/v3/PublicHolidays/{year}/{country}'
    response = httpx.get(url, timeout=15)
    response.raise_for_status()
    imported = []
    for item in response.json():
        counties = item.get('counties') or []
        applies_to_state = bool(item.get('global')) or not counties or state in {str(code).upper() for code in counties}
        if not applies_to_state:
            continue
        holiday_date = date.fromisoformat(item['date'])
        name = item.get('localName') or item.get('name') or 'Public holiday'
        row = upsert_holiday(db, company_id, {
            'state_code': state,
            'holiday_date': holiday_date,
            'name': name,
            'category': 'public',
        })
        imported.append(row)
    return imported
