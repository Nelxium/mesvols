"""
Analyse les prix historiques et detecte les aubaines.
Un prix est une aubaine s'il est >= DEAL_THRESHOLD sous la moyenne historique.
Les vols directs sont mieux cotes que les vols avec escales.
"""

import csv
import os
from collections import defaultdict

from config import DEAL_THRESHOLD

CSV_FILE = os.path.join(os.path.dirname(__file__), "prix_vols.csv")
MIN_DATAPOINTS = 3  # Minimum de prix historiques avant de comparer


def parse_stops(stops_str):
    """Retourne le nombre d'escales a partir du champ stops.

    Regle unique : meme logique que stopT() du frontend.
    Reconnait "Direct", "direct", "sans escale", "nonstop", "0".
    Fallback = 1 avec avertissement (jamais silencieux).
    """
    if not stops_str:
        return 0
    s = stops_str.strip().lower()
    if s in ("direct", "sans escale", "nonstop", "non-stop", "0"):
        return 0
    import re
    m = re.match(r"^(\d+)", s)
    if m:
        return int(m.group(1))
    print(f"  WARNING parse_stops: format inconnu '{stops_str}', fallback=1")
    return 1


ERROR_FARE_THRESHOLD = 0.60  # Rabais >= 60% = erreur de prix possible


def compute_score(price, avg, num_stops, hist_min=None):
    """
    Note un vol de 1 a 5 selon le prix relatif et les escales.
    Prix bas = 20%+ sous la moyenne (ratio <= 0.80).
    Proche du min historique = bonus d'une etoile (si aussi prix bas).
    """
    if avg and avg > 0:
        ratio = price / avg
        prix_bas = ratio <= 0.80
    else:
        prix_bas = False

    # Score de base selon escales + prix
    if num_stops == 0:
        if prix_bas:
            score = 5  # direct + prix bas
        else:
            score = 4  # direct + prix normal
    elif num_stops == 1:
        if prix_bas:
            score = 4  # 1 escale + prix bas
        else:
            score = 3  # 1 escale + prix normal
    else:
        score = 2  # 2+ escales = 2 max

    # Bonus : proche du min historique ET prix bas -> garantir 5
    if hist_min and hist_min > 0 and price <= hist_min * 1.05 and prix_bas:
        score = 5

    return score


def load_history():
    """Charge l'historique des prix depuis le CSV."""
    history = defaultdict(list)

    if not os.path.isfile(CSV_FILE):
        return history

    with open(CSV_FILE, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            route = row.get("route", "")
            try:
                # Nouveau format: price_google + price_skyscanner
                # Ancien format: price_cad
                pg = row.get("price_google") or row.get("price_cad", "")
                price_g = int(pg) if pg else None
                ps = row.get("price_skyscanner", "")
                price_s = int(ps) if ps else None
                # Prix effectif = le plus bas des deux
                prices = [p for p in (price_g, price_s) if p]
                if prices:
                    history[route].append(min(prices))
            except (ValueError, KeyError):
                continue

    return history


def compute_averages(history):
    """Calcule la moyenne des prix pour chaque route."""
    averages = {}
    for route, prices in history.items():
        if prices:
            averages[route] = sum(prices) / len(prices)
    return averages


def compute_minimums(history):
    """Calcule le prix minimum historique pour chaque route."""
    minimums = {}
    for route, prices in history.items():
        if prices:
            minimums[route] = min(prices)
    return minimums


def find_deals(current_results):
    """
    Compare les prix actuels avec la moyenne et le minimum historique.
    Retourne une liste d'aubaines detectees.
    """
    history = load_history()
    averages = compute_averages(history)
    minimums = compute_minimums(history)
    deals = []

    for result in current_results:
        route = result["route"]
        # Prix effectif = le plus bas entre Google et Skyscanner
        price_g = result.get("price_google") or result.get("price_cad", 0)
        price_s = result.get("price_skyscanner")
        if isinstance(price_g, str):
            price_g = int(price_g) if price_g else 0
        if isinstance(price_s, str):
            price_s = int(price_s) if price_s else None
        price = min(price_g, price_s) if price_s else price_g
        avg = averages.get(route)
        hist_min = minimums.get(route)
        stops_str = result.get("stops", "")
        num_stops = parse_stops(stops_str)
        stops_label = "Direct" if num_stops == 0 else f"{num_stops} escale(s)"

        if avg is None:
            count = len(history.get(route, []))
            print(f"  {route}: {price} $ CAD [{stops_label}] — pas assez d'historique "
                  f"({count}/{MIN_DATAPOINTS} points)")
            continue

        count = len(history[route])
        if count < MIN_DATAPOINTS:
            print(f"  {route}: {price} $ CAD [{stops_label}] — seulement {count} points "
                  f"(min {MIN_DATAPOINTS}), on attend...")
            continue

        pct_below = (avg - price) / avg
        near_minimum = hist_min and price <= hist_min * 1.05
        score = compute_score(price, avg, num_stops, hist_min)
        status = ""

        # Detection d'aubaine
        is_deal = pct_below >= DEAL_THRESHOLD
        # Bonus vol direct : seuil reduit de 25%
        if not is_deal and num_stops == 0 and pct_below >= (DEAL_THRESHOLD * 0.75):
            is_deal = True
        # Proche du minimum historique = aubaine automatique
        if not is_deal and near_minimum and count >= MIN_DATAPOINTS:
            is_deal = True

        # Detection error fare (rabais >= 60%)
        is_error_fare = pct_below >= ERROR_FARE_THRESHOLD

        if is_deal:
            status = " *** AUBAINE ! ***"
            if is_error_fare:
                status = " *** ERREUR DE PRIX POSSIBLE ! ***"
            elif num_stops == 0:
                status += " (VOL DIRECT)"
            elif near_minimum:
                status += " (PROCHE DU MINIMUM)"

            deals.append({
                "route": route,
                "price": price,
                "average": round(avg, 2),
                "hist_min": hist_min,
                "discount_pct": round(pct_below * 100, 1),
                "airline": result.get("airline", "Inconnue"),
                "stops": stops_label,
                "num_stops": num_stops,
                "score": score,
                "error_fare": is_error_fare,
                "near_minimum": near_minimum,
                "origin": result.get("origin", ""),
                "destination": result.get("destination", ""),
                "depart": result.get("depart", ""),
                "retour": result.get("retour", ""),
            })

        min_info = f", min: {hist_min} $" if hist_min else ""
        print(f"  {route}: {price} $ CAD [{stops_label}] (moyenne: {avg:.0f} ${min_info}, "
              f"{'%.1f' % (pct_below * 100)}% sous la moyenne, score: {score}/5){status}")

    # Trier : error fares d'abord, puis score decroissant
    deals.sort(key=lambda d: (not d["error_fare"], -d["score"], d["num_stops"], d["price"]))

    return deals
