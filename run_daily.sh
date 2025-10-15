#!/bin/bash

# Script d'exécution quotidienne du pipeline de données FreshKart
# Traite automatiquement les données de la veille

set -e  # Arrêt en cas d'erreur

# Calcul de la date de la veille (compatible Linux et macOS)
if date -v-1d &> /dev/null; then
    # macOS (BSD date)
    YESTERDAY=$(date -v-1d +%Y-%m-%d)
else
    # Linux (GNU date)
    YESTERDAY=$(date -d "yesterday" +%Y-%m-%d)
fi

# Détection automatique du répertoire du script
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Log de démarrage
echo "======================================"
echo "$(date '+%Y-%m-%d %H:%M:%S') - Démarrage du pipeline"
echo "Traitement de la date : $YESTERDAY"
echo "======================================"

# Vérification de l'existence du fichier JSON
ORDER_FILE="data/input/orders_${YESTERDAY}.json"

if [[ ! -f "$ORDER_FILE" ]]; then
    echo "ERREUR: Fichier $ORDER_FILE introuvable"
    echo "$(date '+%Y-%m-%d %H:%M:%S') - Pipeline annulé: données manquantes"
    exit 1
fi

# Exécution adaptative selon l'environnement (UV ou pip)
if command -v uv &> /dev/null && [ -f "pyproject.toml" ]; then
    echo "Utilisation de UV"
    uv run pipeline.py "$YESTERDAY"
elif [ -f ".venv/bin/activate" ]; then
    echo "Utilisation de venv"
    source .venv/bin/activate
    python pipeline.py "$YESTERDAY"
    deactivate
else
    echo "Avertissement : Aucun environnement virtuel détecté"
    python pipeline.py "$YESTERDAY"
fi

# Log de fin
echo "$(date '+%Y-%m-%d %H:%M:%S') - Pipeline terminé avec succès"
echo ""