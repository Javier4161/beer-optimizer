"""
Beer Budget Optimizer
----------------------
Given a list of draft beers (with enjoyability, ABV, and a pricing category)
plus a separate table of category prices at 16/32/64oz, and a budget, this
picks purchases to maximize a weighted "value" score:

    score = 0.50 * enjoyability + 0.35 * price_value + 0.15 * strength

Pricing is set per CATEGORY (Domestic, Premium, Import, Specials, Economy)
rather than per individual beer - every beer in a category shares the same
16/32/64oz prices.

Four caps are user-configurable via the Settings dataclass (entered at
startup in the GUI, persisted to settings.json in the local data dir):
  - session_limit_oz: max oz of one beer per single run of the program
  - rolling_volume_limit_oz / rolling_volume_window_days:
        max oz of one beer across a trailing window of days
  - rolling_category_limit_oz / rolling_category_window_days:
        max oz of one category (summed across all its beers) across a
        separately configurable trailing window of days

Algorithm (greedy):
  1. Normalize enjoyability, price-per-oz, and ABV across all beers (0-1).
  2. Compute a weighted score per beer.
  3. Sort beers best -> worst.
  4. For the current best beer, keep buying the LARGEST size that fits the
     remaining budget, until any of the four caps above is hit, or no size
     of it fits the remaining budget.
  5. Move to the next best beer and repeat.
  6. Stop when budget is exhausted or nothing affordable remains.
"""

import csv
import json
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional


def get_data_dir() -> str:
    """
    Per-user, per-computer folder for this program's editable data and
    history. Uses Windows' LOCALAPPDATA (falls back to home directory on
    other OSes for local testing/dev).

    This is deliberately NOT the folder the .exe lives in: the .exe may
    be run straight off a shared flash drive, and nothing should ever be
    written back to that drive. The first time this program runs on a
    given computer, it creates its own local copy of the beer list and
    category prices here (seeded from the built-in defaults below), and
    every edit or purchase after that stays local to that computer.
    """
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    data_dir = os.path.join(base, "BeerOptimizer")
    os.makedirs(data_dir, exist_ok=True)
    return data_dir


SIZES = [64, 32, 16]  # check largest first
HISTORY_FILE = os.path.join(get_data_dir(), "purchase_history.json")
DEFAULT_BEERS_CSV = os.path.join(get_data_dir(), "beers.csv")
DEFAULT_PRICES_CSV = os.path.join(get_data_dir(), "category_prices.csv")
SETTINGS_FILE = os.path.join(get_data_dir(), "settings.json")
CATEGORIES = {"Domestic", "Premium", "Import", "Specials", "Economy"}


@dataclass
class Settings:
    """
    All four caps are user-configurable, entered at startup:
      - session_limit_oz: cap per beer, per single allocation run
      - rolling_volume_limit_oz / rolling_volume_window_days:
            cap per beer across a trailing window of days
      - rolling_category_limit_oz / rolling_category_window_days:
            cap per category across a (separately configurable) trailing
            window of days

    The scoring weights are also configurable, as whole-number percentages
    that must add up to 100:
      - weight_enjoyability_pct (default 50)
      - weight_price_pct (default 35)
      - weight_strength_pct (default 15)
    """
    session_limit_oz: int = 96
    rolling_volume_limit_oz: int = 192
    rolling_volume_window_days: int = 14
    rolling_category_limit_oz: int = 320
    rolling_category_window_days: int = 14
    weight_enjoyability_pct: int = 50
    weight_price_pct: int = 35
    weight_strength_pct: int = 15


DEFAULT_SETTINGS = Settings()


def _atomic_write_json(path: str, data) -> None:
    """
    Write JSON to `path` without ever leaving a partially-written or
    corrupted file behind, even if the process is killed mid-write
    (e.g. via Task Manager "End Task"). Writes to a temp file in the
    same folder first, then atomically renames it into place - on
    Windows, os.replace() is atomic, so readers only ever see either
    the old complete file or the new complete file, never a half-written
    one.
    """
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp_path, path)


def load_settings(path: str = SETTINGS_FILE) -> Settings:
    """Load saved settings, filling in defaults for any missing/invalid fields."""
    if not os.path.exists(path):
        return Settings()
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        defaults = Settings()
        kwargs = {}
        for key in defaults.__dataclass_fields__:
            kwargs[key] = data.get(key, getattr(defaults, key))
        return Settings(**kwargs)
    except (json.JSONDecodeError, TypeError, ValueError, OSError):
        return Settings()


def save_settings(settings: Settings, path: str = SETTINGS_FILE) -> None:
    _atomic_write_json(path, settings.__dict__)

# Seed data written out the first time the program runs on a computer
# (i.e. when no beers.csv / category_prices.csv exists yet in the data
# dir). After that, whatever the user edits and saves takes over.
DEFAULT_BEER_ROWS = [
    {"name": "Hazy IPA", "enjoyability": "9.0", "abv": "6.5", "category": "Premium"},
    {"name": "Pilsner", "enjoyability": "7.0", "abv": "4.8", "category": "Domestic"},
    {"name": "Stout", "enjoyability": "8.0", "abv": "8.0", "category": "Import"},
    {"name": "Sour", "enjoyability": "8.5", "abv": "5.0", "category": "Specials"},
    {"name": "Barrel-Aged Barleywine", "enjoyability": "9.5", "abv": "11.0", "category": "Specials"},
    {"name": "Light Lager", "enjoyability": "5.5", "abv": "4.2", "category": "Economy"},
]
DEFAULT_CATEGORY_PRICE_ROWS = [
    {"category": "Domestic", "price_16": "4.00", "price_32": "7.50", "price_64": "14.00"},
    {"category": "Premium", "price_16": "6.00", "price_32": "11.00", "price_64": "20.00"},
    {"category": "Import", "price_16": "6.50", "price_32": "12.00", "price_64": "22.00"},
    {"category": "Specials", "price_16": "7.00", "price_32": "13.00", "price_64": "24.00"},
    {"category": "Economy", "price_16": "3.50", "price_32": "6.50", "price_64": "12.00"},
]


@dataclass
class Beer:
    name: str
    enjoyability: float  # e.g. 1-10 scale
    abv: float           # percent, e.g. 6.5
    category: str        # Domestic / Premium / Import / Specials / Economy
    prices: Dict[int, float]  # {16: 6.0, 32: 11.0, 64: 20.0} - looked up from category

    # filled in during scoring
    score: float = field(default=0.0, init=False)

    def price_per_oz(self, size: int) -> float:
        return self.prices[size] / size

    def cheapest_price_per_oz(self) -> float:
        return min(self.price_per_oz(s) for s in self.prices)


def normalize(values: List[float], invert: bool = False) -> List[float]:
    """Min-max normalize to 0-1. If invert=True, lower raw value -> higher score."""
    lo, hi = min(values), max(values)
    if hi == lo:
        return [1.0 for _ in values]  # all identical -> treat as equally good
    norm = [(v - lo) / (hi - lo) for v in values]
    if invert:
        norm = [1 - n for n in norm]
    return norm


def score_beers(beers: List[Beer],
                 w_enjoy: float = 0.50,
                 w_price: float = 0.35,
                 w_strength: float = 0.15) -> None:
    enjoy_norm = normalize([b.enjoyability for b in beers])
    price_norm = normalize([b.cheapest_price_per_oz() for b in beers], invert=True)
    abv_norm = normalize([b.abv for b in beers])

    for b, e, p, a in zip(beers, enjoy_norm, price_norm, abv_norm):
        b.score = w_enjoy * e + w_price * p + w_strength * a


def load_beer_rows(path: str) -> List[dict]:
    """Raw read of beers.csv as a list of dicts, for the editor UI (no validation)."""
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def save_beer_rows(path: str, rows: List[dict]) -> None:
    fieldnames = ["name", "enjoyability", "abv", "category"]
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in fieldnames})
    os.replace(tmp_path, path)


def load_category_price_rows(path: str) -> List[dict]:
    """Raw read of category_prices.csv as a list of dicts, for the editor UI."""
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def save_category_price_rows(path: str, rows: List[dict]) -> None:
    fieldnames = ["category", "price_16", "price_32", "price_64"]
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in fieldnames})
    os.replace(tmp_path, path)


def ensure_default_files() -> None:
    """Create beers.csv / category_prices.csv in the data dir from the
    built-in defaults, but only if they don't already exist - never
    overwrites a file the user has edited."""
    if not os.path.exists(DEFAULT_BEERS_CSV):
        save_beer_rows(DEFAULT_BEERS_CSV, DEFAULT_BEER_ROWS)
    if not os.path.exists(DEFAULT_PRICES_CSV):
        save_category_price_rows(DEFAULT_PRICES_CSV, DEFAULT_CATEGORY_PRICE_ROWS)


def load_category_prices(path: str) -> Dict[str, Dict[int, float]]:
    """
    Expects columns: category,price_16,price_32,price_64
    One row per category (Domestic, Premium, Import, Specials, Economy).
    Leave a price cell blank if that size isn't offered for a category.
    """
    category_prices: Dict[str, Dict[int, float]] = {}
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        required = {"category", "price_16", "price_32", "price_64"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"Category price CSV is missing required columns: {missing}")

        for row in reader:
            category = row["category"].strip()
            if category not in CATEGORIES:
                raise ValueError(
                    f"Unknown category '{category}'. Must be one of: {sorted(CATEGORIES)}"
                )

            prices = {}
            for size, col in ((16, "price_16"), (32, "price_32"), (64, "price_64")):
                val = row.get(col, "").strip()
                if val:
                    prices[size] = float(val)
            if not prices:
                raise ValueError(f"Category '{category}' has no prices listed for any size")

            category_prices[category] = prices

    missing_categories = CATEGORIES - set(category_prices)
    if missing_categories:
        raise ValueError(f"Category price CSV is missing rows for: {sorted(missing_categories)}")

    return category_prices


def load_beers_from_csv(path: str, category_prices: Dict[str, Dict[int, float]]) -> List[Beer]:
    """
    Expects columns: name,enjoyability,abv,category
    `category` must match a category defined in the category prices CSV
    (Domestic, Premium, Import, Specials, Economy).
    """
    beers = []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        required = {"name", "enjoyability", "abv", "category"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"CSV is missing required columns: {missing}")

        for row in reader:
            category = row["category"].strip()
            if category not in category_prices:
                raise ValueError(
                    f"Beer '{row['name']}' has category '{category}', which has no "
                    f"pricing row in the category prices CSV."
                )

            beers.append(Beer(
                name=row["name"].strip(),
                enjoyability=float(row["enjoyability"]),
                abv=float(row["abv"]),
                category=category,
                prices=category_prices[category],
            ))
    return beers


@dataclass
class Purchase:
    beer_name: str
    category: str
    size: int
    price: float
    timestamp: str = ""  # ISO format; filled in when recorded to history


def load_history(path: str = HISTORY_FILE) -> List[dict]:
    """Load past purchase records. Returns [] if the file doesn't exist yet,
    or is unreadable/corrupted (e.g. left partially-written by a process
    that was force-killed mid-save)."""
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, TypeError, ValueError, OSError):
        return []


def save_history(records: List[dict], path: str = HISTORY_FILE) -> None:
    _atomic_write_json(path, records)


def append_purchases_to_history(purchases: List[Purchase], now: datetime,
                                 path: str = HISTORY_FILE) -> None:
    history = load_history(path)
    for p in purchases:
        history.append({
            "beer_name": p.beer_name,
            "category": p.category,
            "size": p.size,
            "price": p.price,
            "timestamp": now.isoformat(),
        })
    save_history(history, path)


def historic_volume_by_beer(history: List[dict], now: datetime,
                             window_days: int = 14) -> Dict[str, int]:
    """Sum oz purchased per beer within the rolling window, up to `now`."""
    cutoff = now - timedelta(days=window_days)
    totals: Dict[str, int] = {}
    for record in history:
        ts = datetime.fromisoformat(record["timestamp"])
        if ts >= cutoff:
            totals[record["beer_name"]] = totals.get(record["beer_name"], 0) + record["size"]
    return totals


def historic_volume_by_category(history: List[dict], now: datetime,
                                 window_days: int = 14) -> Dict[str, int]:
    """Sum oz purchased per category within the rolling window, up to `now`."""
    cutoff = now - timedelta(days=window_days)
    totals: Dict[str, int] = {}
    for record in history:
        ts = datetime.fromisoformat(record["timestamp"])
        # older records may not have a "category" field - skip those safely
        category = record.get("category")
        if ts >= cutoff and category:
            totals[category] = totals.get(category, 0) + record["size"]
    return totals


def largest_affordable_size(beer: Beer, remaining_budget: float,
                             remaining_volume_allowed: int) -> Optional[int]:
    """Largest size that fits both the wallet and the remaining volume allowance."""
    for size in SIZES:
        if size > remaining_volume_allowed:
            continue
        if beer.prices.get(size) is None:
            continue
        if beer.prices[size] <= remaining_budget:
            return size
    return None


def allocate(beers: List[Beer], budget: float,
             historic_oz: Optional[Dict[str, int]] = None,
             historic_category_oz: Optional[Dict[str, int]] = None,
             settings: Optional[Settings] = None) -> List[Purchase]:
    """
    historic_oz: {beer_name: oz already purchased in the beer's rolling
                 window} (from historic_volume_by_beer, called with
                 settings.rolling_volume_window_days). Pass None/{} to
                 ignore history.
    historic_category_oz: {category: oz already purchased in the
                 category's rolling window} (from
                 historic_volume_by_category, called with
                 settings.rolling_category_window_days). Pass None/{} to
                 ignore history.
    settings: caps to enforce. Defaults to Settings() (96oz session /
              192oz per 14 days / 320oz category per 14 days) if omitted.
    """
    historic_oz = historic_oz or {}
    historic_category_oz = historic_category_oz or {}
    settings = settings or DEFAULT_SETTINGS
    score_beers(
        beers,
        w_enjoy=settings.weight_enjoyability_pct / 100,
        w_price=settings.weight_price_pct / 100,
        w_strength=settings.weight_strength_pct / 100,
    )
    ranked = sorted(beers, key=lambda b: b.score, reverse=True)

    purchases: List[Purchase] = []
    remaining_budget = budget
    volume_bought = {b.name: 0 for b in beers}
    category_volume_bought = {c: 0 for c in CATEGORIES}

    for beer in ranked:
        while remaining_budget > 0:
            session_room = settings.session_limit_oz - volume_bought[beer.name]
            rolling_room = (settings.rolling_volume_limit_oz
                             - historic_oz.get(beer.name, 0)
                             - volume_bought[beer.name])
            category_room = (settings.rolling_category_limit_oz
                              - historic_category_oz.get(beer.category, 0)
                              - category_volume_bought[beer.category])
            remaining_volume_allowed = min(session_room, rolling_room, category_room)
            if remaining_volume_allowed <= 0:
                break  # hit the session cap, the rolling beer cap,
                       # or the rolling category cap; move on

            size = largest_affordable_size(beer, remaining_budget, remaining_volume_allowed)
            if size is None:
                break  # can't afford any size of this beer anymore

            price = beer.prices[size]
            purchases.append(Purchase(beer.name, beer.category, size, price))
            remaining_budget -= price
            volume_bought[beer.name] += size
            category_volume_bought[beer.category] += size

        if remaining_budget <= 0:
            break

    return purchases


def summarize(purchases: List[Purchase], budget: float, beers: List[Beer]) -> None:
    beer_by_name = {b.name: b for b in beers}
    spent = sum(p.price for p in purchases)
    print(f"Budget: ${budget:.2f}   Spent: ${spent:.2f}   Remaining: ${budget - spent:.2f}\n")
    totals: Dict[str, int] = {}
    for p in purchases:
        category = beer_by_name[p.beer_name].category
        print(f"  {p.beer_name:20s} ({category:9s}) {p.size:2d}oz   ${p.price:.2f}")
        totals[p.beer_name] = totals.get(p.beer_name, 0) + p.size
    print("\nTotals per beer:")
    for name, oz in totals.items():
        print(f"  {name:20s} {oz}oz")


if __name__ == "__main__":
    ensure_default_files()

    beers_csv_path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_BEERS_CSV
    prices_csv_path = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_PRICES_CSV
    budget = float(sys.argv[3]) if len(sys.argv) > 3 else 100.0
    # optional flag: pass "--no-save" to test without writing to history
    no_save = "--no-save" in sys.argv

    now = datetime.now()
    settings = load_settings()
    category_prices = load_category_prices(prices_csv_path)
    beers = load_beers_from_csv(beers_csv_path, category_prices)

    history = load_history()
    historic_oz = historic_volume_by_beer(history, now, settings.rolling_volume_window_days)
    historic_category_oz = historic_volume_by_category(
        history, now, settings.rolling_category_window_days)

    purchases = allocate(beers, budget, historic_oz=historic_oz,
                          historic_category_oz=historic_category_oz, settings=settings)
    summarize(purchases, budget, beers)

    if historic_oz:
        print(f"\n(Rolling {settings.rolling_volume_window_days}-day beer totals already on record:)")
        for name, oz in historic_oz.items():
            print(f"  {name:20s} {oz}oz")
    if historic_category_oz:
        print(f"\n(Rolling {settings.rolling_category_window_days}-day category totals already on record:)")
        for category, oz in historic_category_oz.items():
            print(f"  {category:20s} {oz}oz")

    if not no_save and purchases:
        append_purchases_to_history(purchases, now)
        print(f"\nSaved {len(purchases)} purchase(s) to {HISTORY_FILE}")
