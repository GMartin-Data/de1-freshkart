# FreshKart - Pipeline de consolidation des ventes

Pipeline ETL quotidien pour traiter et agréger les données de ventes par ville et canal.

## 📋 Prérequis

- Python 3.12+
- UV (recommandé) ou pip/venv
- SQLite3
- Accès cron (Linux/macOS) ou Task Scheduler (Windows)

## 🚀 Installation

### Option 1 : Avec UV (recommandé)

```bash
# Cloner le projet
git clone https://github.com/GMartin-Data/de1-freshkart.git
cd freshkart-pipeline

# Initialiser avec UV
uv sync

# Créer les dossiers nécessaires
mkdir -p data/input data/output data/out logs
```

### Option 2 : Avec pip/venv

```bash
# Cloner le projet
git clone <repo-url>
cd freshkart-pipeline

# Créer et activer l'environnement virtuel
python -m venv .venv
source .venv/bin/activate  # Linux/macOS
# ou .venv\Scripts\activate  # Windows

# Installer les dépendances
pip install pandas

# Créer les dossiers nécessaires
mkdir -p data/input data/out logs
```

## 📁 Structure des données

Placez vos fichiers sources dans `data/input/` :

```
data/input/
├── customers.csv              # Référentiel clients (ville, statut actif)
├── refunds.csv                # Historique des remboursements
└── orders_YYYY-MM-DD.json     # Commandes quotidiennes avec articles
```

**Format attendu** :

- `customers.csv` : customer_id, first_name, last_name, email, city, is_active
- `refunds.csv` : refund_id, order_id, amount, reason, created_at
- `orders_*.json` : order_id, customer_id, channel, created_at, payment_status, items[]

## 💻 Utilisation

### Exécution manuelle

```bash
# Avec UV
uv run pipeline.py <YYYY-MM-DD>

# Avec venv
source .venv/bin/activate
python pipeline.py <YYYY-MM-DD>
```

### Automatisation quotidienne (Linux/macOS)

```bash
# Rendre le script exécutable
chmod +x run_daily.sh

# Tester manuellement
./run_daily.sh

# Configurer le cron (6h du matin, timezone Paris)
crontab -e

# Ajouter cette ligne :
TZ=Europe/Paris
0 6 * * * cd $HOME/freshkart-pipeline && ./run_daily.sh >> logs/pipeline.log 2>&1
```

**Le script `run_daily.sh` :**

- Calcule automatiquement la date de la veille (J-1)
- Vérifie l'existence des fichiers requis
- Détecte automatiquement l'environnement (UV ou venv)
- Log toutes les exécutions dans `logs/pipeline.log`

## 📊 Règles métier appliquées

1. **Clients** : Uniquement les clients actifs (`is_active = true`)
2. **Commandes** : Uniquement les commandes payées (`payment_status = 'paid'`)
3. **Articles** : Rejet des prix unitaires négatifs (loggés dans `rejected_items_*.csv`)
4. **Déduplication** : Première occurrence conservée en cas de doublon sur `order_id`
5. **Remboursements** : Montants négatifs agrégés par commande

## 📤 Outputs générés

```
data/out/
├── daily_summary_YYYYMMDD.csv       # Agrégats par ville/canal (CSV principal)
├── rejected_items_YYYYMMDD.csv      # Items rejetés (si prix négatifs)
└── sales.db                         # Base SQLite cumulative
    ├── orders_clean                 # Détails par commande
    └── daily_city_sales             # Agrégats quotidiens

logs/
└── pipeline.log                     # Historique d'exécution
```

### Format du CSV quotidien

Colonnes : `date;city;channel;orders_count;unique_customers;items_sold;gross_revenue_eur;refunds_eur;net_revenue_eur`

Exemple :

```csv
date;city;channel;orders_count;unique_customers;items_sold;gross_revenue_eur;refunds_eur;net_revenue_eur
2025-03-01;Paris;web;7;7;53;776.8;-6.76;770.04
2025-03-01;Lyon;app;7;7;62;730.3;-10.86;719.44
```

## 🔍 Vérification

```bash
# Vérifier les fichiers générés
ls -lh data/out/

# Inspecter la base SQLite
sqlite3 data/out/sales.db "SELECT COUNT(*) FROM orders_clean;"
sqlite3 data/out/sales.db "SELECT * FROM daily_city_sales ORDER BY date DESC LIMIT 5;"

# Consulter les logs
tail -f logs/pipeline.log
```

## 🛠️ Développement

### Architecture du pipeline

```
1. CHARGEMENT    → Lecture des fichiers sources
2. NETTOYAGE     → Application des règles métier + filtres
3. ENRICHISSEMENT → Jointure avec ville client
4. CALCULS       → Revenus bruts/nets par commande
5. AGRÉGATION    → Métriques par ville/canal/date
6. EXPORT        → CSV quotidien + SQLite cumulatif
```

### Exploration initiale

Voir le notebook Jupyter `exploration.ipynb` pour le processus de développement et les analyses exploratoires.

### Linter et formatage

```bash
# Formater le code
ruff format pipeline.py

# Vérifier le code
ruff check pipeline.py
```

## ⚠️ Gestion des erreurs

Le pipeline s'arrête et log les erreurs dans les cas suivants :

- Fichier `orders_YYYY-MM-DD.json` introuvable pour la date demandée
- Fichiers `customers.csv` ou `refunds.csv` manquants
- Format de date invalide (attendu : YYYY-MM-DD)
- Erreur d'exécution Python

Consultez `logs/pipeline.log` pour diagnostiquer les problèmes.

## 📝 Notes techniques

- **Dénormalisation** : Les items incluent directement les métadonnées de commande pour optimiser les jointures
- **Refunds** : Filtrés sur les order_id valides avant agrégation (optimisation performance)
- **SQLite** : Mode append pour accumulation historique (attention aux doublons si re-exécution)
- **Net revenue négatif** : Possible si remboursements > commande (gestes commerciaux exceptionnels)
