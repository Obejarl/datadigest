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


if __name__ == "__main__":
    sales().to_csv(HERE / "sales.csv", index=False)
    tr_survey().to_csv(HERE / "tr_survey.csv", sep=";", decimal=",", index=False, encoding="cp1254")
    print("wrote samples/sales.csv and samples/tr_survey.csv")
