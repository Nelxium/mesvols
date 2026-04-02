# === Configuration ===
# Remplace les valeurs ci-dessous par tes informations.

# Adresse Gmail qui ENVOIE les alertes
GMAIL_ADDRESS = "nelxium@gmail.com"

# Mot de passe d'application Gmail (pas ton mot de passe normal !)
# Genere-le ici : https://myaccount.google.com/apppasswords
GMAIL_APP_PASSWORD = "uggl pmdf lnwy elqg"

# Adresse(s) qui RECOIT les alertes (peut etre la meme)
ALERT_RECIPIENTS = ["nelxium@gmail.com"]

# Webhook Discord (pour recevoir les alertes dans un canal Discord)
DISCORD_WEBHOOK_URL = "https://discord.com/api/webhooks/1488734088725663837/u0tVEjCp72T8GVCo2M44VWf4iM_v_tyZoDKzLZt2ctfwEEw6ZVPt0_Z_H1hU3Uag6Pcx"

# Seuil de rabais pour declencher une alerte (0.40 = 40 %)
DEAL_THRESHOLD = 0.40

# URL de base du serveur (pour les liens /r/<deal_id> dans data.js)
BASE_URL = "http://localhost:8080"

# Routes a surveiller (depart, arrivee, nom affiche)
ROUTES = [
    ("YUL", "CDG", "Montreal -> Paris"),
    ("YUL", "CUN", "Montreal -> Cancun"),
    ("YUL", "NRT", "Montreal -> Tokyo Narita"),
    ("YUL", "HND", "Montreal -> Tokyo Haneda"),
    ("YUL", "PUJ", "Montreal -> Punta Cana"),
    ("YUL", "HNL", "Montreal -> Hawai"),
    ("YUL", "JFK", "Montreal -> New York"),
    ("YUL", "MIA", "Montreal -> Miami"),
]
