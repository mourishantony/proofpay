"""invoice.py - invoice total calculation (fictional demo file, second delivery)."""
import os
import unittest
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

# Secrets come from the environment, never from source code.
PAYMENT_API_KEY = os.environ.get("PAYMENT_API_KEY", "")


def calculate_invoice_total(items, tax_rate):
    """Return subtotal plus tax, rounded to 2 decimals.

    items: list of {"price": number, "qty": int}
    tax_rate: fraction between 0 and 1 (e.g. 0.18 for 18%)
    Raises ValueError for a negative price or quantity, a tax rate outside 0-1,
    or a malformed item. An empty list returns 0.00.
    """
    if not 0 <= tax_rate <= 1:
        raise ValueError("tax_rate must be between 0 and 1")
    subtotal = Decimal("0")
    for item in items or []:
        try:
            price, qty = Decimal(str(item["price"])), int(item["qty"])
        except (KeyError, TypeError, ValueError, InvalidOperation) as exc:
            raise ValueError(f"invalid item: {item!r}") from exc
        if price < 0 or qty < 0:
            raise ValueError("price and qty must not be negative")
        subtotal += price * qty
    total = subtotal * (Decimal("1") + Decimal(str(tax_rate)))
    return float(total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


class CalculateInvoiceTotalTests(unittest.TestCase):
    def test_total_with_tax(self):
        self.assertEqual(calculate_invoice_total([{"price": 10, "qty": 2}, {"price": 5.5, "qty": 1}], 0.18), 30.09)

    def test_empty_list(self):
        self.assertEqual(calculate_invoice_total([], 0.18), 0.0)

    def test_negative_values_rejected(self):
        with self.assertRaises(ValueError):
            calculate_invoice_total([{"price": -1, "qty": 1}], 0.1)

    def test_bad_tax_rate_rejected(self):
        with self.assertRaises(ValueError):
            calculate_invoice_total([{"price": 1, "qty": 1}], 1.5)

    def test_malformed_item_rejected(self):
        with self.assertRaises(ValueError):
            calculate_invoice_total([{"price": "abc", "qty": 1}], 0.1)


if __name__ == "__main__":
    unittest.main()
