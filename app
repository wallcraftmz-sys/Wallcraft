from flask import Flask, render_template, request, session
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import threading
import os

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

# ------------------- Маршруты -------------------

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

# ------------------- Асинхронная отправка письма -------------------

def send_email(name, contact):
    sender_email = os.environ.get("WALLCRAFT_EMAIL")
    receiver_email = os.environ.get("WALLCRAFT_EMAIL")
    app_password = os.environ.get("WALLCRAFT_APP_PASSWORD")

    if not sender_email or not app_password:
        print("Переменные окружения для почты не настроены!")
        return

    subject = "Новая заявка с сайта"
    body = f"Новая заявка:\nИмя: {name}\nКонтакт: {contact}"

    message = MIMEMultipart()
    message["From"] = sender_email
    message["To"] = receiver_email
    message["Subject"] = subject
    message.attach(MIMEText(body, "plain"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(sender_email, app_password)
            server.sendmail(sender_email, receiver_email, message.as_string())
        print("Письмо успешно отправлено!")
    except Exception as e:
        print("Ошибка при отправке письма:", e)

# ------------------- Форма заказа -------------------

@app.route("/order", methods=["GET", "POST"])
def order():
    if request.method == "POST":
        name = request.form.get("name")
        contact = request.form.get("contact")

        print("Новая заявка:")
        print("Имя:", name)
        print("Контакт:", contact)

        # Отправка письма в отдельном потоке
        threading.Thread(target=send_email, args=(name, contact)).start()

        return render_template("order.html", success=True, lang=session.get('lang'))

    return render_template("order.html", lang=session.get('lang'))

# ------------------- Запуск -------------------

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))  # Render даёт порт через переменную PORT
    app.run(host="0.0.0.0", port=port, debug=True)
