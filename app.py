# app.py
import os
from flask import Flask, render_template, request, session, redirect, url_for

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "wallcraft_secret_key")

# ====== Пример товаров ======
# Заменяй этот список на свой — используй относительный путь в static, например "images/IMG_0856.PNG"
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
        "description_ru": "Эффектные декоративные жидкие обои",
        "description_lv": "Dekoratīvas šķidras tapetes",
        "price": 30.00,
        "image": "images/IMG_0856.PNG"
    }
]

# ====== Установка языка в сессии ======
@app.before_request
def set_lang():
    session['lang'] = request.args.get('lang') or session.get('lang') or 'ru'

# ====== Маршруты ======
@app.route('/')
def index():
    lang = session.get('lang', 'ru')
    # На главной — показываем только фото и название (без кнопок корзины)
    return render_template('index.html', products=products, lang=lang)

@app.route('/catalog')
def catalog():
    lang = session.get('lang', 'ru')
    # Фильтрация: показываем только категорию walls (если нужно)
    filtered = [p for p in products if p.get('category') == 'walls']
    return render_template('catalog.html', products=filtered, lang=lang)

@app.route('/product/<int:product_id>')
def product(product_id):
    lang = session.get('lang', 'ru')
    product_item = next((p for p in products if p['id'] == product_id), None)
    if not product_item:
        return redirect(url_for('catalog'))
    return render_template('product.html', product=product_item, lang=lang)

# Запуск локально
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)), debug=True)
