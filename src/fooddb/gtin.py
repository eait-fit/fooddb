"""GTIN normalisation: every barcode is stored as a check-digit-valid GTIN-14."""

NOT_GLOBAL = {"02", "04", "05", "98", "99", *(str(n) for n in range(20, 30))}


def check_digit(body: str) -> int:
    """GS1 mod-10 check digit for the digits before it."""
    total = sum(int(d) * (3 if i % 2 == 0 else 1) for i, d in enumerate(reversed(body)))
    return (10 - total % 10) % 10


def normalize(code: str | None) -> str | None:
    """GTIN-8/12/13/14 → GTIN-14, or None when it is not a valid global GTIN.

    Numbers that are not global trade items return None too: GS1 restricted
    circulation (GTIN-13 prefixes 02, 04, 20–29) and coupons (05, 98, 99).
    """
    if not code:
        return None
    digits = code.strip()
    if not (digits.isascii() and digits.isdigit()) or len(digits) not in (8, 12, 13, 14):
        return None
    gtin14 = digits.zfill(14)
    if check_digit(gtin14[:-1]) != int(gtin14[-1]):
        return None
    gtin13 = gtin14[1:]
    if gtin13[:2] in NOT_GLOBAL:
        return None
    return gtin14
