import os
from pathlib import Path

import requests

REPO_ROOT = Path(__file__).resolve().parents[3]
ENV_FILE = REPO_ROOT / ".env"


def load_env_file(path):
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_env_file(ENV_FILE)

MEALIE_URL = os.environ.get("MEALIE_URL", "http://your.server.ip.address:9000/api")
API_KEY = os.environ.get("MEALIE_API_KEY", "")
HEADERS = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}


# --- Target structure ---
categories = [
    "Breakfast", "Brunch", "Lunch", "Dinner", "Snack", "Appetizer",
    "Side Dish", "Soup", "Salad", "Dessert", "Beverage",
    "Sauce & Condiment", "Comfort Food", "Quick & Easy", "Healthy"
]

tags = [
    # Cuisines
    "American", "Italian", "Asian", "Mexican", "Mediterranean", "Indian",
    "African", "European", "Latin American", "Middle Eastern",
    # Methods
    "Baked", "Grilled", "Fried", "Roasted", "Air Fryer", "Instant Pot",
    "Slow Cooker", "Steamed", "Boiled", "Raw / No Cook",
    # Diets
    "Vegan", "Vegetarian", "Keto", "Paleo", "Dairy-Free", "Gluten-Free",
    "Low-Carb", "Low-Fat", "High-Protein",
    # Contexts
    "Weeknight", "Holiday", "Kids", "Meal Prep", "Party"
]

# --- Delete all existing categories/tags ---
def wipe(endpoint):
    print(f"[start] Clearing {endpoint}...")
    resp = requests.get(f"{MEALIE_URL}/organizers/{endpoint}?perPage=999", headers=HEADERS)
    resp.raise_for_status()
    for item in resp.json().get("items", []):
        id_ = item["id"]
        name = item["name"]
        del_resp = requests.delete(f"{MEALIE_URL}/organizers/{endpoint}/{id_}", headers=HEADERS)
        if del_resp.status_code == 200:
            print(f"  [ok] Deleted {endpoint[:-1]}: {name}")
        else:
            print(f"  [warn] Failed to delete {name}: {del_resp.status_code}")

# --- Create new items ---
def seed(endpoint, names):
    print(f"[start] Seeding {endpoint}...")
    for name in names:
        resp = requests.post(f"{MEALIE_URL}/organizers/{endpoint}", headers=HEADERS, json={"name": name})
        if resp.status_code in (200, 201):
            print(f"  [ok] Added {endpoint[:-1]}: {name}")
        else:
            print(f"  [warn] Failed to create {name}: {resp.status_code} {resp.text}")

def main():
    if not API_KEY:
        raise RuntimeError("MEALIE_API_KEY is empty. Set it in .env or the environment.")

    wipe("categories")
    wipe("tags")
    seed("categories", categories)
    seed("tags", tags)
    print("\n[done] Categories and tags have been reset and seeded.")

if __name__ == "__main__":
    main()
