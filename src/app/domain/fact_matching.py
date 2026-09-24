"""Exact-match comparison of raw extracted fact strings.

Deliberately no fuzzy tolerance on money or dates: the verification standard's
own worst near-miss (UCL claimed £13,000, real £16,750) is exactly the kind of
"close enough" figure a tolerant comparison would wrongly treat as agreement.
Two facts either state the same value or they don't corroborate each other.

Two faults were found by the Edufurther Agent's first real run against
live pages, in its verbatim copy of this module, and are fixed here too.
The agent's copy is the reference; keep the two in step.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

#: A currency symbol, or an ISO code, before or after the number. The
#: original read symbols only, so "EUR 992" and "GBP 10,000" - how most
#: official pages we actually fetch write it - parsed to nothing.
_AMOUNT_PATTERN = re.compile(
    r"^(?:(?P<sym>[£$€])\s?(?P<a>[\d,]+(?:\.\d+)?)"
    r"|(?P<code>[A-Z]{3})\s?(?P<b>[\d,]+(?:\.\d+)?)"
    r"|(?P<c>[\d,]+(?:\.\d+)?)\s?(?P<code2>[A-Z]{3}))$"
)
#: ISO codes normalised onto their symbol so "EUR 992" and "€992" are the
#: same value rather than two currencies that never corroborate.
_CURRENCY_ALIASES = {"GBP": "£", "USD": "$", "EUR": "€"}
_ORDINAL_SUFFIX = re.compile(r"(\d+)(?:st|nd|rd|th)", re.IGNORECASE)
#: Both orders, and abbreviated month names. One format meant a date
#: written the way most of the world writes it did not parse at all.
_DEADLINE_FORMATS = ("%B %d %Y", "%d %B %Y", "%b %d %Y", "%d %b %Y", "%Y-%m-%d", "%d/%m/%Y")


def parse_amount(raw: str) -> tuple[str, Decimal] | None:
    """`"£13,000"` / `"EUR 992"` -> `(symbol, Decimal)`, or None."""
    match = _AMOUNT_PATTERN.match(raw.strip())
    if not match:
        return None
    parts = match.groupdict()
    currency = parts["sym"] or parts["code"] or parts["code2"] or ""
    digits = parts["a"] or parts["b"] or parts["c"] or ""
    currency = _CURRENCY_ALIASES.get(currency, currency)
    try:
        return currency, Decimal(digits.replace(",", ""))
    except InvalidOperation:
        return None


def amounts_match(a: str, b: str) -> bool | None:
    """None when either side cannot be read - which is not disagreement.

    This returned False for an unparseable value, conflating "I cannot
    read this" with "these differ". False on a deadline or an amount is
    what drives REJECT_RECOMMENDED, so an unrecognised date format was a
    rejection waiting to happen: `deadlines_match` called two identical
    "1 June 2026" strings a contradiction, because it only ever understood
    "June 1 2026".
    """
    parsed_a = parse_amount(a)
    parsed_b = parse_amount(b)
    if parsed_a is None or parsed_b is None:
        return None
    return parsed_a == parsed_b


def parse_deadline(raw: str) -> date | None:
    """`"March 15, 2026"` / `"March 15th 2026"` -> `date(2026, 3, 15)`."""
    cleaned = _ORDINAL_SUFFIX.sub(r"\1", raw.strip()).replace(",", "")
    for fmt in _DEADLINE_FORMATS:
        try:
            return datetime.strptime(cleaned, fmt).date()
        except ValueError:
            continue
    return None


def deadlines_match(a: str, b: str) -> bool | None:
    """None when either side cannot be read. See `amounts_match`."""
    parsed_a = parse_deadline(a)
    parsed_b = parse_deadline(b)
    if parsed_a is None or parsed_b is None:
        return None
    return parsed_a == parsed_b
