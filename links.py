"""
Construction centralisee des liens Skyscanner.
"""


def build_skyscanner_url(deal):
    """
    Construit un lien Skyscanner day-view a partir d'un dict vol.

    Champs attendus : origin, destination, depart_date, return_date, airline_code.
    Si un champ manque, genere le meilleur lien possible sans ce champ.
    airline_code accepte un code IATA (AC) ou plusieurs separes par virgule (AC,LH).
    """
    base = "https://www.skyscanner.ca/transport/flights/day-view"
    params = []

    origin = deal.get("origin", "")
    destination = deal.get("destination", "")
    depart_date = deal.get("depart_date", "")
    return_date = deal.get("return_date", "")
    airline_code = deal.get("airline_code", "")

    if origin:
        params.append(f"origin={origin.upper()}")
    if destination:
        params.append(f"destination={destination.upper()}")
    if depart_date:
        params.append(f"outboundDate={depart_date}")
    if return_date:
        params.append(f"inboundDate={return_date}")
    if airline_code:
        params.append(f"airlines={airline_code}")

    params.extend([
        "cabinclass=economy",
        "adultsv2=1",
        "market=CA",
        "locale=fr-CA",
        "currency=CAD",
    ])

    return f"{base}?{'&'.join(params)}"
