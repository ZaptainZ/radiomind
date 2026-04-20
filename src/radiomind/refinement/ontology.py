"""Ontology tables for NumericAggregator rollup + query-time class aliasing.

Compact data module — edit here to extend. Not Python-structured content,
just two dicts and two helpers.
"""
from __future__ import annotations

# specific-noun → parent class(es). Used during ingest to duplicate events
# from specific buckets ("guitars") into parent buckets ("musical_instruments").
ROLLUP: dict[str, tuple[str, ...]] = {
    **dict.fromkeys(
        ("guitar", "guitars", "piano", "pianos", "keyboard", "ukulele", "ukuleles",
         "violin", "drum", "drums", "cello", "bass", "flute", "trumpet",
         "saxophone", "harp", "mandolin", "banjo", "harmonica", "instrument"),
        ("musical_instruments",),
    ),
    **dict.fromkeys(
        ("faucet", "toaster", "mat", "shelf", "blender", "coffeemaker",
         "coffee", "mixer", "microwave", "fridge", "dishwasher", "stove",
         "oven", "kettle"),
        ("kitchen_items",),
    ),
    **dict.fromkeys(
        ("coffee_maker", "coffee_makers", "kitchen_mat", "kitchen_mats",
         "kitchen_faucet", "kitchen_shelf", "kitchen_shelves", "rice_cooker",
         "rice_cookers", "slow_cooker", "slow_cookers", "air_fryer",
         "air_fryers", "food_processor", "food_processors"),
        ("kitchen_items",),
    ),
    **dict.fromkeys(
        ("dog", "cat", "hamster", "snake", "bird", "fish", "rabbit"),
        ("pets",),
    ),
    **dict.fromkeys(
        ("car", "truck", "suv", "sedan", "motorcycle"),
        ("vehicles",),
    ),
    **dict.fromkeys(("book", "novel"), ("books_read",)),
    **dict.fromkeys(("hike", "trek", "walk", "trail"), ("hikes",)),
    **dict.fromkeys(("trip", "vacation", "visit", "journey"), ("trips",)),
    **dict.fromkeys(
        ("class", "course", "lesson", "workshop", "session"),
        ("classes_taken",),
    ),
    "species": ("bird_species", "wildlife_sightings"),
}

# query-focus aliases — "money" resolves to charity_donations etc.
ALIASES: dict[str, str] = {
    "instruments": "musical_instruments",
    "instrument": "musical_instruments",
    "music_instruments": "musical_instruments",
    "musical_instrument": "musical_instruments",
    "kitchen_things": "kitchen_items",
    "kitchenware": "kitchen_items",
    "kitchen": "kitchen_items",
    "money": "charity_donations",
    "charity": "charity_donations",
    "donations": "charity_donations",
    "contributions": "charity_donations",
    "income": "income_events",
    "earnings": "income_events",
    "savings": "savings_events",
    "expenses": "spending_events",
    "spending": "spending_events",
    "birds": "bird_species",
    "species_of_birds": "bird_species",
}


# Helpers that used to live inline in numeric_aggregator

def parents_of(cls: str) -> tuple[str, ...]:
    """Return parent-class tuple for a specific class name (empty if none)."""
    return ROLLUP.get(cls.lower(), ())


def resolve_alias(focus: str) -> str:
    """Map a query-focus phrase to its canonical class name (or passthrough)."""
    return ALIASES.get(focus.lower(), focus.lower())
