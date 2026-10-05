"""Automatic checks run on every incoming record. They flag, they never fix."""

from collections.abc import Mapping


def flags(values: Mapping[str, float]) -> list[str]:
    """Values are per 100 g, keyed by INFOODS tagname."""
    out: list[str] = []
    kcal = values.get("ENERC_KCAL")
    p, f, c = values.get("PROCNT"), values.get("FAT"), values.get("CHOCDF")
    if kcal is not None and None not in (p, f, c):
        atwater = 4 * p + 9 * f + 4 * c
        if abs(kcal - atwater) > max(20, 0.25 * max(kcal, atwater)):
            out.append("energy-mismatch")
    if sum(v for v in (p, f, c) if v is not None) > 105:
        out.append("macros-over-100g")
    sugar, sat = values.get("SUGAR"), values.get("FASAT")
    if sugar is not None and c is not None and sugar > c + 0.5:
        out.append("sugars-over-carbs")
    if sat is not None and f is not None and sat > f + 0.5:
        out.append("saturates-over-fat")
    if any(v < 0 for v in values.values()):
        out.append("negative-value")
    return out
