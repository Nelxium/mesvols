"""
MesVols - Serveur local
Sert le dashboard sur le réseau local (port 8080).
Accès depuis téléphone sur le même WiFi.
"""

import http.server
import socket
import os
import sys

PORT = 8080
DOSSIER = os.path.dirname(os.path.abspath(__file__))


class MesVolsHandler(http.server.SimpleHTTPRequestHandler):
    """Sert le dashboard + endpoint /r/<deal_id> pour les redirections reservation."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=DOSSIER, **kwargs)

    def do_GET(self):
        if self.path.startswith("/r/"):
            self._handle_reserve()
            return
        if self.path == "/" or self.path == "":
            ua = self.headers.get("User-Agent", "")
            if "Mobile" in ua or "iPhone" in ua:
                self.path = "/dashboard-mobile.html"
            else:
                self.path = "/dashboard-mesvols.html"
        return super().do_GET()

    def _handle_reserve(self):
        """302 vers l'URL capturee si fraiche, sinon fallback Skyscanner."""
        deal_id = self.path[3:].split("?")[0]
        target = self._resolve_url(deal_id)
        self.send_response(302)
        self.send_header("Location", target)
        self.end_headers()

    def _resolve_url(self, deal_id):
        """Ne doit JAMAIS lever d'exception — toujours retourner une URL."""
        try:
            from booking_capture import load_deals, is_fresh
            from links import build_skyscanner_url

            deals = load_deals()
            deal = deals.get(deal_id)

            # Lien capture frais → redirection directe
            if deal and deal.get("success") and deal.get("final_url") and is_fresh(deal):
                return deal["final_url"]

            # Deal connu mais pas frais → fallback Skyscanner avec ses champs
            if deal:
                return build_skyscanner_url({
                    "origin": deal.get("origin", ""),
                    "destination": deal.get("destination", ""),
                    "depart_date": deal.get("depart", ""),
                    "return_date": deal.get("retour", ""),
                    "airline_code": deal.get("airline_code", ""),
                })

            # deal_id inconnu → parser le deal_id pour extraire les champs
            # Format: ORIGIN-DEST-DEPDATE-RETDATE-CODE
            parts = deal_id.split("-")
            if len(parts) >= 4:
                dep_raw, ret_raw = parts[2], parts[3]
                dep = f"{dep_raw[:4]}-{dep_raw[4:6]}-{dep_raw[6:8]}" if len(dep_raw) == 8 else ""
                ret = f"{ret_raw[:4]}-{ret_raw[4:6]}-{ret_raw[6:8]}" if len(ret_raw) == 8 else ""
                code = parts[4] if len(parts) >= 5 else ""
                return build_skyscanner_url({
                    "origin": parts[0], "destination": parts[1],
                    "depart_date": dep, "return_date": ret,
                    "airline_code": code,
                })
        except Exception:
            pass

        return "https://www.skyscanner.ca"

    def log_message(self, format, *args):
        # Log simplifié
        print(f"  {args[0]}")


def get_ip_locale():
    """Trouve l'IP locale de l'ordi sur le WiFi."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


if __name__ == "__main__":
    ip = get_ip_locale()

    print()
    print("=" * 50)
    print("  MesVols - Serveur local")
    print("=" * 50)
    print()
    print(f"  Sur cet ordi :  http://localhost:{PORT}")
    print(f"  Sur ton cell :  http://{ip}:{PORT}")
    print()
    print("  (meme WiFi requis)")
    print("  Ctrl+C pour arreter")
    print("=" * 50)
    print()

    try:
        serveur = http.server.HTTPServer(("0.0.0.0", PORT), MesVolsHandler)
        serveur.serve_forever()
    except KeyboardInterrupt:
        print("\nServeur arrete.")
        serveur.server_close()
    except OSError as e:
        if "10048" in str(e) or "Address already in use" in str(e):
            print(f"\nERREUR : Le port {PORT} est deja utilise.")
            print("Ferme l'autre serveur ou change le port.")
        else:
            print(f"\nERREUR : {e}")
        sys.exit(1)
