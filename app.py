import os
import sqlite3
import smtplib
from email.mime.text import MIMEText
from flask import Flask, render_template, request, session, redirect, url_for, jsonify
from functools import wraps
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "wallcraft_secret_key")

DB = "data/wallcraft.db"

# ================== ТОВАРЫ ==================
products = [
    {
        "id": 1,
        "category": "walls",
        "name_ru": "Жидкие обои — Ocean",
        "name_lv": "Šķidrās tapetes — Ocean",
        "description_ru": "Высококачественные жидкие обои для стен",
        "description_lv": "Augstas kvalitātes šķidrās tapetes sienām",
        "price": 25.00,
        "image": "/static/images/ocean.jpg"
    },
    {
        "id": 2,
        "category": "walls",
        "name_ru": "Жидкие обои — Golden",
        "name_lv": "Šķidrās tapetes — Golden",
        "description_ru": "Декоративные жидкие обои",
        "description_lv": "Dekoratīvas šķidrās tapetes",
        "price": 30.00,
        "image": "/static/images/golden.jpg"
    },
    {
        "id": 3,
        "category": "walls",
        "name_ru": "Жидкие обои — Modern",
        "name_lv": "Šķidrās tapetes — Modern",
        "description_ru": "Современный интерьер",
        "description_lv": "Mūsdienīgs interjers",
        "price": 28.00,
        "image": "/static/images/modern.jpg"
    }
]

# ================== ЯЗЫК ==================
@app.before_request
def set_lang():
    session["lang"] = request.args.get("lang") or session.get("lang") or "ru"

# ================== БАЗА ==================
def init_db():
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    # Таблица пользователей
    c.execute("""CREATE TABLE IF NOT EXISTS users(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE,
        password TEXT
    )""")
    # Таблица заказов
    c.execute("""CREATE TABLE IF NOT EXISTS orders(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        name TEXT,
        contact TEXT,
        status TEXT DEFAULT 'Ожидает оплату'
    )""")
    conn.commit()
    conn.close()

init_db()

# ================== ГЛАВНАЯ ==================
@app.route("/")
def index():
    lang = session["lang"]
    return render_template("index.html", products=products, lang=lang, cart_total_items=sum(session.get("cart", {}).values()))

# ================== КАТАЛОГ ==================
@app.route("/catalog")
def catalog():
    lang = session["lang"]
    return render_template("catalog.html", products=products, lang=lang, cart_total_items=sum(session.get("cart", {}).values()))

# ================== КОРЗИНА ==================
@app.route("/cart")
def cart():
    lang = session["lang"]
    cart_items = []
    total = 0
    for pid, qty in session.get("cart", {}).items():
        product = next((p for p in products if p["id"]==int(pid)), None)
        if product:
            cart_items.append({"product": product, "qty": qty})
            total += product["price"] * qty
    return render_template("cart.html", cart_items=cart_items, total=total, lang=lang)

# ================== API ==================
@app.route("/api/add_to_cart/<int:pid>", methods=["POST"])
def api_add_to_cart(pid):
    cart = session.get("cart", {})
    cart[str(pid)] = cart.get(str(pid),0)+1
    session["cart"] = cart
    product = next((p for p in products if p["id"]==pid), None)
    return jsonify({
        "success": True,
        "qty": cart[str(pid)],
        "product_name": product["name_"+session["lang"]],
        "cart_total_items": sum(cart.values())
    })

@app.route("/api/update_cart/<int:pid>/<action>", methods=["POST"])
def api_update_cart(pid, action):
    cart = session.get("cart", {})
    pid_str = str(pid)
    if pid_str in cart:
        if action=="plus": cart[pid_str]+=1
        elif action=="minus": cart[pid_str]-=1
        if cart[pid_str]<=0: del cart[pid_str]
    session["cart"] = cart
    total = sum(next(p["price"] for p in products if p["id"]==int(k))*q for k,q in cart.items())
    return jsonify({"success": True, "qty": cart.get(pid_str,0), "total": total, "cart_total_items": sum(cart.values())})

# ================== ФОРМА ЗАЯВКИ ==================
@app.route("/order", methods=["GET","POST"])
def order():
    lang = session["lang"]
    success = False
    if request.method=="POST":
        name = request.form.get("name")
        contact = request.form.get("contact")
        # Отправка на email
        msg = MIMEText(f"Имя: {name}\nКонтакт: {contact}")
        msg["Subject"] = "Новый заказ Wallcraft"
        msg["From"] = os.environ.get("GMAIL_EMAIL")
        msg["To"] = os.environ.get("GMAIL_EMAIL")
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
            s.login(os.environ.get("GMAIL_EMAIL"), os.environ.get("GMAIL_APP_PASSWORD"))
            s.send_message(msg)
        session["cart"] = {}
        success = True
    return render_template("order.html", success=success, lang=lang)

if __name__=="__main__":
    app.run(debug=True)
