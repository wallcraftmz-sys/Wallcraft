from flask import Flask, render_template, request, session, redirect, url_for, jsonify

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
    product = products[0]
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

@app.route("/cart")
def cart():
    return render_template(
        "cart.html",
        cart_items=[],
        total=0,
        lang=session["lang"]
    )

if __name__ == "__main__":
    app.run(debug=True)
