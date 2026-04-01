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
    """Redirige / vers le dashboard."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=DOSSIER, **kwargs)

    def do_GET(self):
        if self.path == "/" or self.path == "":
            ua = self.headers.get("User-Agent", "")
            if "Mobile" in ua or "iPhone" in ua:
                self.path = "/dashboard-mobile.html"
            else:
                self.path = "/dashboard-mesvols.html"
        return super().do_GET()

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
