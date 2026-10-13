"""Локальные проверки нормализации и дедупликации (без сети)."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from main import build_result, normalize_phone  # noqa: E402


def test_normalize_phone():
    valid = {
        "+7 999 123-45-67": "+79991234567",
        "8 (999) 123 45 67": "+79991234567",
        "79991234567": "+79991234567",
        "8-916-000-00-01": "+79160000001",
        "9005551212": "+79005551212",
        "8 903 111 22 33": "+79031112233",
        "+7-926-123-45-67": "+79261234567",
        "8 999 111 00 00": "+79991110000",
        "+7 916 445 56 67": "+79164455667",
        "+79219998877": "+79219998877",
    }
    invalid = ["123", "", "не указан", "+7 999", None, "abc", "+1 202 555 0143"]
    for src, exp in valid.items():
        assert normalize_phone(src) == exp, f"{src!r}: {normalize_phone(src)!r} != {exp!r}"
    for src in invalid:
        assert normalize_phone(src) is None, f"{src!r} должен быть отброшен"
    print("✅ normalize_phone")


def test_build_result():
    orders = [
        {"id": 1, "name": "A", "phone": "+7 999 123-45-67", "email": "a@x.ru",
         "amount": 1000, "created_at": "2026-10-01T10:00:00Z"},
        {"id": 2, "name": "B", "phone": "8 (999) 123 45 67", "email": "",
         "amount": 5000, "created_at": "2026-10-02T11:00:00Z"},   # тот же номер, больше сумма
        {"id": 3, "name": "C", "phone": "79991234567", "email": "a@x.ru",
         "amount": 3000, "created_at": "2026-10-03T09:00:00Z"},
        {"id": 4, "name": "D", "phone": "123", "email": "d@x.ru",
         "amount": 999, "created_at": "2026-10-01T00:00:00Z"},    # невалидный
        {"id": 5, "name": "E", "phone": "+7 916 000 00 01", "email": "e@x.ru",
         "amount": 200, "created_at": "2026-10-05T12:00:00Z"},
        {"id": 6, "name": "F", "phone": "8-916-000-00-01", "email": "",
         "amount": 200, "created_at": "2026-10-01T12:00:00Z"},    # равные суммы -> позже по дате
    ]
    res = build_result(orders)
    assert res["stats"] == {"received": 6, "unique": 2,
                            "duplicates_merged": 3, "invalid_dropped": 1}, res["stats"]
    by = {c["phone"]: c for c in res["clients"]}
    assert by["+79991234567"] == {"name": "B", "phone": "+79991234567",
                                  "email": "", "amount": 5000}
    assert by["+79160000001"]["name"] == "E"      # позднее по created_at при равных суммах
    assert by["+79160000001"]["amount"] == 200
    print("✅ build_result: дедуп по макс. amount, тай-брейк по created_at")


def test_idempotency():
    orders = [{"id": 1, "name": "A", "phone": "79991234567", "email": "",
               "amount": 10, "created_at": "2026-10-01T00:00:00Z"}]
    assert build_result(orders) == build_result(orders) == build_result(orders)
    print("✅ идемпотентность: повторный расчёт даёт тот же результат")


if __name__ == "__main__":
    test_normalize_phone()
    test_build_result()
    test_idempotency()
    print("\nВсе тесты пройдены ✔")
