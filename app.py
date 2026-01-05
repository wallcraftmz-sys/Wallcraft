import os
from flask import Flask, render_template, request, session, redirect, url_for

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "wallcraft_secret_key")

# Небольшой список товаров — указывай image как "images/имяфайла.ext"
products = [
    {
        "id": 1,
        "category": "walls",
        "name_ru": "Жидкие обои — Ocean",
        "name_lv": "Šķidrie tapetes — Ocean",
        "description_ru": "Высококачественные жидкие обои для стен",
        "description_lv": "Augstas kvalitātes šķidrie tapetes",
        "price": 25.00,
        "image": "images/IMG_0856.PNG"
    },
    {
        "id": 2,
        "category": "walls",
        "name_ru": "Жидкие обои — Golden",
        "name_lv": "Šķidrie tapetes — Golden",
        "description_ru": "Декоративные жидкие обои",
        "description_lv": "Dekoratīvas šķidrās tapetes",
        "price": 30.00,
        "image": "images/IMG_0856.PNG"
    }
]

@app.before_request
def set_lang():
    # Устанавливаем язык в сессии; можно переключать через ?lang=ru или ?lang=lv
    session['lang'] = request.args.get('lang') or session.get('lang') or 'ru'

@app.route('/')
def index():
    lang = session.get('lang', 'ru')
    # На главной — только картинки и названия (без кнопок корзины)
    return render_template('index.html', products=products, lang=lang)

@app.route('/catalog')
def catalog():
    lang = session.get('lang', 'ru')
    # Показываем товары категории walls (простая фильтрация)
    filtered = [p for p in products if p.get('category') == 'walls']
    return render_template('catalog.html', products=filtered, lang=lang)

@app.route('/product/<int:product_id>')
def product(product_id):
    lang = session.get('lang', 'ru')
    item = next((p for p in products if p['id'] == product_id), None)
    if not item:
        return redirect(url_for('catalog'))
    return render_template('product.html', product=item, lang=lang)
# API добавления в корзину (используется js)
@app.route('/api/add_to_cart/<int:product_id>', methods=['POST'])
def api_add_to_cart(product_id):
    cart = session.get('cart', {})
    cart[str(product_id)] = cart.get(str(product_id), 0) + 1
    session['cart'] = cart
    p = next((x for x in products if x['id']==product_id), None)
    return jsonify(success=True, product=p, cart_total_items=sum(cart.values()))
if __name__ == '__main__':
    # локальный запуск
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)), debug=True)
