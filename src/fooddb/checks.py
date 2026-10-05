"""Automatic checks run on every incoming record. They flag, they never fix."""

from collections.abc import Mapping


def flags(values: Mapping[str, float]) -> dict[str, set[str]]:
    """Values are per 100 g, keyed by INFOODS tagname. Each failed check names the fields it implicates.

    Carbohydrate is CHOCDF (by difference, fibre included) or CHOAVL (available, fibre excluded),
    whichever the record has. With CHOAVL, Atwater adds fibre at 2 kcal/g (EU 1169/2011 Annex XIV).
    """
    out: dict[str, set[str]] = {}
    carbs = "CHOAVL" if "CHOAVL" in values else "CHOCDF"
    macros = ("PROCNT", "FAT", carbs)
    kcal = values.get("ENERC_KCAL")
    p, f, c = values.get("PROCNT"), values.get("FAT"), values.get(carbs)
    fibre = values.get("FIBTG") if carbs == "CHOAVL" else None
    if kcal is not None and None not in (p, f, c):
        atwater = 4 * p + 9 * f + 4 * c + 2 * (fibre or 0)
        if abs(kcal - atwater) > max(20, 0.25 * max(kcal, atwater)):
            out["energy-mismatch"] = {"ENERC_KCAL", *macros} | ({"FIBTG"} if fibre is not None else set())
    if sum(v for v in (p, f, c) if v is not None) > 105:
        out["macros-over-100g"] = {k for k in macros if k in values}
    sugar, sat = values.get("SUGAR"), values.get("FASAT")
    if sugar is not None and c is not None and sugar > c + 0.5:
        out["sugars-over-carbs"] = {"SUGAR", carbs}
    if sat is not None and f is not None and sat > f + 0.5:
        out["saturates-over-fat"] = {"FASAT", "FAT"}
    if negative := {k for k, v in values.items() if v < 0}:
        out["negative-value"] = negative
    return out
