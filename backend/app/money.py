"""Money as integer minor units plus a currency code. Never a float.

Every multiplication by a rate goes through `mul_ratio`, which rounds half up on
integers, so the same inputs always produce the same centavos.
"""

from __future__ import annotations

from dataclasses import dataclass


def div_round_half_up(numerator: int, denominator: int) -> int:
    """Integer division rounding half away from zero."""
    if not isinstance(numerator, int) or not isinstance(denominator, int) or isinstance(numerator, bool):
        raise TypeError("div_round_half_up takes integers only")
    if denominator <= 0:
        raise ValueError("denominator must be positive")
    sign = -1 if numerator < 0 else 1
    q, r = divmod(abs(numerator), denominator)
    if 2 * r >= denominator:
        q += 1
    return sign * q


@dataclass(frozen=True)
class Money:
    minor: int
    currency: str

    def __post_init__(self) -> None:
        if isinstance(self.minor, bool) or not isinstance(self.minor, int):
            raise TypeError(f"Money.minor must be an int, got {type(self.minor).__name__}")
        if not (isinstance(self.currency, str) and len(self.currency) == 3 and self.currency.isupper()):
            raise ValueError(f"currency must be an ISO 4217 code, got {self.currency!r}")

    def _same(self, other: Money) -> None:
        if not isinstance(other, Money):
            raise TypeError("can only combine Money with Money")
        if other.currency != self.currency:
            raise ValueError(f"currency mismatch: {self.currency} vs {other.currency}")

    def __add__(self, other: Money) -> Money:
        self._same(other)
        return Money(self.minor + other.minor, self.currency)

    def __sub__(self, other: Money) -> Money:
        self._same(other)
        return Money(self.minor - other.minor, self.currency)

    def __neg__(self) -> Money:
        return Money(-self.minor, self.currency)

    def times(self, qty: int) -> Money:
        if isinstance(qty, bool) or not isinstance(qty, int):
            raise TypeError("quantity must be an int")
        return Money(self.minor * qty, self.currency)

    def mul_ratio(self, numerator: int, denominator: int) -> Money:
        return Money(div_round_half_up(self.minor * numerator, denominator), self.currency)

    def to_json(self) -> dict:
        return {"minor": self.minor, "currency": self.currency}

    @staticmethod
    def zero(currency: str) -> Money:
        return Money(0, currency)


def sum_money(items: list[Money], currency: str) -> Money:
    total = Money.zero(currency)
    for m in items:
        total = total + m
    return total


def round_outward(low: Money, high: Money, step_minor: int) -> tuple[Money, Money]:
    """Round a range outward so the displayed range always contains the computed one."""
    lo = (low.minor // step_minor) * step_minor
    hi = -((-high.minor) // step_minor) * step_minor
    return Money(lo, low.currency), Money(hi, high.currency)


def format_money(m: Money, decimals: bool = True) -> str:
    """Display format, e.g. $12,345.60 MXN. Formatting only; never parse this back."""
    sign = "-" if m.minor < 0 else ""
    whole, cents = divmod(abs(m.minor), 100)
    body = f"{whole:,}" + (f".{cents:02d}" if decimals else "")
    return f"{sign}${body} {m.currency}"
