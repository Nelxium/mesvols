# MesVols - Detecteur de Vols Pas Chers

Projet Python qui scrape Google Flights pour trouver des vols aller-retour pas chers au depart de Montreal (YUL) vers Paris, Cancun, Barcelone, Bangkok et Tokyo.

## Fonctionnalites

- Scraping automatique des prix via Selenium + Google Flights
- Sauvegarde des prix dans un fichier CSV (historique)
- Detection d'aubaines : alerte quand un prix est 40%+ sous la moyenne historique
- Notification par email via Gmail

## Prerequis

- Python 3.9+
- Google Chrome installe sur ta machine

## Installation

```bash
cd C:\MesVols
pip install -r requirements.txt
```

## Configuration Gmail

1. Va sur https://myaccount.google.com/security
2. Active la **verification en 2 etapes** si ce n'est pas deja fait
3. Va sur https://myaccount.google.com/apppasswords
4. Cree un mot de passe d'application (choisis "Courrier" et "Ordinateur Windows")
5. Copie le mot de passe genere (16 caracteres, ex: `abcd efgh ijkl mnop`)
6. Ouvre `config.py` et remplace les valeurs :

```python
GMAIL_ADDRESS = "ton.email@gmail.com"
GMAIL_APP_PASSWORD = "abcd efgh ijkl mnop"
ALERT_RECIPIENTS = ["ton.email@gmail.com"]
```

## Utilisation

### Lancer une recherche manuelle

```bash
python main.py
```

### Lancer seulement le scraper (sans analyse)

```bash
python scraper.py
```

### Automatiser avec le Planificateur de taches Windows

1. Ouvre le **Planificateur de taches** (Task Scheduler)
2. Cree une tache de base
3. Programme : `python`
4. Arguments : `C:\MesVols\main.py`
5. Repeter tous les jours (ou toutes les 12h pour plus de chances)

## Fichiers

| Fichier | Role |
|---|---|
| `config.py` | Configuration (email, routes, seuil) |
| `scraper.py` | Scraping Google Flights avec Selenium |
| `analyzer.py` | Comparaison des prix avec la moyenne historique |
| `notifier.py` | Envoi d'alertes email via Gmail |
| `main.py` | Point d'entree (scrape + analyse + alerte) |
| `prix_vols.csv` | Historique des prix (genere automatiquement) |
| `requirements.txt` | Dependances Python |

## Comment ca marche

1. Le scraper ouvre Google Flights en mode headless (sans fenetre)
2. Il cherche des vols aller-retour dans ~30 jours pour chaque route
3. Le prix le plus bas est sauvegarde dans `prix_vols.csv`
4. L'analyseur compare le prix actuel avec la moyenne de tous les prix precedents
5. Si le prix est 40%+ en dessous de la moyenne -> email d'alerte !

## Notes

- Les 3 premieres executions servent a accumuler de l'historique (pas d'alerte)
- Google peut bloquer le scraping si tu lances trop souvent. 1-2 fois par jour est raisonnable
- Le seuil de 40% est configurable dans `config.py` (`DEAL_THRESHOLD`)
