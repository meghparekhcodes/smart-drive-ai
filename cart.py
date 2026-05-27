from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
import csv
import os
import re
from math import fabs

# =========================================================
# SMART DRIVE AI - PROFESSIONAL VERSION
# =========================================================

app = Flask(__name__)
CORS(app)

# =========================================================
# GLOBAL SETTINGS
# =========================================================

DEFAULT_LIMIT = 6
MAX_LIMIT = 20

# =========================================================
# HELPER FUNCTIONS
# =========================================================

def parse_float_safe(value):
    """
    Convert strings like:
    '12,00,000'
    '$12000'
    '12000.50'

    into float safely.
    """

    if value is None:
        return None

    value = str(value).strip()

    if value == "":
        return None

    cleaned = re.sub(r"[^\d.]", "", value)

    try:
        return float(cleaned)
    except:
        return None


def normalize_text(value):
    """
    Normalize text for matching.
    """

    if value is None:
        return ""

    return str(value).strip().lower()


# =========================================================
# LOAD CSV DATA
# =========================================================

def load_cars_from_csv(filename="cars.csv"):

    cars = []

    try:

        with open(filename, newline="", encoding="utf-8") as csvfile:

            reader = csv.DictReader(csvfile)

            for row in reader:

                # ---------------------------
                # Normalize text fields
                # ---------------------------

                row["name"] = normalize_text(row.get("name"))
                row["brand"] = normalize_text(row.get("brand"))
                row["fuel"] = normalize_text(row.get("fuel"))

                # ---------------------------
                # Normalize price
                # ---------------------------

                price = None

                if "price_in_inr" in row:
                    price = parse_float_safe(row["price_in_inr"])

                elif "price" in row:
                    price = parse_float_safe(row["price"])

                row["price_in_inr"] = price

                # ---------------------------
                # Add default image
                # ---------------------------

                row["image"] = row.get(
                    "image",
                    "https://images.unsplash.com/photo-1503376780353-7e6692767b70"
                )

                cars.append(row)

    except FileNotFoundError:
        print("cars.csv file not found!")

    return cars


# =========================================================
# LOAD ALL CARS
# =========================================================

cars = load_cars_from_csv()

print(f"Loaded {len(cars)} cars successfully.")

# =========================================================
# ADVANCED FILTER SYSTEM
# =========================================================

def filter_cars(
    budget=None,
    brand=None,
    fuel=None,
    search=None
):

    results = []

    for car in cars:

        # -------------------------------------
        # Skip cars without price
        # -------------------------------------

        price = car.get("price_in_inr")

        if price is None:
            continue

        # -------------------------------------
        # Budget Filter
        # -------------------------------------

        if budget is not None:

            if price > budget:
                continue

        # -------------------------------------
        # Brand Filter
        # -------------------------------------

        if brand:

            if brand.lower() not in car["brand"]:
                continue

        # -------------------------------------
        # Fuel Filter
        # -------------------------------------

        if fuel:

            if fuel.lower() != car["fuel"]:
                continue

        # -------------------------------------
        # Search Filter
        # -------------------------------------

        if search:

            combined = (
                car["name"] +
                " " +
                car["brand"] +
                " " +
                car["fuel"]
            )

            if search.lower() not in combined:
                continue

        results.append(car.copy())

    return results

# =========================================================
# AI-LIKE RANKING SYSTEM
# =========================================================

def calculate_score(
    car,
    budget=None,
    preferred_brand=None,
    preferred_fuel=None
):

    score = 0

    price = car.get("price_in_inr")

    # -------------------------------------
    # Budget proximity score
    # -------------------------------------

    if budget is not None and price is not None:

        difference = fabs(price - budget)

        score += max(0, 1000000 - difference)

        if price <= budget:
            score += 50000

    # -------------------------------------
    # Brand preference bonus
    # -------------------------------------

    if preferred_brand:

        if preferred_brand.lower() in car["brand"]:
            score += 30000

    # -------------------------------------
    # Fuel preference bonus
    # -------------------------------------

    if preferred_fuel:

        if preferred_fuel.lower() == car["fuel"]:
            score += 20000

    return score


def rank_cars(
    car_list,
    budget=None,
    brand=None,
    fuel=None
):

    ranked = []

    for car in car_list:

        score = calculate_score(
            car,
            budget,
            brand,
            fuel
        )

        car["_score"] = score

        ranked.append(car)

    ranked.sort(
        key=lambda x: x["_score"],
        reverse=True
    )

    return ranked

# =========================================================
# PAGINATION SYSTEM
# =========================================================

def paginate_results(items, limit, offset):

    total = len(items)

    sliced = items[offset:offset + limit]

    has_more = (offset + limit) < total

    return {
        "items": sliced,
        "total": total,
        "has_more": has_more
    }

# =========================================================
# HOME PAGE
# =========================================================

@app.route("/")
def home():
    return render_template("index.html")

# =========================================================
# HEALTH CHECK
# =========================================================

@app.route("/health")
def health():

    return jsonify({
        "status": "healthy",
        "cars_loaded": len(cars)
    })

# =========================================================
# MAIN RECOMMENDATION API
# =========================================================

@app.route("/recommend", methods=["POST"])
def recommend():

    try:

        data = request.get_json()

        # -------------------------------------
        # Get Input Data
        # -------------------------------------

        budget = parse_float_safe(data.get("budget"))

        brand = normalize_text(data.get("brand"))

        fuel = normalize_text(data.get("fuel"))

        search = normalize_text(data.get("search"))

        limit = data.get("limit", DEFAULT_LIMIT)

        offset = data.get("offset", 0)

        # -------------------------------------
        # Validate Limit
        # -------------------------------------

        try:
            limit = int(limit)
        except:
            limit = DEFAULT_LIMIT

        if limit <= 0:
            limit = DEFAULT_LIMIT

        if limit > MAX_LIMIT:
            limit = MAX_LIMIT

        # -------------------------------------
        # Validate Offset
        # -------------------------------------

        try:
            offset = int(offset)
        except:
            offset = 0

        if offset < 0:
            offset = 0

        # -------------------------------------
        # Prevent empty queries
        # -------------------------------------

        if (
            budget is None and
            brand == "" and
            fuel == "" and
            search == ""
        ):

            return jsonify({
                "success": False,
                "message": "Please enter at least one filter.",
                "recommendations": []
            }), 400

        # -------------------------------------
        # Filter Cars
        # -------------------------------------

        filtered = filter_cars(
            budget,
            brand,
            fuel,
            search
        )

        # -------------------------------------
        # No Results
        # -------------------------------------

        if len(filtered) == 0:

            return jsonify({
                "success": True,
                "message": "No cars found matching your preferences.",
                "recommendations": [],
                "total": 0,
                "has_more": False
            })

        # -------------------------------------
        # Rank Results
        # -------------------------------------

        ranked = rank_cars(
            filtered,
            budget,
            brand,
            fuel
        )

        # -------------------------------------
        # Pagination
        # -------------------------------------

        paginated = paginate_results(
            ranked,
            limit,
            offset
        )

        # -------------------------------------
        # Remove internal score
        # -------------------------------------

        cleaned = []

        for car in paginated["items"]:

            if "_score" in car:
                car.pop("_score")

            cleaned.append(car)

        # -------------------------------------
        # Success Response
        # -------------------------------------

        return jsonify({

            "success": True,

            "message": f"{paginated['total']} cars found.",

            "recommendations": cleaned,

            "total": paginated["total"],

            "offset": offset,

            "limit": limit,

            "has_more": paginated["has_more"]

        })

    except Exception as e:

        return jsonify({
            "success": False,
            "message": str(e)
        }), 500

# =========================================================
# TOP BRANDS API
# =========================================================

@app.route("/brands")
def brands():

    unique_brands = sorted(
        list(
            set(
                car["brand"]
                for car in cars
                if car["brand"]
            )
        )
    )

    return jsonify({
        "brands": unique_brands
    })

# =========================================================
# TOP FUEL TYPES API
# =========================================================

@app.route("/fuel-types")
def fuel_types():

    unique_fuels = sorted(
        list(
            set(
                car["fuel"]
                for car in cars
                if car["fuel"]
            )
        )
    )

    return jsonify({
        "fuel_types": unique_fuels
    })

# =========================================================
# CAR DETAILS API
# =========================================================

@app.route("/car/<car_name>")
def car_details(car_name):

    car_name = normalize_text(car_name)

    for car in cars:

        if car["name"] == car_name:

            return jsonify({
                "success": True,
                "car": car
            })

    return jsonify({
        "success": False,
        "message": "Car not found."
    }), 404

# =========================================================
# ERROR HANDLERS
# =========================================================

@app.errorhandler(404)
def not_found(error):

    return jsonify({
        "success": False,
        "message": "Route not found."
    }), 404


@app.errorhandler(500)
def internal_error(error):

    return jsonify({
        "success": False,
        "message": "Internal server error."
    }), 500

# =========================================================
# START SERVER
# =========================================================

if __name__ == "__main__":

    port = int(os.environ.get("PORT", 10000))

    print(f"Running Smart Drive AI on port {port}")

    app.run(
        host="0.0.0.0",
        port=port
    )