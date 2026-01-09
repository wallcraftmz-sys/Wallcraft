from flask import Flask, render_template, request, session, redirect, url_for, jsonify
import os
import requests

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "wallcraft_secret_key")

# ===== PRODUCTS =====
products = [
    {
        "id": 1,
        "category": "walls",
        "name_ru": "Жидкие обои — Ocean",
        "name_lv": "Šķidrie tapetes — Ocean",
        "description_ru": "Высококачественные жидкие обои",
        "description_lv": "Augstas kvalitātes tapetes",
        "price": 25.00,
        "image": "images/IMG_0856.PNG"
    }
]

# ===== TELEGRAM =====
def send_telegram(message: str):
    token = os.getenv("TG_BOT_TOKEN")
    chat_id = os.getenv("TG_CHAT_ID")

    if not token or not chat_id:
        print("TG ERROR: env vars not set")
        return

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message
    }

    try:
        r = requests.post(url, json=payload, timeout=10)
        if r.status_code != 200:
            print("TG ERROR:", r.text)
    except Exception as e:
        print("TG EXCEPTION:", e)

# ===== LANGUAGE =====
@app.before_request
def set_lang():
    session["lang"] = request.args.get("lang") or session.get("lang") or "ru"

# ===== PAGES =====
@app.route("/")
def index():
    return render_template("index.html", products=products, lang=session["lang"])

@app.route("/catalog")
def catalog():
    return render_template("catalog.html", products=products, lang=session["lang"])

@app.route("/product/<int:product_id>")
def product(product_id):
    item = next((p for p in products if p["id"] == product_id), None)
    if not item:
        return redirect(url_for("catalog"))
    return render_template("product.html", product=item, lang=session["lang"])

# ===== CART API =====
@app.route("/api/add_to_cart/<int:product_id>", methods=["POST"])
def add_to_cart(product_id):
    cart = session.get("cart", {})
    pid = str(product_id)
    cart[pid] = cart.get(pid, 0) + 1
    session["cart"] = cart
    return jsonify(success=True, cart_total_items=sum(cart.values()))

@app.route("/api/update_cart/<int:pid>/<action>", methods=["POST"])
def update_cart(pid, action):
    cart = session.get("cart", {})
    pid_str = str(pid)

    if pid_str in cart:
        if action == "plus":
            cart[pid_str] += 1
        elif action == "minus":
            cart[pid_str] -= 1
            if cart[pid_str] <= 0:
                del cart[pid_str]

    session["cart"] = cart

    total = 0.0
    subtotal = 0.0
    qty = cart.get(pid_str, 0)

    for k, q in cart.items():
        pr = next((p for p in products if p["id"] == int(k)), None)
        if not pr:
            continue
        total += pr["price"] * q
        if k == pid_str:
            subtotal = pr["price"] * q

    return jsonify(
        qty=qty,
        subtotal=subtotal,
        total=total,
        cart_total_items=sum(cart.values())
    )

# ===== CART PAGE =====
@app.route("/cart")
def cart():
    cart = session.get("cart", {})
    items = []
    total = 0.0

    for pid_str, qty in cart.items():
        pr = next((p for p in products if p["id"] == int(pid_str)), None)
        if pr:
            items.append({"product": pr, "qty": qty})
            total += pr["price"] * qty

    return render_template("cart.html", cart_items=items, total=total, lang=session["lang"])

# ===== ORDER =====
@app.route("/order", methods=["GET", "POST"])
def order():
    lang = session.get("lang", "ru")
    success = False
    cart = session.get("cart", {})

    if request.method == "POST" and cart:
        name = request.form.get("name", "").strip()
        contact = request.form.get("contact", "").strip()

        lines = []
        total = 0.0

        for pid_str, qty in cart.items():
            pr = next((p for p in products if p["id"] == int(pid_str)), None)
            if not pr:
                continue
            subtotal = pr["price"] * qty
            total += subtotal
            lines.append(
                f"{pr['name_ru']} — {qty} шт × {pr['price']} € = {subtotal:.2f} €"
            )

        message = (
            "🛒 НОВЫЙ ЗАКАЗ WALLCRAFT\n\n"
            f"👤 Имя: {name}\n"
            f"📞 Контакт: {contact}\n\n"
            "📦 СОСТАВ ЗАКАЗА:\n"
            + "\n".join(lines)
            + f"\n\n💰 ИТОГО: {total:.2f} €"
        )

        send_telegram(message)

        session["cart"] = {}
        success = True

    return render_template("order.html", success=success, lang=lang)

if __name__ == "__main__":
    app.run(debug=True)
