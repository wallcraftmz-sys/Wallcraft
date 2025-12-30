from flask import Flask, render_template, request, session

app = Flask(__name__)
app.secret_key = 'wallcraft_secret_key'

# Пример товара
products = [{
    "id": 1,
    "name_lv": "Šķidrie tapetes - South 941",
    "name_ru": "Жидкие обои - South 941",
    "description_lv": "Materiāls dekoratīvai sienu un griestu apdarei...",
    "description_ru": "Материал для декоративной отделки стен и потолков...",
    "price": 25.00,
    "image": "liquid_wallpaper.jpg"
}]

@app.before_request
def get_lang():
    session['lang'] = request.args.get('lang') or session.get('lang') or 'lv'

@app.route('/')
def index():
    lang = session.get('lang')
    return render_template('index.html', lang=lang, products=products)

@app.route('/catalog')
def catalog():
    lang = session.get('lang')
    return render_template('catalog.html', lang=lang, products=products)

@app.route('/product/<int:id>')
def product(id):
    lang = session.get('lang')
    product_item = next((p for p in products if p['id'] == id), None)
    return render_template('product.html', lang=lang, product=product_item)

@app.route("/order", methods=["GET", "POST"])
def order():
    if request.method == "POST":
        # Получаем данные из формы
        name = request.form.get("name")
        contact = request.form.get("contact")

        print("Новая заявка:")
        print("Имя:", name)
        print("Контакт:", contact)

        # Передаём success=True, чтобы показать сообщение на странице
        return render_template("order.html", success=True, lang=session.get('lang'))

    # Для GET-запроса просто показываем форму
    return render_template("order.html", lang=session.get('lang'))

if __name__ == '__main__':
    # Локально используем порт 5000
    app.run(host="0.0.0.0", port=5000, debug=True)
