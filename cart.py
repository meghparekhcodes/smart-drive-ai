# app.py (updated)
from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
import csv
import re
from math import fabs

app = Flask(__name__)
CORS(app)


def _parse_float_safe(val):
    """
    Try to parse numeric value from strings like "1,234,567" or "1234567.00".
    Returns float or None.
    """
    if val is None:
        return None
    s = str(val).strip()
    if s == "":
        return None
    # Remove any non-digit/non-dot characters (commas, currency symbols, spaces)
    cleaned = re.sub(r"[^\d.]", "", s)
    try:
        return float(cleaned)
    except ValueError:
        return None


# --- Load Car Data from CSV File ---
def load_cars_from_csv(filename="cars.csv"):
    """
    Loads CSV into a list of dicts.
    Normalizes name/brand/fuel (strip + lower).
    Converts price fields to numeric and stores as 'price_in_inr' (float or None).
    """
    cars = []
    try:
        with open(filename, newline="", encoding="utf-8") as csvfile:
            reader = csv.DictReader(csvfile)
            for row in reader:
                # Normalize text fields (so filters match reliably)
                for text_col in ("name", "brand", "fuel"):
                    if text_col in row:
                        row[text_col] = (row[text_col] or "").strip().lower()
                    else:
                        row[text_col] = ""

                # Normalize price: prefer 'price_in_inr', fall back to 'price'
                price_in_inr = None
                if "price_in_inr" in row and (row["price_in_inr"] or "").strip() != "":
                    price_in_inr = _parse_float_safe(row["price_in_inr"])
                elif "price" in row and (row["price"] or "").strip() != "":
                    price_in_inr = _parse_float_safe(row["price"])

                # store numeric price
                row["price_in_inr"] = price_in_inr

                # Optionally remove original 'price' if present
                if "price" in row:
                    row.pop("price", None)

                cars.append(row)
    except FileNotFoundError:
        print(f"Error: {filename} not found. Make sure it exists!")
    return cars


# Load data from CSV at start (cache in memory)
cars = load_cars_from_csv()


# --- Scoring and sorting utility ---
def score_and_sort_results(results, budget=None, brand_pref=None, fuel_pref=None):
    """
    Score each car in results and return a sorted list.
    If budget is provided, we prefer cars that are closer to budget (higher price <= budget).
    We compute a simple score:
      base_score = -abs(price - budget)  (smaller distance -> higher score)
    and small boosts for brand/fuel matches.
    If no budget is provided, we sort by price ascending.
    """
    scored = []
    for car in results:
        price = car.get("price_in_inr")
        # default score
        score = 0.0
        if budget is not None and price is not None:
            # smaller absolute difference -> higher score
            # use negative abs to allow descending sort later
            score = -fabs(price - budget)
            # prefer cars that are <= budget (slight bonus)
            if price <= budget:
                score += 1.0
        else:
            # fallback: prefer lower prices (simple)
            score = -price if price is not None else float("-inf")

        # brand boost (optional)
        if brand_pref and (car.get("brand") or "") == brand_pref.lower():
            score += 2.0
        # fuel boost (optional)
        if fuel_pref and (car.get("fuel") or "") == fuel_pref.lower():
            score += 1.0

        # attach numeric score for debugging/inspection
        car["_score"] = score
        scored.append(car)

    # sort by score descending so highest score comes first
    scored.sort(key=lambda r: r.get("_score", float("-inf")), reverse=True)
    return scored


# --- Filter cars based on user input ---
def filter_cars(budget, brand, fuel):
    """
    Return cars that satisfy the given filters.
    - budget: numeric or None (we interpret as max price)
    - brand: substring match (case-insensitive)
    - fuel: exact match (normalized)
    """
    results = []
    for car in cars:
        price = car.get("price_in_inr")
        # If price is missing or not numeric, skip that row (you can change policy)
        if price is None:
            continue

        if budget is not None:
            # price must be <= budget
            try:
                if float(price) > float(budget):
                    continue
            except (ValueError, TypeError):
                continue

        # brand filter: allow substring matching (so "tata" matches "tata motors")
        if brand:
            if brand.lower() not in (car.get("brand") or "").lower():
                continue

        # fuel filter: exact normalized match
        if fuel:
            if fuel.lower() != (car.get("fuel") or "").lower():
                continue

        # Row passes all filters
        results.append(car.copy())  # copy to avoid side-effects when scoring
    return results


def paginate_list(items, limit=3, offset=0):
    """
    Return a slice and metadata: items_slice, total_count, has_more
    limit/offset are sanitized and converted to ints.
    """
    total = len(items)
    # sanitize offset/limit
    try:
        offset = int(offset)
        if offset < 0:
            offset = 0
    except (ValueError, TypeError):
        offset = 0
    try:
        # If limit is None or empty, default to total (return all)
        if limit in (None, "", []):
            limit = total if total > 0 else 3
        limit = int(limit)
        if limit <= 0:
            limit = 3
    except (ValueError, TypeError):
        limit = 3

    slice_items = items[offset: offset + limit]
    has_more = (offset + limit) < total
    return slice_items, total, has_more


# Home Route (serves your HTML page)
@app.route('/')
def home():
    return render_template('index.html')


# Recommendation API with pagination support
@app.route('/recommend', methods=['POST', 'GET'])
def recommend():
    # Accept JSON body (POST) or query params (GET)
    if request.method == 'POST':
        data = request.get_json() or {}
        budget_raw = data.get('budget', None)
        brand = (data.get('brand') or '').strip()
        fuel = (data.get('fuel') or '').strip()
        # optional pagination params
        limit = data.get('limit', None)
        offset = data.get('offset', 0)
    else:
        # GET (fallback) - read from query string
        budget_raw = request.args.get('budget', None)
        brand = (request.args.get('brand') or '').strip()
        fuel = (request.args.get('fuel') or '').strip()
        limit = request.args.get('limit', None)
        offset = request.args.get('offset', 0)

    # parse budget safely (allow strings like "1,500,000")
    try:
        budget = _parse_float_safe(budget_raw) if budget_raw not in (None, "", []) else None
    except Exception:
        return jsonify({"message": "Invalid budget format."}), 400

    # Reject negative budgets
    if budget is not None and budget < 0:
        return jsonify({"message": "Budget must be a positive number."}), 400

    # Prevent returning entire dataset when no filters provided
    if budget is None and not brand and not fuel:
        return jsonify(
            {
                "recommendations": [],
                "total": 0,
                "has_more": False,
                "message": "Please provide a budget or at least one filter (brand or fuel) before requesting recommendations."
            }
        ), 400

    # Filter candidates first
    all_matches = filter_cars(budget, brand, fuel)

    if not all_matches:
        return jsonify({"recommendations": [], "total": 0, "has_more": False, "message": "No cars found matching your preferences."})

    # Score and sort matches (prefer cars closer to budget)
    ranked = score_and_sort_results(all_matches, budget, brand_pref=brand, fuel_pref=fuel)

    # apply pagination
    slice_items, total, has_more = paginate_list(ranked, limit=limit, offset=offset)

    # Remove internal _score before returning (but keep if you want to debug)
    for c in slice_items:
        if "_score" in c:
            c.pop("_score", None)

    # Normalize numeric metadata
    try:
        offset_int = int(offset)
    except (ValueError, TypeError):
        offset_int = 0
    try:
        limit_int = int(limit) if limit not in (None, "", []) else len(slice_items)
    except (ValueError, TypeError):
        limit_int = len(slice_items)

    return jsonify({
        "recommendations": slice_items,
        "total": total,
        "has_more": has_more,
        "offset": offset_int,
        "limit": limit_int
    })


if __name__ == '__main__':
    app.run(host="0.0.0.0", port=10000)
