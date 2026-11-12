"""Generate the synthetic sample datasets (seeded, so the output is reproducible).

python samples/make_samples.py
"""

from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).parent
rng = np.random.default_rng(42)


def sales(n: int = 1000) -> pd.DataFrame:
    dates = pd.Timestamp("2024-01-01") + pd.to_timedelta(rng.integers(0, 730, n), unit="D")
    units = rng.poisson(3, n) + 1
    price = np.round(rng.lognormal(3.2, 0.6, n), 2)
    price[rng.choice(n, 15, replace=False)] *= 20  # a few extreme prices
    discount = np.where(rng.random(n) < 0.25, np.nan, rng.choice([0, 5, 10, 15, 20], n))
    df = pd.DataFrame(
        {
            "order_id": np.arange(100001, 100001 + n),
            "order_date": dates.strftime("%Y-%m-%d"),
            "region": rng.choice(
                ["North", "South", "East", "West", "Central"], n, p=[0.3, 0.2, 0.2, 0.2, 0.1]
            ),
            "category": rng.choice(["Electronics", "Books", "Home", "Toys", "Sports", "Beauty"], n),
            "units": units,
            "unit_price": price,
            "discount_pct": discount,
            "rating": np.where(rng.random(n) < 0.1, np.nan, rng.integers(1, 6, n)),
            "returning_customer": rng.choice([True, False], n, p=[0.4, 0.6]),
            "currency": "USD",
        }
    )
    df["revenue"] = np.round(df.units * df.unit_price * (1 - df.discount_pct.fillna(0) / 100), 2)
    df.loc[rng.choice(n, 40, replace=False), "region"] = np.nan
    return pd.concat([df, df.sample(5, random_state=1)], ignore_index=True)  # 5 duplicate rows


def tr_survey(n: int = 300) -> pd.DataFrame:
    """Shaped like an export from Excel in a Turkish locale: ';', cp1254, decimal comma, dd.mm.yyyy."""
    comments = [
        "Hizmetten çok memnunum",
        "Fiyatlar biraz yüksek",
        "Teslimat geç kaldı",
        "Personel ilgiliydi",
        "Ürün çeşitliliği az",
        "Tekrar alışveriş yaparım",
    ]
    dates = pd.Timestamp("2025-03-01") + pd.to_timedelta(rng.integers(0, 45, n), unit="D")
    return pd.DataFrame(
        {
            "şehir": rng.choice(["İstanbul", "Ankara", "İzmir", "Bursa", "Antalya", "Eskişehir"], n),
            "yaş": rng.integers(18, 70, n),
            "aylık_gelir": np.round(rng.normal(35000, 9000, n), 2),
            "memnuniyet": rng.integers(1, 6, n),
            "cinsiyet": rng.choice(["Kadın", "Erkek", "Belirtmek istemiyor"], n, p=[0.48, 0.48, 0.04]),
            "anket_tarihi": dates.strftime("%d.%m.%Y"),
            "yorum": [f"{rng.choice(comments)} (#{i})" for i in range(n)],
        }
    )


def opt_production() -> pd.DataFrame:
    """A furniture workshop: profit per unit, resource use per unit and demand limits."""
    return pd.DataFrame(
        [
            ("Chair", 45, 1.5, 2.0, 4, 20, 200),
            ("Table", 120, 4.0, 5.0, 15, 5, 60),
            ("Desk", 150, 5.0, 6.0, 18, 0, 40),
            ("Bookshelf", 95, 3.0, 4.0, 12, 0, 80),
            ("Bed", 210, 6.0, 8.0, 25, 0, 30),
            ("Stool", 25, 0.8, 1.0, 2, 0, 300),
            ("Cabinet", 130, 4.5, 5.5, 14, 0, 50),
            ("Nightstand", 60, 2.0, 2.5, 6, 0, 100),
        ],
        columns=["product", "profit", "machine_hours", "labor_hours", "wood_kg", "min_qty", "max_qty"],
    )


def opt_transport() -> pd.DataFrame:
    """Unit shipping cost (TL) from four factories to six cities; empty = no route."""
    nan = np.nan
    rows = [
        ("İstanbul", 300, 70, 66, 105, 94, 33, 73),
        ("Ankara", 250, 48, 26, 74, 49, 23, 41),
        ("İzmir", 200, 45, 55, nan, 90, 41, 98),
        ("Bursa", 150, 54, 52, 106, 82, 15, 72),
        ("demand", nan, 140, 120, 110, 160, 130, 150),
    ]
    cols = ["factory", "supply", "Antalya", "Konya", "Trabzon", "Adana", "Eskişehir", "Samsun"]
    return pd.DataFrame(rows, columns=cols)


def opt_assignment() -> pd.DataFrame:
    """Efficiency score (0-100) of each worker on each task; empty = not certified."""
    workers = ["Ayşe", "Mehmet", "Elif", "Can", "Zeynep", "Burak", "Deniz"]
    tasks = ["Welding", "Assembly", "Painting", "QA", "Packaging", "Maintenance", "Logistics"]
    scores = rng.integers(45, 99, size=(len(workers), len(tasks))).astype(float)
    scores[3, 0] = np.nan  # Can is not certified for welding
    df = pd.DataFrame(scores, columns=tasks)
    df.insert(0, "worker", workers)
    return df


def opt_projects() -> pd.DataFrame:
    """Candidate projects: expected return and cost in money (k TL) and engineers."""
    names = [
        "CRM upgrade",
        "Mobile app",
        "Data warehouse",
        "Solar roof",
        "New warehouse",
        "Robot arm",
        "ERP migration",
        "Website redesign",
        "Fleet telematics",
        "Training academy",
        "Cyber audit",
        "Packaging line",
        "Customer portal",
        "AI forecasting",
        "Office move",
    ]
    capex = rng.integers(60, 320, size=len(names))
    engineers = rng.integers(1, 7, size=len(names))
    expected_return = np.round(
        capex * rng.uniform(1.1, 2.4, size=len(names)) + engineers * rng.uniform(5, 40, size=len(names))
    )
    return pd.DataFrame(
        {"project": names, "expected_return": expected_return, "capex": capex, "engineers": engineers}
    )


if __name__ == "__main__":
    # "\n" explicitly: pandas uses the OS line ending by default, which would make Windows output differ.
    lf = {"index": False, "lineterminator": "\n"}
    sales().to_csv(HERE / "sales.csv", **lf)
    tr_survey().to_csv(HERE / "tr_survey.csv", sep=";", decimal=",", encoding="cp1254", **lf)
    opt_production().to_csv(HERE / "opt_production.csv", **lf)
    opt_transport().to_csv(HERE / "opt_transport.csv", **lf)
    opt_assignment().to_csv(HERE / "opt_assignment.csv", **lf)
    opt_projects().to_csv(HERE / "opt_projects.csv", **lf)
    print("wrote samples/*.csv")
