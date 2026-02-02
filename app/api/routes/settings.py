import json
import urllib.request
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ...api.deps import require_role
from ...db import get_db
from ...models import SystemSetting, User
from ...schemas import SystemSettingBase, SystemSettingCreate, SystemSettingUpdate
from ...services.audit import record_audit

router = APIRouter(prefix="/settings", tags=["settings"])

CURRENCY_SETTINGS_KEY = "currency"
SYSTEM_SETTINGS_KEY = "system"
CURRENCY_API_URL = "https://open.er-api.com/v6/latest/{base}"


def _parse_last_update(payload: dict) -> str:
    utc_value = payload.get("time_last_update_utc")
    if isinstance(utc_value, str):
        try:
            parsed = parsedate_to_datetime(utc_value)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc).isoformat()
        except (TypeError, ValueError):
            pass
    unix_value = payload.get("time_last_update_unix")
    if isinstance(unix_value, (int, float)):
        return datetime.fromtimestamp(unix_value, tz=timezone.utc).isoformat()
    return datetime.now(tz=timezone.utc).isoformat()


def _fetch_currency_rates(base_currency: str) -> Tuple[dict, str]:
    url = CURRENCY_API_URL.format(base=base_currency)
    request = urllib.request.Request(url, headers={"User-Agent": "SmartPOS/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            if response.status != 200:
                raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Currency provider error")
            payload = json.load(response)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Currency provider unavailable") from exc

    if payload.get("result") != "success":
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=payload.get("error-type") or "Currency provider error",
        )

    rates = payload.get("rates")
    if not isinstance(rates, dict):
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Currency provider response invalid")

    last_updated = _parse_last_update(payload)
    return rates, last_updated


def _resolve_base_currency(db: Session) -> str:
    currency_setting = db.query(SystemSetting).filter(SystemSetting.setting_key == CURRENCY_SETTINGS_KEY).first()
    if currency_setting and isinstance(currency_setting.setting_value, dict):
        base_value = currency_setting.setting_value.get("baseCurrency")
        if isinstance(base_value, str) and len(base_value) == 3:
            return base_value.upper()

    system_setting = db.query(SystemSetting).filter(SystemSetting.setting_key == SYSTEM_SETTINGS_KEY).first()
    if system_setting and isinstance(system_setting.setting_value, dict):
        system_currency = system_setting.setting_value.get("currency")
        if isinstance(system_currency, str) and len(system_currency) == 3:
            return system_currency.upper()

    return "HTG"


@router.get("/", response_model=List[SystemSettingBase])
def list_settings(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager", allow_perms=("settings.read",))),
):
    return db.query(SystemSetting).order_by(SystemSetting.created_at.desc()).all()


@router.put("/{key}", response_model=SystemSettingBase)
def upsert_setting(
    key: str,
    setting_in: SystemSettingUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin", allow_perms=("settings.write",))),
):
    setting = db.query(SystemSetting).filter(SystemSetting.setting_key == key).first()
    if not setting:
        create_payload = SystemSettingCreate(
            setting_key=key,
            setting_value=setting_in.setting_value or {},
            description=setting_in.description,
        )
        setting = SystemSetting(**create_payload.model_dump())
        db.add(setting)
        action = "CREATE"
    else:
        for field, value in setting_in.model_dump(exclude_unset=True).items():
            setattr(setting, field, value)
        action = "UPDATE"

    record_audit(
        db,
        user_id=current_user.id,
        action=action,
        table_name="system_settings",
        record_id=setting.id,
        new_values=setting_in.model_dump(exclude_unset=True),
    )
    db.commit()
    db.refresh(setting)
    return setting


@router.post("/currency/refresh", response_model=SystemSettingBase)
def refresh_currency_rates(
    base: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin", allow_perms=("settings.write",))),
):
    base_currency = (base or _resolve_base_currency(db)).upper()
    if not base_currency.isalpha() or len(base_currency) != 3:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid base currency")

    rates, last_updated = _fetch_currency_rates(base_currency)
    rates[base_currency] = 1
    payload = {
        "baseCurrency": base_currency,
        "rates": rates,
        "lastUpdated": last_updated,
    }

    setting = db.query(SystemSetting).filter(SystemSetting.setting_key == CURRENCY_SETTINGS_KEY).first()
    if not setting:
        create_payload = SystemSettingCreate(
            setting_key=CURRENCY_SETTINGS_KEY,
            setting_value=payload,
            description="Currency exchange rates",
        )
        setting = SystemSetting(**create_payload.model_dump())
        db.add(setting)
        action = "CREATE"
    else:
        setting.setting_value = payload
        action = "UPDATE"

    record_audit(
        db,
        user_id=current_user.id,
        action=action,
        table_name="system_settings",
        record_id=setting.id,
        new_values=payload,
    )
    db.commit()
    db.refresh(setting)
    return setting
