"""
Construction centralisee des liens Skyscanner.
"""


def _date_to_yymmdd(date_str):
    """Convertit YYYY-MM-DD en YYMMDD (ex: 2026-06-30 -> 260630)."""
    return date_str.replace("-", "")[2:] if date_str else ""


def build_skyscanner_url(deal):
    """
    Construit un lien Skyscanner public legacy a partir d'un dict vol.

    Format : /transport/flights/{origin}/{dest}/{YYMMDD}/{YYMMDD}/?params
    Champs attendus : origin, destination, depart_date, return_date.
    Si return_date est absent, genere un lien aller simple.
    """
    origin = (deal.get("origin", "") or "").lower()
    destination = (deal.get("destination", "") or "").lower()
    dep = _date_to_yymmdd(deal.get("depart_date", ""))
    ret = _date_to_yymmdd(deal.get("return_date", ""))

    path = f"{origin}/{destination}"
    if dep:
        path += f"/{dep}"
    if ret:
        path += f"/{ret}"

    params = "adultsv2=1&cabinclass=economy&market=CA&locale=fr-CA&currency=CAD"
    return f"https://www.skyscanner.ca/transport/flights/{path}/?{params}"
