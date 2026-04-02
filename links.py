"""
Construction centralisee des liens de recherche vol.
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


def build_united_search_url(origin, dest, depart_date, return_date):
    """Recherche pre-remplie sur united.com."""
    return (
        f"https://www.united.com/en/us/fsr/choose-flights"
        f"?tt=RT&f={origin}&t={dest}&d={depart_date}&r={return_date}&px=1"
    )


def build_kayak_search_url(origin, dest, depart_date, return_date):
    """Recherche pre-remplie sur kayak.com."""
    return (
        f"https://ca.kayak.com/flights/{origin}-{dest}"
        f"/{depart_date}/{return_date}?sort=bestflight_a"
    )


def build_search_link(origin, dest, depart_date, return_date, airline_code=""):
    """
    Retourne (search_url, search_label) selon la compagnie.
    UA -> united.com, sinon -> kayak.com.
    """
    if airline_code == "UA":
        return (
            build_united_search_url(origin, dest, depart_date, return_date),
            "Rechercher sur united.com",
        )
    return (
        build_kayak_search_url(origin, dest, depart_date, return_date),
        "Rechercher sur ca.kayak.com",
    )
