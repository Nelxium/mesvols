# MesVols - Configuration Task Scheduler Windows

## Creer la tache planifiee

1. Ouvrir **Task Scheduler** (Planificateur de taches)
   - Win+R > `taskschd.msc` > Entree

2. Cliquer **Create Basic Task** (panneau de droite)
   - Nom : `MesVols`
   - Description : `Scraping vols + publication GitHub Pages`

3. **Trigger** (declencheur)
   - Choisir **Daily**
   - Cocher **Repeat task every** : `30 minutes` (ou `6 hours` selon la frequence voulue)
   - Cocher **for a duration of** : `Indefinitely`

4. **Action**
   - Choisir **Start a program**
   - Programme : `C:\MesVols\run.bat`
   - Start in : `C:\MesVols`

5. **Finish** puis ouvrir les proprietes de la tache pour ajuster :

## Options recommandees (onglet General)

- Cocher **Run whether user is logged on or not** (optionnel, necessite mot de passe)
- Cocher **Run with highest privileges** (pas necessaire sauf problemes de permissions)

## Options recommandees (onglet Settings)

- Cocher **Allow task to be run on demand** (pour lancer manuellement)
- Cocher **Stop the task if it runs longer than** : `30 minutes`
- Cocher **If the task is already running, do not start a new instance**

## Options recommandees (onglet Conditions)

- Decocher **Start the task only if the computer is on AC power** (si laptop)

## Frequence recommandee

- **Toutes les 30 min** : ideal pour un dashboard "live" a jour
- **Toutes les 6h** : suffisant pour un suivi quotidien
- **Toutes les 2h** : bon compromis

Le scraping prend environ 3-5 minutes par run. Chaque run ne fait un push que s'il y a des changements dans les donnees.

## Verifier que ca marche

### Lancer manuellement

```
cd C:\MesVols
run.bat
```

Ou clic droit sur la tache > **Run**.

### Consulter les logs

Les logs sont dans `C:\MesVols\logs\` avec un fichier par jour :

```
logs\run_20260402.log
```

Chaque run est horodate avec le resultat de chaque etape.

### Codes de sortie

| Code | Signification |
|------|---------------|
| 0 | Succes (ou rien a publier) |
| 1 | Echec `main.py` (scraping) |
| 2 | Echec `publish.py` |
| 3 | Echec `git commit` |
| 4 | Echec `git push` |

Le code de sortie est visible dans Task Scheduler > colonne **Last Run Result**.

### Verifier dans Task Scheduler

- Colonne **Last Run Result** : `0x0` = succes
- Colonne **Last Run Time** : date du dernier run
- Onglet **History** : historique des executions
