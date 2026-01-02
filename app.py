import sqlite3
import threading
import os
import smtplib
from functools import wraps
from flask import Flask, render_template, request, session, redirect, url_for
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.secret_key = "wallcraft_secret_key"

# ================== ТОВАРЫ ==================
products = [
    {
        "id": 1,
        "category": "walls",
        "name_ru": "Жидкие обои — Ocean",
        "description_ru": "Высококачественные жидкие обои для стен",
        "price": 25.00,
        "image": "https://cdn.pixabay.com/photo/2016/11/29/06/16/texture-1868576_1280.jpg"
    },
    {
        "id": 2,
        "category": "walls",
        "name_ru": "Жидкие обои — Golden",
        "description_ru": "Эффектные декоративные жидкие обои",
        "price": 30.00,
        "image": "https://cdn.pixabay.com/photo/2018/10/18/18/38/wall-3759044_1280.jpg"
    },
    {
        "id": 3,
        "category": "walls",
        "name_ru": "Жидкие обои — Modern",
        "description_ru": "Современный стиль для интерьера",
        "price": 28.00,
        "image": "https://cdn.pixabay.com/photo/2017/08/07/12/50/wall-2608854_1280.jpg"
    }
]

# ================== ЯЗЫК ==================
@app.before_request
def set_lang():
    session["lang"] = request.args.get("lang") or session.get("lang") or "ru"

# ================== ГЛАВНАЯ ==================
@app.route("/")
def index():
    return render_template("index.html", products=products)

# ================== КАТАЛОГ ==================
@app.route("/catalog")
def catalog():
    cat = request.args.get("cat")
    min_price = request.args.get("min_price")
    max_price = request.args.get("max_price")

    filtered = products

    if cat:
        filtered = [p for p in filtered if p["category"] == cat]
    if min_price:
        filtered = [p for p in filtered if p["price"] >= float(min_price)]
    if max_price:
        filtered = [p for p in filtered if p["price"] <= float(max_price)]

    return render_template("catalog.html", products=filtered)

# ================== ДОБАВИТЬ В КОРЗИНУ ==================
@app.route("/add_to_cart/<int:product_id>")
def add_to_cart(product_id):
    cart = session.get("cart", {})
    cart[str(product_id)] = cart.get(str(product_id), 0) + 1
    session["cart"] = cart
    return redirect(url_for("cart"))

# ================== КОРЗИНА ==================
@app.route("/cart")
def cart():
    cart = session.get("cart", {})
    cart_items = []
    total = 0

    for pid, qty in cart.items():
        product = next((p for p in products if p["id"] == int(pid)), None)
        if product:
            cart_items.append({"product": product, "qty": qty})
            total += product["price"] * qty

    return render_template("cart.html", cart_items=cart_items, total=total)

# ================== + / − ==================
@app.route("/update_cart/<int:product_id>/<action>")
def update_cart(product_id, action):
    cart = session.get("cart", {})
    pid = str(product_id)

    if pid in cart:
        if action == "plus":
            cart[pid] += 1
        elif action == "minus":
            cart[pid] -= 1
            if cart[pid] <= 0:
                del cart[pid]

    session["cart"] = cart
    return redirect(url_for("cart"))

# ================== ЗАКАЗ ==================
@app.route("/order", methods=["GET", "POST"])
def order():
    if request.method == "POST":
        name = request.form.get("name")
        contact = request.form.get("contact")

        threading.Thread(target=send_email, args=(name, contact)).start()
        return render_template("order.html", success=True)

    return render_template("order.html")

def send_email(name, contact):
    sender = os.environ.get("WALLCRAFT_EMAIL")
    password = os.environ.get("WALLCRAFT_APP_PASSWORD")

    msg = MIMEMultipart()
    msg["From"] = sender
    msg["To"] = sender
    msg["Subject"] = "Новая заявка с сайта"

    msg.attach(MIMEText(f"Имя: {name}\nКонтакт: {contact}", "plain"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(sender, password)
            server.sendmail(sender, sender, msg.as_string())
    except Exception as e:
        print("Ошибка почты:", e)

# ================== ЗАПУСК ==================
if __name__ == "__main__":
    app.run(debug=True)
