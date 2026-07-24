import json
import os
import re
import sqlite3

from calendar import monthrange
from datetime import datetime, timedelta

from flask import (
    Flask, render_template, request, redirect,
    url_for, session, send_file, jsonify, flash
)

from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
)

from werkzeug.security import generate_password_hash, check_password_hash


from config import Config

app = Flask(__name__)
app.config.from_object(Config)

DATABASE = app.config["DATABASE"]
app.secret_key = app.config["SECRET_KEY"]

import re

def validate_password(password):
    """
    Validate password strength.

    Returns:
        (True, "") if valid
        (False, "Reason") if invalid
    """

    if len(password) < 8:
        return False, "Password must be at least 8 characters long."

    if not re.search(r"[A-Z]", password):
        return False, "Password must contain at least one uppercase letter."

    if not re.search(r"[a-z]", password):
        return False, "Password must contain at least one lowercase letter."

    if not re.search(r"[0-9]", password):
        return False, "Password must contain at least one number."

    if not re.search(r"[!@#$%^&*(),.?\":{}|<>]", password):
        return False, "Password must contain at least one special character."

    return True, ""

# -----------------------
# DATABASE CONNECTION
# -----------------------

def get_db_connection():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

# -----------------------
# CREATE TABLES
# -----------------------

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()

    # Users table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        role TEXT NOT NULL DEFAULT 'customer',
        full_name TEXT,
        email TEXT UNIQUE,
        phone TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
""")

    # Menu table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS menu (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        price REAL NOT NULL,
        category TEXT NOT NULL,
        image TEXT,
        available INTEGER DEFAULT 1
    )
""")

    # Orders table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            total_amount REAL,
            status TEXT NOT NULL DEFAULT 'Pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
    ''')

    # Order items
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS order_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL,
            item_name TEXT NOT NULL,
            price REAL NOT NULL,
            quantity INTEGER NOT NULL,
            FOREIGN KEY(order_id) REFERENCES orders(id)
        )
    ''')

    # Feedback table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS feedback (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        message TEXT,
        rating INTEGER NOT NULL,
        admin_reply TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(user_id) REFERENCES users(id)
        );
    """)

    # Create admin if not exists
    admin = cursor.execute(
        "SELECT id FROM users WHERE username = ?",
        ("admin",)
    ).fetchone()

    if not admin:
        cursor.execute(
            "INSERT INTO users (username, password, role) VALUES (?, ?, ?)",
            (
            "admin",
            generate_password_hash(app.config["ADMIN_PASSWORD"]),
            "admin"
            )
        )

    conn.commit()
    conn.close()


# -----------------------
# PUBLIC ROUTES
# -----------------------

@app.route("/")
def home():
    print("Current session role:", session.get("role"))
    return render_template("home.html")


@app.route("/menu")
def menu():
    conn = get_db_connection()

    try:
        menu_items = conn.execute("""
            SELECT *
            FROM menu
            WHERE available = 1
            ORDER BY category, name
        """).fetchall()

    finally:
        conn.close()

    return render_template(
        "menu.html",
        menu_items=menu_items
    )


@app.route("/about")
def about():
    return render_template("about.html")


@app.route("/cart")
def cart():
    if session.get("role") != "customer":
        return "Access Denied"

    reorder_cart = session.pop("reorder_cart", None)
    return render_template("cart.html", reorder_cart=reorder_cart)


@app.route("/checkout")
def checkout():

    if session.get("role") != "customer":
        return "Access Denied"

    conn = get_db_connection()

    user = conn.execute(
        """
        SELECT full_name, email, phone
        FROM users
        WHERE id = ?
        """,
        (session["user_id"],)
    ).fetchone()

    conn.close()

    return render_template(
        "checkout.html",
        user=user
    )


@app.route("/forgot_password", methods=["GET", "POST"])
def forgot_password():

    if request.method == "POST":

        username = request.form["username"].strip()
        new_password = request.form["new_password"]

        # Validate password strength
        valid, message = validate_password(new_password)

        if not valid:
            flash(message, "error")
            return redirect(url_for("forgot_password"))

        conn = get_db_connection()

        user = conn.execute(
            """
            SELECT *
            FROM users
            WHERE username = ?
            """,
            (username,)
        ).fetchone()

        if not user:
            conn.close()
            flash("Username not found.", "error")
            return redirect(url_for("forgot_password"))

        # Prevent using the same password
        if check_password_hash(user["password"], new_password):
            conn.close()
            flash("New password cannot be the same as the old password.", "error")
            return redirect(url_for("forgot_password"))

        hashed_password = generate_password_hash(new_password)

        conn.execute(
            """
            UPDATE users
            SET password = ?
            WHERE username = ?
            """,
            (hashed_password, username)
        )

        conn.commit()
        conn.close()

        flash("Password reset successfully. Please login.", "success")
        return redirect(url_for("login"))

    return render_template("forgot_password.html")


# -----------------------
# CUSTOMER ROUTES
# -----------------------

@app.route("/cancel_order/<int:order_id>", methods=["POST"])
def cancel_order(order_id):
    if session.get("role") != "customer":
        return "Access Denied"

    conn = get_db_connection()

    order = conn.execute("""
        SELECT * FROM orders
        WHERE id=? AND user_id=?
    """, (order_id, session["user_id"])).fetchone()

    if not order:
        conn.close()
        return "Order not found"

    if order["status"] != "Received":
        conn.close()
        return "Cannot cancel this order"

    conn.execute("""
        UPDATE orders
        SET status = 'Cancelled'
        WHERE id=?
    """, (order_id,))

    conn.commit()
    conn.close()

    return redirect(url_for("profile"))


@app.route("/reorder/<int:order_id>", methods=["POST"])
def reorder(order_id):
    if session.get("role") != "customer":
        return "Access Denied"

    conn = get_db_connection()

    items = conn.execute("""
        SELECT
            order_items.item_name,
            order_items.price,
            order_items.quantity,
            menu.image,
            menu.available
        FROM order_items
        LEFT JOIN menu
            ON order_items.item_name = menu.name
        WHERE order_items.order_id = ?
    """, (order_id,)).fetchall()

    conn.close()

    if not items:
        flash("No items found in this order.", "error")
        return redirect(url_for("profile"))

    cart = []
    unavailable_items = []

    for item in items:

        # Skip unavailable items
        # Item deleted or out of stock
        if item["available"] != 1:
            unavailable_items.append(item["item_name"])
            continue

        cart.append({
            "name": item["item_name"],
            "price": item["price"],
            "quantity": item["quantity"],
            "image": item["image"] if item["image"] else "default.jpg"
        })

    # If every item is unavailable
    if not cart:
        flash(
            "None of the items from your previous order are currently available.",
            "error"
        )
        return redirect(url_for("profile"))

    # Replace current cart with reordered items
    session["reorder_cart"] = cart
    session.modified = True

    # Flash message
    if unavailable_items:
        flash(
            f"{len(cart)} item(s) added to cart. "
            f"The following item(s) are currently unavailable: "
            f"{', '.join(unavailable_items)}",
            "warning"
        )
    else:
        flash(
            "All items from your previous order have been added to the cart.",
            "success"
        )

    return redirect(url_for("cart"))


@app.route("/profile")
def profile():

    if "user_id" not in session:
        return redirect(url_for("login"))

    conn = get_db_connection()

    # ------------------------
    # User Details
    # ------------------------
    user = conn.execute("""
        SELECT
            id,
            username,
            full_name,
            phone,
            role,
            created_at
        FROM users
        WHERE id = ?
    """, (session["user_id"],)).fetchone()

    if not user:
        conn.close()
        return redirect(url_for("logout"))

    # ------------------------
    # Active Queue
    # ------------------------
    active_orders = conn.execute("""
        SELECT id
        FROM orders
        WHERE status IN ('Received', 'Preparing')
        ORDER BY id ASC
    """).fetchall()

    queue = [row["id"] for row in active_orders]

    # ------------------------
    # User Orders
    # ------------------------
    orders = conn.execute("""
        SELECT *
        FROM orders
        WHERE user_id = ?
        ORDER BY id DESC
    """, (session["user_id"],)).fetchall()

    orders_with_details = []

    for order in orders:

        items = conn.execute("""
            SELECT *
            FROM order_items
            WHERE order_id = ?
        """, (order["id"],)).fetchall()

        if order["id"] in queue:

            position = queue.index(order["id"]) + 1
            orders_ahead = position - 1
            estimated_time = orders_ahead * 5

        else:

            position = "-"
            orders_ahead = "-"
            estimated_time = "-"

        orders_with_details.append({
            "id": order["id"],
            "status": order["status"],
            "created_at": order["created_at"],
            "total_amount": order["total_amount"],
            "items": items,
            "position": position,
            "orders_ahead": orders_ahead,
            "estimated_time": estimated_time
        })

    conn.close()

    return render_template(
        "profile.html",
        user=user,
        orders=orders_with_details
    )


@app.route("/edit_profile", methods=["GET", "POST"])
def edit_profile():

    if "user_id" not in session:
        return redirect(url_for("login"))

    conn = get_db_connection()

    if request.method == "POST":

        name = request.form["name"].strip()
        phone = request.form["phone"].strip()

        # Validate Name
        if len(name) < 3:
            flash("Name must contain at least 3 characters.", "error")
            conn.close()
            return redirect(url_for("edit_profile"))

        # Validate Phone Number
        if not phone.isdigit() or len(phone) != 10:
            flash("Please enter a valid 10-digit phone number.", "error")
            conn.close()
            return redirect(url_for("edit_profile"))

        conn.execute("""
            UPDATE users
            SET
                full_name = ?,
                phone = ?
            WHERE id = ?
        """, (name, phone, session["user_id"]))

        conn.commit()
        conn.close()

        flash("Profile updated successfully!", "success")
        return redirect(url_for("profile"))

    # ------------------------
    # GET REQUEST
    # ------------------------

    user = conn.execute("""
        SELECT
            username,
            full_name,
            phone
        FROM users
        WHERE id = ?
    """, (session["user_id"],)).fetchone()

    conn.close()

    return render_template(
        "edit_profile.html",
        user=user
    )


@app.route("/change_password", methods=["GET", "POST"])
def change_password():
    if "user_id" not in session:
        return redirect(url_for("login"))

    if request.method == "POST":
        current_password = request.form["current_password"]
        new_password = request.form["new_password"]

        conn = get_db_connection()

        user = conn.execute(
            """
            SELECT *
            FROM users
            WHERE id=?
            """,
            (session["user_id"],)
        ).fetchone()

        if not user:
            conn.close()
            flash("User not found.", "error")
            return redirect(url_for("login"))

        if not check_password_hash(user["password"], current_password):
            conn.close()
            flash("Current password is incorrect.", "error")
            return redirect(url_for("change_password"))

        valid, message = validate_password(new_password)

        if not valid:
            conn.close()
            flash(message, "error")
            return redirect(url_for("change_password"))

        if check_password_hash(user["password"], new_password):
            conn.close()
            flash("New password cannot be the same as the current password.", "error")
            return redirect(url_for("change_password"))

        hashed_password = generate_password_hash(new_password)

        conn.execute(
            """
            UPDATE users
            SET password=?
            WHERE id=?
            """,
            (hashed_password, session["user_id"])
        )

        conn.commit()
        conn.close()

        flash("Password changed successfully.", "success")
        return redirect(url_for("profile"))

    return render_template("change_password.html")


@app.route("/place_order", methods=["POST"])
def place_order():

    if session.get("role") != "customer":
        return redirect(url_for("login"))

    cart = json.loads(request.form["cartData"])

    total_amount = sum(
        item["price"] * item["quantity"]
        for item in cart
    )

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
    INSERT INTO orders
    (user_id, total_amount, status, created_at)
    VALUES (?, ?, ?, ?)
""", (
    session["user_id"],
    total_amount,
    "Received",
    datetime.now().strftime("%Y-%m-%d %H:%M:%S")
))

    order_id = cursor.lastrowid

    for item in cart:

        cursor.execute("""
            INSERT INTO order_items
            (order_id, item_name, price, quantity)
            VALUES (?, ?, ?, ?)
        """, (
            order_id,
            item["name"],
            item["price"],
            item["quantity"]
        ))

    conn.commit()
    conn.close()

    return render_template(
        "order_success.html",
        order_id=order_id
    )

# -----------------------
# STAFF DASHBOARD
# -----------------------

@app.route("/staff")
def staff_dashboard():

    if session.get("role") != "staff":
        return redirect(url_for("login"))

    conn = get_db_connection()

    # Get all orders
    orders = conn.execute("""
        SELECT *
        FROM orders
        ORDER BY id DESC
    """).fetchall()

    orders_with_items = []

    now = datetime.now()

    # Dashboard Statistics
    total_orders = len(orders)
    received = 0
    preparing = 0
    completed = 0

    for order in orders:

        # Count order status
        if order["status"] == "Received":
            received += 1

        elif order["status"] == "Preparing":
            preparing += 1

        elif order["status"] == "Completed":
            completed += 1

        # Get order items
        items = conn.execute("""
            SELECT *
            FROM order_items
            WHERE order_id = ?
        """, (order["id"],)).fetchall()

        # Time Ago
        order_time = datetime.strptime(
            order["created_at"],
            "%Y-%m-%d %H:%M:%S"
        )

        diff = now - order_time

        minutes = int(diff.total_seconds() // 60)
        hours = minutes // 60

        if minutes < 1:
            time_ago = "Just now"

        elif minutes < 60:
            time_ago = f"{minutes} min ago"

        elif hours < 24:
            time_ago = f"{hours} hr ago"

        else:
            days = hours // 24
            time_ago = (
                f"{days} day ago"
                if days == 1
                else f"{days} days ago"
            )

        orders_with_items.append({

            "id": order["id"],
            "status": order["status"],
            "created_at": order["created_at"],
            "time_ago": time_ago,
            "total_amount": order["total_amount"],
            "items": items

        })

    conn.close()

    return render_template(

        "staff_dashboard.html",

        orders=orders_with_items,

        total_orders=total_orders,
        received=received,
        preparing=preparing,
        completed=completed

    )


@app.route("/staff/menu")
def staff_menu():

    if session.get("role") != "staff":
        return redirect(url_for("login"))

    conn = get_db_connection()

    menu_items = conn.execute("""
        SELECT *
        FROM menu
        ORDER BY id DESC
    """).fetchall()

    conn.close()

    return render_template(
        "staff_menu.html",
        menu_items=menu_items
    )


@app.route("/staff/add_menu", methods=["POST"])
def add_menu():

    if session.get("role") != "staff":
        return redirect(url_for("login"))

    name = request.form["name"].strip()
    price = float(request.form["price"])
    category = request.form["category"]

    if price <= 0:
        flash("Price must be greater than zero.", "error")
        return redirect(url_for("staff_menu"))

    file = request.files.get("image")

    if file and file.filename:
        filename = file.filename
        file.save(os.path.join("static/images", filename))
    else:
        filename = "default.jpg"

    conn = get_db_connection()

    existing = conn.execute("""
        SELECT id
        FROM menu
        WHERE LOWER(name)=LOWER(?)
    """, (name,)).fetchone()

    if existing:
        conn.close()
        flash("Menu item already exists.", "warning")
        return redirect(url_for("staff_menu"))

    conn.execute("""
        INSERT INTO menu
        (
            name,
            price,
            category,
            image
        )
        VALUES (?, ?, ?, ?)
    """, (
        name,
        price,
        category,
        filename
    ))

    conn.commit()
    conn.close()

    flash("Menu item added successfully.", "success")

    return redirect(url_for("staff_menu"))


@app.route("/staff/toggle_stock/<int:id>")
def toggle_stock(id):

    if session.get("role") != "staff":
        return redirect(url_for("login"))

    conn = get_db_connection()

    item = conn.execute("""
        SELECT available
        FROM menu
        WHERE id=?
    """, (id,)).fetchone()

    if not item:
        conn.close()
        flash("Menu item not found.", "error")
        return redirect(url_for("staff_menu"))

    new_status = 0 if item["available"] else 1

    conn.execute("""
        UPDATE menu
        SET available=?
        WHERE id=?
    """, (
        new_status,
        id
    ))

    conn.commit()
    conn.close()

    flash("Stock status updated successfully.", "success")

    return redirect(url_for("staff_menu"))


@app.route("/staff/delete_menu/<int:id>")
def delete_menu(id):

    if session.get("role") != "staff":
        return redirect(url_for("login"))

    conn = get_db_connection()

    item = conn.execute("""
        SELECT id
        FROM menu
        WHERE id=?
    """, (id,)).fetchone()

    if not item:
        conn.close()
        flash("Menu item not found.", "error")
        return redirect(url_for("staff_menu"))

    conn.execute("""
        DELETE FROM menu
        WHERE id=?
    """, (id,))

    conn.commit()
    conn.close()

    flash("Menu item deleted successfully.", "success")

    return redirect(url_for("staff_menu"))


@app.route("/staff/edit_menu/<int:id>")
def edit_menu(id):

    if session.get("role") != "staff":
        return redirect(url_for("login"))

    conn = get_db_connection()

    item = conn.execute("""
        SELECT *
        FROM menu
        WHERE id=?
    """, (id,)).fetchone()

    conn.close()

    if not item:
        flash("Menu item not found.", "error")
        return redirect(url_for("staff_menu"))

    return render_template(
        "edit_menu.html",
        item=item
    )

@app.route("/staff/update_menu/<int:id>", methods=["POST"])
def update_menu(id):

    if session.get("role") != "staff":
        return redirect(url_for("login"))

    name = request.form["name"].strip()
    price = float(request.form["price"])
    category = request.form["category"]

    if price <= 0:
        flash("Price must be greater than zero.", "error")
        return redirect(url_for("edit_menu", id=id))

    conn = get_db_connection()

    item = conn.execute("""
        SELECT *
        FROM menu
        WHERE id=?
    """, (id,)).fetchone()

    if not item:
        conn.close()
        flash("Menu item not found.", "error")
        return redirect(url_for("staff_menu"))

    file = request.files.get("image")

    if file and file.filename:

        filename = file.filename
        file.save(os.path.join("static/images", filename))

    else:

        filename = item["image"]

    conn.execute("""
        UPDATE menu
        SET
            name=?,
            price=?,
            category=?,
            image=?
        WHERE id=?
    """, (
        name,
        price,
        category,
        filename,
        id
    ))

    conn.commit()
    conn.close()

    flash("Menu item updated successfully.", "success")

    return redirect(url_for("staff_menu"))

@app.route("/update_order/<int:order_id>", methods=["POST"])
def update_order(order_id):

    if session.get("role") != "staff":
        return redirect(url_for("login"))

    new_status = request.form["status"]

    allowed_flow = {

        "Received": ["Preparing"],

        "Preparing": ["Completed"],

        "Completed": [],

        "Cancelled": []

    }

    conn = get_db_connection()

    order = conn.execute("""
        SELECT status
        FROM orders
        WHERE id=?
    """, (order_id,)).fetchone()

    if not order:

        conn.close()

        flash("Order not found.", "error")

        return redirect(url_for("staff_dashboard"))

    current_status = order["status"]

    if new_status not in allowed_flow.get(current_status, []):

        conn.close()

        flash("Invalid order status update.", "error")

        return redirect(url_for("staff_dashboard"))

    conn.execute("""
        UPDATE orders
        SET status=?
        WHERE id=?
    """, (
        new_status,
        order_id
    ))

    conn.commit()
    conn.close()

    flash("Order status updated successfully.", "success")

    return redirect(url_for("staff_dashboard"))


# -----------------------
# FEEDBACK ROUTES
# -----------------------

@app.route("/feedback", methods=["GET", "POST"])
def feedback():

    conn = get_db_connection()
    cur = conn.cursor()

    # -----------------------
    # SUBMIT FEEDBACK
    # -----------------------
    if request.method == "POST":

        if "user_id" not in session:
            flash("Please login to submit feedback.", "error")
            conn.close()
            return redirect(url_for("login"))

        user_id = session["user_id"]
        message = request.form.get("message", "").strip()
        rating = request.form["rating"]

        # Allow only one feedback per customer
        existing = cur.execute(
            """
            SELECT id
            FROM feedback
            WHERE user_id = ?
            """,
            (user_id,)
        ).fetchone()

        if existing:
            flash("You have already submitted feedback.", "warning")
            conn.close()
            return redirect(url_for("feedback"))

        print("Session user_id:", session.get("user_id"))

        user = cur.execute(
        "SELECT * FROM users WHERE id=?",
        (session.get("user_id"),)
        ).fetchone()

        print("User exists:", user)
        
        cur.execute(
            """
            INSERT INTO feedback (
                user_id,
                message,
                rating
            )
            VALUES (?, ?, ?)
            """,
            (
                user_id,
                message if message else "",
                rating
            )
        )

        conn.commit()

        flash(
            "Thank you for your feedback!",
            "success"
        )

        conn.close()

        return redirect(url_for("feedback"))

    # -----------------------
    # LOAD ALL FEEDBACK
    # -----------------------

    cur.execute(
        """
        SELECT
            feedback.id,
            feedback.message,
            feedback.rating,
            feedback.created_at,
            feedback.admin_reply,
            users.username
        FROM feedback
        JOIN users
            ON users.id = feedback.user_id
        ORDER BY feedback.created_at DESC
        """
    )

    feedbacks = cur.fetchall()

    # -----------------------
    # REVIEW STATISTICS
    # -----------------------

    cur.execute(
        "SELECT AVG(rating) FROM feedback"
    )

    avg = cur.fetchone()[0]

    avg_rating = round(avg, 1) if avg else 0

    cur.execute(
        "SELECT COUNT(*) FROM feedback"
    )

    total_reviews = cur.fetchone()[0]

    rating_counts = {}

    for i in range(1, 6):

        cur.execute(
            """
            SELECT COUNT(*)
            FROM feedback
            WHERE rating = ?
            """,
            (i,)
        )

        rating_counts[i] = cur.fetchone()[0]

    conn.close()

    return render_template(
        "feedback.html",
        feedbacks=feedbacks,
        avg_rating=avg_rating,
        total_reviews=total_reviews,
        rating_counts=rating_counts
    )

# -----------------------
# ADMIN ROUTES
# -----------------------

@app.route("/admin")
def admin_dashboard():
    if session.get("role") != "admin":
        return "Access Denied"

    conn = get_db_connection()

    total_orders = conn.execute(
        "SELECT COUNT(*) FROM orders"
    ).fetchone()[0]

    total_revenue = conn.execute(
        "SELECT IFNULL(SUM(total_amount),0) FROM orders"
    ).fetchone()[0]

    total_customers = conn.execute(
        "SELECT COUNT(*) FROM users WHERE role='customer'"
    ).fetchone()[0]

    staff_members = conn.execute(
        "SELECT id, username FROM users WHERE role='staff'"
    ).fetchall()

    daily_rows = conn.execute("""
        SELECT strftime('%H:00', created_at) as label,
           COUNT(*) as orders,
           IFNULL(SUM(total_amount), 0) as revenue
        FROM orders
        WHERE DATE(created_at) = DATE('now')
        GROUP BY strftime('%H', created_at)
    """).fetchall()

    daily_map = {
        row["label"]: {"orders": row["orders"], "revenue": row["revenue"]}
        for row in daily_rows
    }

    daily_dates = [f"{h:02d}:00" for h in range(24)]
    daily_orders = [daily_map.get(label, {}).get("orders", 0) for label in daily_dates]
    daily_revenues = [daily_map.get(label, {}).get("revenue", 0) for label in daily_dates]

    weekly_rows = conn.execute("""
    SELECT DATE(created_at) as full_date,
           COUNT(*) as orders,
           IFNULL(SUM(total_amount), 0) as revenue
        FROM orders
        WHERE DATE(created_at) >= DATE('now', '-6 days')
        GROUP BY DATE(created_at)
    """).fetchall()

    weekly_map = {
        row["full_date"]: {"orders": row["orders"], "revenue": row["revenue"]}
        for row in weekly_rows
    }

    weekly_dates = []
    weekly_orders = []
    weekly_revenues = []

    for i in range(6, -1, -1):
        day = datetime.now() - timedelta(days=i)
        label = day.strftime("%a")
        full_date = day.strftime("%Y-%m-%d")

        weekly_dates.append(label)
        weekly_orders.append(weekly_map.get(full_date, {}).get("orders", 0))
        weekly_revenues.append(weekly_map.get(full_date, {}).get("revenue", 0))

    today = datetime.now()
    days_in_month = monthrange(today.year, today.month)[1]

    monthly_rows = conn.execute("""
    SELECT strftime('%d', created_at) as day,
           COUNT(*) as orders,
           IFNULL(SUM(total_amount), 0) as revenue
        FROM orders
        WHERE strftime('%Y-%m', created_at) = strftime('%Y-%m', 'now')
        GROUP BY strftime('%d', created_at)
    """).fetchall()

    monthly_map = {
        int(row["day"]): {"orders": row["orders"], "revenue": row["revenue"]}
        for row in monthly_rows
    }

    monthly_dates = [str(day) for day in range(1, days_in_month + 1)]
    monthly_orders = [monthly_map.get(day, {}).get("orders", 0) for day in range(1, days_in_month + 1)]
    monthly_revenues = [monthly_map.get(day, {}).get("revenue", 0) for day in range(1, days_in_month + 1)]

    yearly_rows = conn.execute("""
    SELECT strftime('%m', created_at) as month,
           COUNT(*) as orders,
           IFNULL(SUM(total_amount), 0) as revenue
        FROM orders
        WHERE strftime('%Y', created_at) = strftime('%Y', 'now')
        GROUP BY strftime('%m', created_at)
    """).fetchall()

    yearly_map = {
        int(row["month"]): {"orders": row["orders"], "revenue": row["revenue"]}
        for row in yearly_rows
    }

    month_names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                   "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

    yearly_dates = month_names
    yearly_orders = [yearly_map.get(i, {}).get("orders", 0) for i in range(1, 13)]
    yearly_revenues = [yearly_map.get(i, {}).get("revenue", 0) for i in range(1, 13)]

    conn.close()

    return render_template(
        "admin_dashboard.html",
        total_orders=total_orders,
        total_revenue=total_revenue,
        total_customers=total_customers,
        staff_members=staff_members,

        daily_dates=daily_dates,
        daily_orders=daily_orders,
        daily_revenues=daily_revenues,

        weekly_dates=weekly_dates,
        weekly_orders=weekly_orders,
        weekly_revenues=weekly_revenues,

        monthly_dates=monthly_dates,
        monthly_orders=monthly_orders,
        monthly_revenues=monthly_revenues,

        yearly_dates=yearly_dates,
        yearly_orders=yearly_orders,
        yearly_revenues=yearly_revenues
    )


@app.route("/admin/feedback")
def view_feedback():

    if session.get("role") != "admin":
        return redirect(url_for("login"))

    conn = get_db_connection()

    feedbacks = conn.execute("""

        SELECT

            feedback.id,
            feedback.message,
            feedback.rating,
            feedback.created_at,
            feedback.admin_reply,
            users.username

        FROM feedback

        JOIN users

            ON users.id = feedback.user_id

        ORDER BY feedback.created_at DESC

    """).fetchall()

    conn.close()

    return render_template(
        "admin_feedback.html",
        feedbacks=feedbacks
    )


@app.route("/admin/delete_feedback/<int:id>", methods=["POST"])
def delete_feedback(id):

    if session.get("role") != "admin":
        return redirect(url_for("login"))

    conn = get_db_connection()

    conn.execute(
        "DELETE FROM feedback WHERE id=?",
        (id,)
    )

    conn.commit()
    conn.close()

    flash("Feedback deleted successfully.", "success")

    return redirect(url_for("view_feedback"))


@app.route("/admin/reply_feedback/<int:id>", methods=["POST"])
def reply_feedback(id):

    if session.get("role") != "admin":
        return redirect(url_for("login"))

    reply = request.form["reply"].strip()

    if reply == "":
        flash("Reply cannot be empty.", "error")
        return redirect(url_for("view_feedback"))

    conn = get_db_connection()

    conn.execute("""
        UPDATE feedback
        SET admin_reply = ?
        WHERE id = ?
    """, (reply, id))

    conn.commit()
    conn.close()

    flash("Reply saved successfully.", "success")

    return redirect(url_for("view_feedback"))


@app.route("/admin/sales")
def sales_report():
    if session.get("role") != "admin":
        return "Access Denied"

    conn = get_db_connection()

    sold_items = conn.execute("""
        SELECT
            item_name,
            SUM(quantity) AS total_sold,
            SUM(quantity * price) AS total_revenue,
            COUNT(DISTINCT order_id) AS total_orders
        FROM order_items
        GROUP BY item_name
        ORDER BY total_sold DESC
    """).fetchall()

    conn.close()

    return render_template("sales_report.html", sold_items=sold_items)


@app.route("/analytics_data/<period>")
def analytics_data(period):
    if session.get("role") != "admin":
        return jsonify({"error": "Access Denied"})

    conn = get_db_connection()

    if period == "daily":
        query = """
            SELECT DATE(created_at) as label,
                   COUNT(*) as orders,
                   SUM(total_amount) as revenue
            FROM orders
            GROUP BY DATE(created_at)
            ORDER BY DATE(created_at)
        """
    elif period == "weekly":
        query = """
            SELECT strftime('%Y-%W', created_at) as label,
                   COUNT(*) as orders,
                   SUM(total_amount) as revenue
            FROM orders
            GROUP BY strftime('%Y-%W', created_at)
            ORDER BY strftime('%Y-%W', created_at)
        """
    elif period == "monthly":
        query = """
            SELECT strftime('%Y-%m', created_at) as label,
                   COUNT(*) as orders,
                   SUM(total_amount) as revenue
            FROM orders
            GROUP BY strftime('%Y-%m', created_at)
            ORDER BY strftime('%Y-%m', created_at)
        """
    else:
        query = """
            SELECT strftime('%Y', created_at) as label,
                   COUNT(*) as orders,
                   SUM(total_amount) as revenue
            FROM orders
            GROUP BY strftime('%Y', created_at)
            ORDER BY strftime('%Y', created_at)
        """

    rows = conn.execute(query).fetchall()
    conn.close()

    return jsonify({
        "labels": [row["label"] for row in rows],
        "orders": [row["orders"] for row in rows],
        "revenue": [row["revenue"] for row in rows]
    })


@app.route("/export_orders")
def export_orders():
    if session.get("role") != "admin":
        return "Access Denied"

    conn = get_db_connection()
    orders = conn.execute("""
        SELECT id, user_id, total_amount, status, created_at
        FROM orders
        ORDER BY id DESC
    """).fetchall()

    total_orders = len(orders)
    total_revenue = sum(o["total_amount"] for o in orders)

    conn.close()

    file_path = "orders_report.pdf"
    doc = SimpleDocTemplate(file_path)
    elements = []

    styles = getSampleStyleSheet()

    elements.append(Paragraph("<b>SnackQ Order Report</b>", styles["Title"]))
    elements.append(Spacer(1, 0.3 * inch))

    elements.append(Paragraph(
        f"Generated On: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        styles["Normal"]
    ))
    elements.append(Spacer(1, 0.2 * inch))

    elements.append(Paragraph("<b>Summary</b>", styles["Heading2"]))
    elements.append(Spacer(1, 0.2 * inch))
    elements.append(Paragraph(f"Total Orders: {total_orders}", styles["Normal"]))
    elements.append(Paragraph(f"Total Revenue: ₹{total_revenue}", styles["Normal"]))
    elements.append(Spacer(1, 0.4 * inch))

    data = [["Order ID", "User ID", "Total (₹)", "Status", "Date"]]

    for o in orders:
        data.append([
            o["id"],
            o["user_id"],
            o["total_amount"],
            o["status"],
            o["created_at"]
        ])

    table = Table(data, repeatRows=1)

    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("ALIGN", (2, 1), (2, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))

    elements.append(table)

    doc.build(elements)

    return send_file(file_path, as_attachment=True)


@app.route("/add_staff", methods=["POST"])
def add_staff():

    # Only admin can add staff
    if session.get("role") != "admin":
        flash("Access denied.", "error")
        return redirect(url_for("login"))

    username = request.form.get("username", "").strip()
    full_name = request.form.get("full_name", "").strip()
    email = request.form.get("email", "").strip()
    phone = request.form.get("phone", "").strip()
    password = request.form.get("password", "")

    # Required fields
    if not username or not full_name or not email or not password:
        flash("Please fill in all required fields.", "error")
        return redirect(url_for("admin_dashboard"))

    # Password validation
    valid, message = validate_password(password)

    if not valid:
        flash(message, "error")
        return redirect(url_for("admin_dashboard"))

    conn = get_db_connection()

    try:

        # Username already exists?
        existing_user = conn.execute(
            "SELECT id FROM users WHERE username = ?",
            (username,)
        ).fetchone()

        if existing_user:
            flash("Username already exists.", "error")
            return redirect(url_for("admin_dashboard"))

        # Email already exists?
        existing_email = conn.execute(
            "SELECT id FROM users WHERE email = ?",
            (email,)
        ).fetchone()

        if existing_email:
            flash("Email is already registered.", "error")
            return redirect(url_for("admin_dashboard"))

        hashed_password = generate_password_hash(password)

        conn.execute("""
            INSERT INTO users
            (
                username,
                password,
                role,
                full_name,
                email,
                phone,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
        """, (
            username,
            hashed_password,
            "staff",
            full_name,
            email,
            phone
        ))

        conn.commit()

        flash("Staff member added successfully!", "success")

    except sqlite3.Error as e:

        print("Database Error:", e)

        flash("Unable to add staff.", "error")

    finally:

        conn.close()

    return redirect(url_for("admin_dashboard"))


@app.route("/delete_staff/<int:staff_id>", methods=["POST"])
def delete_staff(staff_id):
    if session.get("role") != "admin":
        return "Access Denied"

    conn = get_db_connection()

    staff = conn.execute("""
        SELECT * FROM users
        WHERE id = ? AND role = 'staff'
    """, (staff_id,)).fetchone()

    if not staff:
        conn.close()
        flash("Staff not found.", "error")
        return redirect(url_for("admin_dashboard"))

    conn.execute("DELETE FROM users WHERE id = ?", (staff_id,))
    conn.commit()
    conn.close()

    flash("Staff deleted successfully!", "success")
    return redirect(url_for("admin_dashboard"))


# -----------------------
# AUTH ROUTES
# -----------------------

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":

        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")
        if password != confirm_password:
            flash("Passwords do not match.", "error")
            return render_template("register.html")
        full_name = request.form.get("full_name", "").strip()
        email = request.form.get("email", "").strip()
        phone = request.form.get("phone", "").strip()

        role = "customer"

        # Required fields
        if not username or not password:
            flash("Username and password are required.", "error")
            return render_template("register.html")

        # Password validation
        valid, message = validate_password(password)

        if not valid:
            flash(message, "error")
            return render_template("register.html")

        conn = get_db_connection()

        try:
            # Check existing username
            existing_user = conn.execute(
                "SELECT id FROM users WHERE username = ?",
                (username,)
            ).fetchone()

            if existing_user:
                flash("Username already exists.", "error")
                return render_template("register.html")

            # Check existing email
            if email:
                existing_email = conn.execute(
                    "SELECT id FROM users WHERE email = ?",
                    (email,)
                ).fetchone()

                if existing_email:
                    flash("Email is already registered.", "error")
                    return render_template("register.html")

            hashed_password = generate_password_hash(password)

            conn.execute("""
                INSERT INTO users (
                    username,
                    password,
                    role,
                    full_name,
                    email,
                    phone,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
            """, (
                username,
                hashed_password,
                role,
                full_name,
                email,
                phone
            ))

            conn.commit()

            flash(
                "Registration successful! Please login.",
                "success"
            )

            return redirect(url_for("login"))

        except sqlite3.Error as e:
            print("Database Error:", e)
            flash(
                "Unable to register. Please try again.",
                "error"
            )

        finally:
            conn.close()

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    username = ""

    if "login_attempts" not in session:
        session["login_attempts"] = 0

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        # Check for empty fields
        if not username or not password:
            flash("Username and password are required.", "error")
            return render_template("login.html", username=username)

        # Limit failed login attempts
        if session["login_attempts"] >= 5:
            flash("Too many failed attempts. Try again later.", "error")
            return render_template("login.html", username=username)

        try:
            conn = get_db_connection()

            user = conn.execute(
                "SELECT * FROM users WHERE username = ?",
                (username,)
            ).fetchone()
            print("User:", user)
            conn.close()

        except Exception as e:
            print(f"Database Error: {e}")
            flash("Unable to connect to the database.", "error")
            return render_template("login.html", username=username)

        # Successful login
        if user:
            print("Stored password:", user["password"])
            print("Entered password:", password)
            print("Password match:", check_password_hash(user["password"], password))
        if user and check_password_hash(user["password"], password):
            session.clear()

            session["user"] = user["username"]
            session["role"] = user["role"]
            session["user_id"] = user["id"]
            session["login_attempts"] = 0

            flash(f"Welcome back, {user['username']}!", "success")
            return redirect(url_for("home"))

        # Invalid credentials
        session["login_attempts"] += 1
        flash(
            f"Invalid username or password. ({session['login_attempts']}/5)",
            "error"
        )

        return render_template("login.html", username=username)

    return render_template("login.html", username=username)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("home"))


# -----------------------
# RUN APP
# -----------------------

if __name__ == "__main__":
    init_db()
    app.run(debug=True)