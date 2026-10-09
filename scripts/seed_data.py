"""Load sample data: 500 customers, 24 products, 2000 orders (plus their line items).

Re-running wipes the four tables and reloads them. The random seed is fixed, so
the data is the same on every run apart from dates, which are relative to today.
"""
import random
import sys
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import create_engine, text

from app.config import settings

NUM_CUSTOMERS = 500
NUM_ORDERS = 2000
HISTORY_DAYS = 730  # orders span the last two years

FIRST_NAMES = [
    "James", "Mary", "Robert", "Patricia", "John", "Jennifer", "Michael", "Linda",
    "David", "Elizabeth", "William", "Barbara", "Richard", "Susan", "Joseph", "Jessica",
    "Thomas", "Sarah", "Daniel", "Karen", "Matthew", "Nancy", "Anthony", "Lisa",
    "Priya", "Wei", "Carlos", "Aisha", "Hiroshi", "Fatima", "Diego", "Mei",
    "Omar", "Sofia", "Raj", "Elena", "Kwame", "Ingrid", "Mateo", "Yuki",
]
LAST_NAMES = [
    "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis",
    "Rodriguez", "Martinez", "Hernandez", "Lopez", "Gonzalez", "Wilson", "Anderson",
    "Thomas", "Taylor", "Moore", "Jackson", "Martin", "Lee", "Perez", "Thompson",
    "White", "Patel", "Nguyen", "Kim", "Chen", "Singh", "Khan", "Okafor", "Tanaka",
    "Rossi", "Novak", "Cohen", "Murphy", "Schmidt", "Silva", "Ali", "Walker",
]
EMAIL_DOMAINS = ["gmail.com", "yahoo.com", "outlook.com", "icloud.com", "hotmail.com"]
# (city, state, weight) - bigger cities get more customers
CITIES = [
    ("New York", "NY", 10), ("Los Angeles", "CA", 9), ("Chicago", "IL", 7),
    ("Houston", "TX", 6), ("Phoenix", "AZ", 5), ("Philadelphia", "PA", 5),
    ("San Antonio", "TX", 4), ("San Diego", "CA", 4), ("Dallas", "TX", 4),
    ("San Jose", "CA", 3), ("Austin", "TX", 4), ("Seattle", "WA", 4),
    ("Denver", "CO", 3), ("Boston", "MA", 4), ("Atlanta", "GA", 4),
    ("Miami", "FL", 4), ("Portland", "OR", 3), ("Nashville", "TN", 3),
    ("Minneapolis", "MN", 2), ("Charlotte", "NC", 3),
]
# (name, category, price, cost, stock)
PRODUCTS = [
    ("Wireless Noise-Cancelling Headphones", "Electronics", "199.99", "110.00", 140),
    ("4K Ultra HD Monitor 27\"", "Electronics", "349.99", "215.00", 60),
    ("Mechanical Keyboard", "Electronics", "89.99", "42.00", 210),
    ("Wireless Mouse", "Electronics", "29.99", "11.50", 480),
    ("USB-C Docking Station", "Electronics", "129.99", "68.00", 95),
    ("Portable Bluetooth Speaker", "Electronics", "59.99", "27.00", 260),
    ("Ergonomic Office Chair", "Furniture", "279.99", "150.00", 45),
    ("Standing Desk", "Furniture", "449.99", "260.00", 30),
    ("Bookshelf 5-Tier", "Furniture", "119.99", "58.00", 70),
    ("LED Desk Lamp", "Furniture", "39.99", "15.00", 320),
    ("Filing Cabinet", "Furniture", "149.99", "80.00", 55),
    ("Monitor Arm", "Furniture", "69.99", "31.00", 150),
    ("Stainless Steel Water Bottle", "Home & Kitchen", "24.99", "8.00", 600),
    ("Drip Coffee Maker", "Home & Kitchen", "79.99", "38.00", 120),
    ("Non-Stick Cookware Set", "Home & Kitchen", "139.99", "72.00", 80),
    ("Air Fryer 5 Qt", "Home & Kitchen", "99.99", "51.00", 110),
    ("Chef's Knife 8\"", "Home & Kitchen", "49.99", "19.00", 230),
    ("Electric Kettle", "Home & Kitchen", "34.99", "14.00", 290),
    ("Yoga Mat", "Sports & Outdoors", "27.99", "9.50", 410),
    ("Adjustable Dumbbell Set", "Sports & Outdoors", "229.99", "130.00", 40),
    ("Running Backpack", "Sports & Outdoors", "64.99", "28.00", 170),
    ("Resistance Bands Set", "Sports & Outdoors", "19.99", "5.50", 520),
    ("Insulated Camping Tent", "Sports & Outdoors", "189.99", "102.00", 35),
    ("Fitness Tracker", "Sports & Outdoors", "89.99", "44.00", 190),
]
STATUSES = ["completed", "pending", "cancelled"]


def build_customers(rng, today):
    customers, seen_emails = [], set()
    cities = [(c, s) for c, s, _ in CITIES]
    weights = [w for _, _, w in CITIES]
    while len(customers) < NUM_CUSTOMERS:
        first, last = rng.choice(FIRST_NAMES), rng.choice(LAST_NAMES)
        email = "{}.{}{}@{}".format(
            first.lower(), last.lower(), rng.randint(1, 99), rng.choice(EMAIL_DOMAINS)
        )
        if email in seen_emails:
            continue
        seen_emails.add(email)
        city, state = rng.choices(cities, weights=weights)[0]
        customers.append({
            "first_name": first,
            "last_name": last,
            "email": email,
            "city": city,
            "state": state,
            "country": "USA",
            # leave at least 30 days so every customer can have order history
            "signup_date": today - timedelta(days=rng.randint(30, HISTORY_DAYS + 365)),
        })
    return customers


def weighted_sample(rng, weights, k):
    """Pick k distinct indexes, favouring higher weights."""
    pool, remaining, picked = list(range(len(weights))), list(weights), []
    for _ in range(k):
        i = rng.choices(range(len(pool)), weights=remaining)[0]
        picked.append(pool.pop(i))
        remaining.pop(i)
    return picked


def build_orders(rng, today, customers):
    """Return (orders, items). customer/product/order ids are 1-based positions."""
    # A minority of customers place most of the orders, as in real sales data.
    customer_weights = [rng.paretovariate(1.5) for _ in customers]
    # Cheaper products sell more often.
    product_weights = [1 / (float(p[2]) ** 0.5) for p in PRODUCTS]
    earliest = today - timedelta(days=HISTORY_DAYS)

    orders, items = [], []
    for order_id in range(1, NUM_ORDERS + 1):
        customer_idx = rng.choices(range(len(customers)), weights=customer_weights)[0]
        start = max(earliest, customers[customer_idx]["signup_date"])
        order_day = start + timedelta(days=rng.randint(0, (today - start).days))
        order_date = datetime.combine(
            order_day, time(rng.randint(7, 22), rng.randint(0, 59), rng.randint(0, 59))
        )
        # Recent orders are the ones still pending; older ones have resolved.
        if (today - order_day).days <= 7:
            status = rng.choices(STATUSES, weights=[30, 62, 8])[0]
        else:
            status = rng.choices(STATUSES, weights=[88, 2, 10])[0]

        total = Decimal("0")
        num_lines = rng.choices([1, 2, 3, 4, 5], weights=[35, 30, 20, 10, 5])[0]
        for product_idx in weighted_sample(rng, product_weights, num_lines):
            quantity = rng.choices([1, 2, 3, 4], weights=[60, 25, 10, 5])[0]
            unit_price = Decimal(PRODUCTS[product_idx][2])
            total += unit_price * quantity
            items.append({
                "order_id": order_id,
                "product_id": product_idx + 1,
                "quantity": quantity,
                "unit_price": unit_price,
            })
        orders.append({
            "customer_id": customer_idx + 1,
            "order_date": order_date,
            "status": status,
            "total_amount": total,
        })
    return orders, items


def main() -> None:
    rng = random.Random(42)
    today = date.today()

    customers = build_customers(rng, today)
    products = [
        {"name": n, "category": c, "price": Decimal(p), "cost": Decimal(k), "stock_quantity": s}
        for n, c, p, k, s in PRODUCTS
    ]
    orders, items = build_orders(rng, today, customers)

    engine = create_engine(settings.database_url)
    with engine.begin() as conn:
        conn.execute(text(
            "TRUNCATE order_items, orders, products, customers RESTART IDENTITY CASCADE"
        ))
        conn.execute(text(
            "INSERT INTO customers (first_name, last_name, email, city, state, country, signup_date) "
            "VALUES (:first_name, :last_name, :email, :city, :state, :country, :signup_date)"
        ), customers)
        conn.execute(text(
            "INSERT INTO products (name, category, price, cost, stock_quantity) "
            "VALUES (:name, :category, :price, :cost, :stock_quantity)"
        ), products)
        conn.execute(text(
            "INSERT INTO orders (customer_id, order_date, status, total_amount) "
            "VALUES (:customer_id, :order_date, :status, :total_amount)"
        ), orders)
        conn.execute(text(
            "INSERT INTO order_items (order_id, product_id, quantity, unit_price) "
            "VALUES (:order_id, :product_id, :quantity, :unit_price)"
        ), items)

    print("Seeded {} customers, {} products, {} orders, {} order items".format(
        len(customers), len(products), len(orders), len(items)
    ))


if __name__ == "__main__":
    main()
