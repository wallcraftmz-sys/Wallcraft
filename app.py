from flask import Flask, render_template, request, session, redirect, url_for, jsonify
import smtplib
from email.mime.text import MIMEText
import os

app = Flask(__name__)
app.secret_key = "wallcraft_secret_key"

products = [
    {
        "id": 1,
        "name_ru": "Жидкие обои — Ocean",
        "name_lv": "Šķidrie tapetes — Ocean",
        "description_ru": "Высококачественные жидкие обои",
        "description_lv": "Augstas kvalitātes tapetes",
        "price": 25.00,
        "image": "images/IMG_0856.PNG"
    }
]

@app.before_request
def set_lang():
    session["lang"] = request.args.get("lang") or session.get("lang") or "ru"

@app.route("/")
def index():
    return render_template(
        "index.html",
        products=products,
        lang=session["lang"]
    )

@app.route("/catalog")
def catalog():
    return render_template(
        "catalog.html",
        products=products,
        lang=session["lang"]
    )

@app.route("/product/<int:product_id>")
def product(product_id):
    product = next((p for p in products if p["id"] == product_id), None)
    if not product:
        return redirect(url_for("catalog"))

    return render_template(
        "product.html",
        product=product,
        lang=session["lang"]
    )

@app.route("/api/add_to_cart/<int:product_id>", methods=["POST"])
def add_to_cart(product_id):
    cart = session.get("cart", {})
    cart[str(product_id)] = cart.get(str(product_id), 0) + 1
    session["cart"] = cart
    return jsonify(success=True)
  
@app.route("/api/update_cart/<int:pid>/<action>", methods=["POST"])
def update_cart(pid, action):
    cart = session.get("cart", {})
    pid = str(pid)

    if pid in cart:
        if action == "plus":
            cart[pid] += 1
        elif action == "minus":
            cart[pid] -= 1
            if cart[pid] <= 0:
                del cart[pid]

    session["cart"] = cart

    total = 0
    subtotal = 0
    qty = cart.get(pid, 0)

    for k, q in cart.items():
        product = next(p for p in products if p["id"] == int(k))
        total += product["price"] * q
        if k == pid:
            subtotal = product["price"] * q

    return {
        "qty": qty,
        "subtotal": subtotal,
        "total": total
    }

@app.route("/cart")
def cart():
    cart = session.get("cart", {})
    items = []
    total = 0

    for pid, qty in cart.items():
        product = next((p for p in products if p["id"] == int(pid)), None)
        if product:
            items.append({
                "product": product,
                "qty": qty
            })
            total += product["price"] * qty

    return render_template(
        "cart.html",
        cart_items=items,
        total=total,
        lang=session["lang"]
    )
@app.route("/order", methods=["GET", "POST"])
def order():
    lang = session.get("lang", "ru")
    success = False

    if request.method == "POST":
        name = request.form.get("name")
        contact = request.form.get("contact")

        text = f"Новый заказ Wallcraft\n\nИмя: {name}\nКонтакт: {contact}"

        msg = MIMEText(text)
        msg["Subject"] = "Новая заявка Wallcraft"
        msg["From"] = os.environ["GMAIL_EMAIL"]
        msg["To"] = os.environ["GMAIL_EMAIL"]

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(
                os.environ["GMAIL_EMAIL"],
                os.environ["GMAIL_APP_PASSWORD"]
            )
            server.send_message(msg)

        session["cart"] = {}
        success = True

    return render_template("order.html", success=success, lang=lang)
    
if __name__ == "__main__":
    app.run(debug=True)
