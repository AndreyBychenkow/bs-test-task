"""Мини-синхронизатор заявок.

Забирает «сырые» заявки из источника (/api/orders), нормализует телефоны
к формату +7XXXXXXXXXX, дедуплицирует по телефону (при дубле — запись с
максимальным amount, при равенстве — более поздняя по created_at) и отдаёт
результат в JSON строго по схеме задания.

Идемпотентность: результат детерминированно пересчитывается из источника
при каждом синке — повторные запуски не плодят дубли и дают тот же JSON.

Прогрев: пока инстанс запущен, сервис сам периодически дёргает свой /health
(self-ping), чтобы free-инстанс Render не засыпал от простоя.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from contextlib import asynccontextmanager
from datetime import datetime

import httpx
from fastapi import FastAPI
from fastapi.responses import JSONResponse

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("sync")

SOURCE_URL = os.getenv("SOURCE_URL", "https://test.ooobs.ru/api/orders")
CACHE_TTL = float(os.getenv("CACHE_TTL", "30"))                  # сек: свежесть кэша ответа
KEEPALIVE_MINUTES = float(os.getenv("KEEPALIVE_MINUTES", "5"))   # self-ping, 0 = выкл.
HTTP_TIMEOUT = float(os.getenv("HTTP_TIMEOUT", "15"))

_state: dict = {"result": None, "fetched_at": 0.0, "stale": False, "last_keepalive": 0.0}
_lock = asyncio.Lock()


# ---------- нормализация ----------

def normalize_phone(raw) -> str | None:
    """Приводит телефон к +7XXXXXXXXXX. None — если к 11 цифрам не приводится."""
    digits = re.sub(r"\D", "", str(raw if raw is not None else ""))
    if not digits:
        return None
    if len(digits) == 11 and digits[0] in ("7", "8"):
        core = digits[1:]
    elif len(digits) == 10:            # 9005551212 -> +79005551212
        core = digits
    else:
        return None
    if len(core) != 10 or core[0] in ("0", "1"):
        return None                    # невалидный код оператора/региона
    return "+7" + core


def _amount(value):
    """Число из amount; мусор/пусто -> 0."""
    if value is None or isinstance(value, bool):
        return 0
    if isinstance(value, (int, float)):
        return int(value) if float(value).is_integer() else float(value)
    try:
        num = float(str(value).replace(",", ".").strip())
        return int(num) if num.is_integer() else num
    except (TypeError, ValueError):
        return 0


def _ts(value) -> float:
    """created_at -> unix-время для сравнения (ISO-8601, Z допускается)."""
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
        except ValueError:
            pass
    return 0.0


def build_result(orders: list) -> dict:
    """Считает итоговый отчёт из «сырых» заявок."""
    received = invalid_dropped = 0
    best_key: dict[str, tuple] = {}
    winner: dict[str, dict] = {}

    for idx, raw in enumerate(orders):
        received += 1
        if not isinstance(raw, dict):
            invalid_dropped += 1
            continue
        phone = normalize_phone(raw.get("phone"))
        if phone is None:
            invalid_dropped += 1
            continue
        amount = _amount(raw.get("amount"))
        amount_num = float(amount) if isinstance(amount, (int, float)) else 0.0
        rid = raw.get("id")
        key = (amount_num, _ts(raw.get("created_at")),
               float(rid) if isinstance(rid, (int, float)) else float(idx))
        if phone not in best_key or key > best_key[phone]:
            best_key[phone] = key
            winner[phone] = raw

    clients = [
        {
            "name": winner[p].get("name") or "",
            "phone": p,
            "email": winner[p].get("email") or "",
            "amount": _amount(winner[p].get("amount")),
        }
        for p in sorted(winner)
    ]
    result = {
        "clients": clients,
        "stats": {
            "received": received,
            "unique": len(clients),
            "duplicates_merged": received - invalid_dropped - len(clients),
            "invalid_dropped": invalid_dropped,
        },
    }
    return result


# ---------- источник + кэш ----------

async def refresh(force: bool = False) -> dict:
    async with _lock:
        now = time.time()
        if (not force and _state["result"] is not None
                and now - _state["fetched_at"] < CACHE_TTL):
            return _state["result"]
        try:
            async with httpx.AsyncClient(timeout=HTTP_TIMEOUT,
                                         follow_redirects=True) as client:
                resp = await client.get(SOURCE_URL)
                resp.raise_for_status()
                data = resp.json()
            if not isinstance(data, list):
                raise ValueError("источник вернул не JSON-массив")
            _state.update(result=build_result(data), fetched_at=now, stale=False)
            log.info("sync ok: %s", _state["result"]["stats"])
        except Exception as exc:  # noqa: BLE001 — отдаём кэш/ошибку, сервис не падает
            log.warning("sync failed: %s", exc)
            if _state["result"] is None:
                raise
            _state["stale"] = True
        return _state["result"]


async def _keepalive_loop() -> None:
    """Пингует собственный публичный URL, чтобы free-инстанс Render не засыпал."""
    base = os.getenv("RENDER_EXTERNAL_URL")
    if not base or KEEPALIVE_MINUTES <= 0:
        return
    while True:
        await asyncio.sleep(KEEPALIVE_MINUTES * 60)
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                await client.get(f"{base}/health")
        except Exception:  # noqa: BLE001
            pass
        finally:
            _state["last_keepalive"] = time.time()


@asynccontextmanager
async def lifespan(_: FastAPI):
    try:
        await refresh(force=True)          # прогреваем кэш на старте
    except Exception as exc:  # noqa: BLE001
        log.warning("warm-up failed: %s", exc)
    task = asyncio.create_task(_keepalive_loop())
    yield
    task.cancel()


app = FastAPI(title="Мини-синхронизатор заявок", lifespan=lifespan)


def _respond() -> JSONResponse:
    payload = _state["result"]
    headers = {
        "Cache-Control": "no-store",
        "X-Sync-Age": f"{max(0.0, time.time() - _state['fetched_at']):.0f}s",
        "X-Sync-Stale": "1" if _state["stale"] else "0",
    }
    return JSONResponse(payload, headers=headers)


@app.get("/")
@app.get("/result")
async def get_result():
    """Итоговый JSON строго по схеме задания."""
    try:
        await refresh()
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(
            {"error": "source_unavailable", "detail": str(exc)}, status_code=503)
    return _respond()


@app.get("/sync")
async def force_sync():
    """Принудительная синхронизация (идемпотентна: тот же результат)."""
    await refresh(force=True)
    return _respond()


@app.get("/health")
async def health():
    last = _state["last_keepalive"]
    return {
        "status": "ok",
        "source": SOURCE_URL,
        "synced_ago_sec": round(max(0.0, time.time() - _state["fetched_at"])),
        "has_result": _state["result"] is not None,
        "keepalive": {
            "enabled": bool(os.getenv("RENDER_EXTERNAL_URL")) and KEEPALIVE_MINUTES > 0,
            "interval_min": KEEPALIVE_MINUTES,
            "last_self_ping_age_sec": round(time.time() - last) if last else None,
        },
    }
