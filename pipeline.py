"""
Pipeline de consolidation quotidienne des ventes FreshKart.

Traite les données de commandes, clients et remboursements pour produire :
- Un CSV quotidien avec agrégats par ville et canal
- Une base SQLite cumulative avec historique complet
"""

import json
import sqlite3
import sys

import pandas as pd


def load_data(
    date_str: str,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """
    Charge les 4 sources de données pour une date donnée.

    Args:
        date_str: Date au format YYYY-MM-DD

    Returns:
        Tuple de (df_customers, df_orders, df_items, df_refunds)
    """
    df_customers = pd.read_csv("data/input/customers.csv")

    with open(f"data/input/orders_{date_str}.json") as f:
        data = json.load(f)
    df_orders = pd.DataFrame(data)

    df_items = pd.json_normalize(
        data,
        record_path="items",
        meta=["order_id", "customer_id", "channel", "created_at", "payment_status"],
    )

    df_refunds = pd.read_csv("data/input/refunds.csv")

    return df_customers, df_orders, df_items, df_refunds


def clean_data(
    df_customers: pd.DataFrame,
    df_orders: pd.DataFrame,
    df_items: pd.DataFrame,
    date_str: str,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """
    Applique les règles métier de filtrage et nettoyage.

    - Garde uniquement clients actifs et commandes payées
    - Élimine les doublons sur order_id
    - Rejette les items avec prix négatif (exportés dans rejected_items_*.csv)

    Args:
        df_customers: Référentiel clients
        df_orders: Commandes du jour
        df_items: Lignes d'articles du jour
        date_str: Date pour nommage du fichier de rejets

    Returns:
        Tuple de (df_customers_clean, df_orders_clean, df_items_clean)
    """
    # Filtres
    df_customers = df_customers.query("is_active == True")

    df_orders = df_orders.query("payment_status == 'paid'")

    df_items = df_items.query("payment_status == 'paid'")

    # Doublons
    df_orders = df_orders.drop_duplicates(subset="order_id", keep="first")

    # Items au prix négatif
    df_items_clean = df_items.query("unit_price >= 0")
    df_items_rejected = df_items.query("unit_price < 0")

    if not df_items_rejected.empty:
        df_items_rejected.to_csv(
            f"data/out/rejected_items_{date_str}.csv",
            sep=";",
            decimal=".",
            index=False,
            encoding="utf-8",
        )
    else:
        print("NO REJECTED ITEMS")

    return df_customers, df_orders, df_items_clean


def enrich_and_calculate(
    df_items_clean: pd.DataFrame,
    df_customers: pd.DataFrame,
    df_refunds: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Enrichit les données et calcule les revenus par commande.

    - Ajoute la ville client à chaque article
    - Calcule line_total (qty x unit_price)
    - Agrège au niveau commande → gross_revenue
    - Intègre les remboursements → net_revenue

    Args:
        df_items_clean: Articles nettoyés
        df_customers: Clients actifs avec ville
        df_refunds: Historique complet des remboursements

    Returns:
        Tuple de (df_items_full, df_order_revenue)
    """
    # Enrichissement + Calcul de line_total
    df_items_full = df_items_clean.merge(
        df_customers[["customer_id", "city"]],
        on="customer_id",
        how="inner",
    ).assign(line_total=lambda df_: df_.qty * df_.unit_price)

    # Aggrégation par commande
    df_order_revenue = (
        df_items_full.groupby("order_id")
        .agg(
            {
                "line_total": "sum",
                "customer_id": "first",
                "channel": "first",
                "city": "first",
                "created_at": "first",
            }
        )
        .reset_index()
        .rename(columns={"line_total": "gross_revenue"})
    )

    # Préparation des refunds
    valid_orders = df_order_revenue.order_id.unique()  # noqa: F841
    df_refunds_agg = (
        df_refunds.query("order_id.isin(@valid_orders)")
        .groupby("order_id")
        .agg({"amount": "sum"})
        .reset_index()
        .rename(columns={"amount": "refunds_amount"})
    )

    # Jointure finale et calculs
    df_order_revenue = df_order_revenue.merge(
        df_refunds_agg, on="order_id", how="left"
    ).assign(
        refunds_amount=lambda df_: df_.refunds_amount.fillna(0),
        net_revenue=lambda df_: df_.gross_revenue + df_.refunds_amount,
    )

    return df_items_full, df_order_revenue


def aggregate_daily(
    df_order_revenue: pd.DataFrame, df_items_full: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Agrège les métriques par ville, canal et date.

    Calcule pour chaque combinaison (date, city, channel) :
    - orders_count, unique_customers, items_sold
    - gross_revenue_eur, refunds_eur, net_revenue_eur

    Args:
        df_order_revenue: Revenus par commande
        df_items_full: Articles enrichis (pour items_sold)

    Returns:
        Tuple de (df_daily_summary, df_order_revenue enrichi avec date et items_sold)
    """
    df_order_revenue["date"] = pd.to_datetime(
        df_order_revenue.created_at
    ).dt.date  # Complainte Pylance alors que ça fonctionne...

    df_items_count = (
        df_items_full.groupby("order_id")
        .qty.sum()
        .reset_index()
        .rename(columns={"qty": "items_sold"})
    )

    df_order_revenue = pd.merge(
        left=df_order_revenue, right=df_items_count, on="order_id", how="left"
    )

    df_daily_summary = (
        df_order_revenue.groupby(["date", "city", "channel"])
        .agg(
            {
                "order_id": "count",
                "customer_id": "nunique",
                "items_sold": "sum",
                "gross_revenue": "sum",
                "refunds_amount": "sum",
                "net_revenue": "sum",
            }
        )
        .reset_index()
        .rename(
            columns={
                "order_id": "orders_count",
                "customer_id": "unique_customers",
                "gross_revenue": "gross_revenue_eur",
                "refunds_amount": "refunds_eur",
                "net_revenue": "net_revenue_eur",
            }
        )
    )

    return df_daily_summary, df_order_revenue


def export_results(
    df_daily_summary: pd.DataFrame, df_order_revenue: pd.DataFrame, date_str: str
) -> None:
    """
    Exporte les résultats en CSV et SQLite.

    - CSV : daily_summary_{date_str}.csv (séparateur ';')
    - SQLite : Append dans sales.db (tables orders_clean et daily_city_sales)

    Args:
        df_daily_summary: Agrégats quotidiens
        df_order_revenue: Détails par commande
        date_str: Date pour nommage du CSV
    """
    df_daily_summary.to_csv(
        f"data/out/daily_summary_{date_str}.csv",
        sep=";",
        decimal=".",
        index=False,
        encoding="utf-8",
    )

    conn = sqlite3.connect("data/out/sales.db")

    # Table 1 : détails par commande
    df_order_revenue.to_sql("orders_clean", conn, if_exists="append", index=False)

    # Table 2 : agrégats
    df_daily_summary.to_sql("daily_city_sales", conn, if_exists="append", index=False)

    conn.close()

    print("✓ sales.db updatée")


def main(date_str):
    """
    Exécute le pipeline complet pour une date donnée.

    Args:
        date_str: Date à traiter au format YYYY-MM-DD
    """
    print(f"Traitement du {date_str}...")

    # 1. Chargement
    df_customers, df_orders, df_items, df_refunds = load_data(date_str)

    # 2. Nettoyage
    df_customers, df_orders, df_items_clean = clean_data(
        df_customers, df_orders, df_items, date_str
    )

    # 3-4. Enrichissement et calculs
    df_items_full, df_order_revenue = enrich_and_calculate(
        df_items_clean, df_customers, df_refunds
    )

    # 5. Agrégation
    df_daily_summary, df_order_revenue = aggregate_daily(
        df_order_revenue, df_items_full
    )

    # 6. Export
    export_results(df_daily_summary, df_order_revenue, date_str)

    print(f"✓ Pipeline terminé pour {date_str}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python pipeline.py YYYY-MM-DD")
        sys.exit(1)

    date_str = sys.argv[1]

    # Validation du format date
    try:
        pd.to_datetime(date_str)
    except ValueError:
        print(f"Erreur: '{date_str}' n'est pas une date (format attendu: YYYY-MM-DD)")
        sys.exit(1)

    main(date_str)
