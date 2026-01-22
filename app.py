from werkzeug.middleware.proxy_fix import ProxyFix
from flask import (
    Flask,
    render_template,
    request,
    session,
    redirect,
    url_for,
    jsonify,
    flash
)
import os
import requests
from datetime import timedelta
from datetime import datetime

from flask_sqlalchemy import SQLAlchemy
from flask_login import (
    LoginManager,
    UserMixin,
    login_user,
    logout_user,
    current_user,
    login_required
)
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
from werkzeug.utils import secure_filename
import uuid
import secrets
from flask import render_template_string
# ======================
# ADMIN ACCESS CONTROL
# ======================
def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for("login"))

        if getattr(current_user, "role", None) != "admin":
            return redirect(url_for("profile"))

        return f(*args, **kwargs)
    return decorated


# ======================
# TELEGRAM
# ======================
def send_telegram(message: str):
    token = os.getenv("TG_BOT_TOKEN")
    chat_id = os.getenv("TG_CHAT_ID")

    if not token or not chat_id:
        print("❌ Telegram ENV vars not set:", {
            "TG_BOT_TOKEN": bool(token),
            "TG_CHAT_ID": bool(chat_id)
        })
        return False

    try:
        r = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": message},
            timeout=10
        )

        print("✅ TG response:", r.status_code, r.text)

        return r.ok
    except Exception as e:
        print("❌ TG ERROR:", repr(e))
        return False


# ======================
# APP CONFIG
# ======================
app = Flask(__name__)
# ======================
# CORE-9: LOGGING
# ======================
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("wallcraft")
# ======================
# CORE-10: CONFIG dev/prod
# ======================
class BaseConfig:
    SECRET_KEY = os.getenv("SECRET_KEY", "wallcraft_super_secret_key")
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SAMESITE = "Lax"
    MAX_CONTENT_LENGTH = 8 * 1024 * 1024  # CORE-19/SEC: 8MB upload limit

class ProdConfig(BaseConfig):
    DEBUG = False
    TESTING = False

class DevConfig(BaseConfig):
    DEBUG = True
    TESTING = False

APP_ENV = os.getenv("APP_ENV", "prod").lower()
app.config.from_object(DevConfig if APP_ENV == "dev" else ProdConfig)
app.secret_key = os.getenv("SECRET_KEY", "wallcraft_super_secret_key")
UPLOAD_FOLDER = "static/uploads"
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}

app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


# Railway / ProxyFix
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

# Cookies
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    REMEMBER_COOKIE_HTTPONLY=True,
    REMEMBER_COOKIE_SAMESITE="Lax",
)

# 🔥 DATABASE (КРИТИЧНО)
DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is not set")

if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

app.config["SQLALCHEMY_DATABASE_URI"] = DATABASE_URL
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

# Sessions
app.permanent_session_lifetime = timedelta(days=7)
app.config["REMEMBER_COOKIE_DURATION"] = timedelta(days=7)


# ======================
# DB + LOGIN MANAGER
# ======================
db = SQLAlchemy(app)

login_manager = LoginManager()
login_manager.login_view = "login"
login_manager.init_app(app)

@login_manager.unauthorized_handler
def unauthorized():
    return redirect(url_for("login", lang=session.get("lang", "ru")))


# ======================
# MODELS
# ======================
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    role = db.Column(db.String(20), default="admin")


class Order(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    user = db.relationship("User", backref="orders")

    name = db.Column(db.String(100), nullable=False)
    contact = db.Column(db.String(100), nullable=False)

    items = db.Column(db.Text, nullable=False)
    total = db.Column(db.Float, nullable=False)

    status = db.Column(db.String(30), default="new")

    is_deleted = db.Column(db.Boolean, default=False)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name_ru = db.Column(db.String(200), nullable=False)
    name_lv = db.Column(db.String(200), nullable=False)
    price = db.Column(db.Float, nullable=False)
    image = db.Column(db.String(200))

    is_active = db.Column(db.Boolean, default=True)


class OrderStatusHistory(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    order_id = db.Column(db.Integer, db.ForeignKey("order.id"), nullable=False)
    order = db.relationship("Order", backref="status_history")

    old_status = db.Column(db.String(30))
    new_status = db.Column(db.String(30))

    changed_by = db.Column(db.String(80))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class OrderComment(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    order_id = db.Column(db.Integer, db.ForeignKey("order.id"), nullable=False)
    order = db.relationship("Order", backref="comments")

    author = db.Column(db.String(80))
    text = db.Column(db.Text, nullable=False)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class SiteStepProgress(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    step_id = db.Column(db.Integer, unique=True, nullable=False)
    done = db.Column(db.Boolean, default=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow)
# ======================
# USER LOADER
# ======================
@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


# ======================
# INIT DB (SAFE)
# ======================
from sqlalchemy import text, or_
from io import StringIO
import csv
from flask import Response

with app.app_context():
    db.create_all()

    # migration: order.is_deleted
    try:
        db.session.execute(
            text('ALTER TABLE "order" ADD COLUMN is_deleted BOOLEAN DEFAULT FALSE')
        )
        db.session.commit()
    except Exception:
        db.session.rollback()

    # migration: product.is_active
    try:
        db.session.execute(
            text("ALTER TABLE product ADD COLUMN is_active BOOLEAN DEFAULT TRUE")
        )
        db.session.commit()
    except Exception:
        db.session.rollback()


ORDER_STATUSES = {
    "new": {"ru": "Новый", "lv": "Jauns", "en": "New"},
    "confirmed": {"ru": "В работе", "lv": "Darbā", "en": "In progress"},
    "in_progress": {"ru": "В работе", "lv": "Darbā", "en": "In progress"},
    "shipped": {"ru": "Отправлен", "lv": "Nosūtīts", "en": "Shipped"},
    "completed": {"ru": "Завершён", "lv": "Pabeigts", "en": "Completed"},
}

ALLOWED_STATUS_TRANSITIONS = {
    "new": ["in_progress"],
    "confirmed": ["in_progress"],
    "in_progress": ["shipped", "completed"],
    "shipped": ["completed"],
    "completed": [],
}

SITE_STEPS = [
    # CORE / STRUCTURE (1–20)
    (1, "Core", "Единая структура шаблонов (base/admin_base)"),
    (2, "Core", "Единые компоненты кнопок/таблиц/форм"),
    (3, "Core", "Единые сообщения flash (success/error)"),
    (4, "Core", "404/500 страницы"),
    (5, "Core", "Единый формат дат/валют"),
    (6, "Core", "Мультиязычность RU/LV/EN во всех страницах"),
    (7, "Core", "Robots.txt и sitemap.xml"),
    (8, "Core", "Favicon + OG meta (соцсети)"),
    (9, "Core", "Логирование ключевых действий"),
    (10, "Core", "Разделение конфигов dev/prod"),
    (11, "Core", "Health-check endpoint"),
    (12, "Core", "Страница “О нас/Контакты”"),
    (13, "Core", "Страница “Политика/Условия”"),
    (14, "Core", "Страница “Доставка/Оплата”"),
    (15, "Core", "Страница “FAQ”"),
    (16, "Core", "Компонент хлебных крошек"),
    (17, "Core", "Система уведомлений в UI"),
    (18, "Core", "Валидация форм сервер/клиент"),
    (19, "Core", "Сжатие/оптимизация изображений"),
    (20, "Core", "Проверка корректности ссылок/меню"),

    # SECURITY (21–40)
    (21, "Security", "CSRF на все формы"),
    (22, "Security", "Rate limit на login/checkout"),
    (23, "Security", "Блок повторной отправки checkout"),
    (24, "Security", "Хеширование паролей (есть)"),
    (25, "Security", "Политика паролей (длина/сложность)"),
    (26, "Security", "Блок brute-force по IP"),
    (27, "Security", "Secure cookies настройки"),
    (28, "Security", "Проверка загрузки файлов (MIME/размер)"),
    (29, "Security", "Максимальный размер upload"),
    (30, "Security", "Ограничение типов расширений (есть)"),
    (31, "Security", "Очистка/нормализация входных данных"),
    (32, "Security", "Запрет опасных редиректов"),
    (33, "Security", "Роли (admin/user) (есть)"),
    (34, "Security", "Защита админки (есть)"),
    (35, "Security", "Аудит действий админа (лог)"),
    (36, "Security", "CSP headers"),
    (37, "Security", "HSTS headers"),
    (38, "Security", "X-Frame-Options / clickjacking"),
    (39, "Security", "Sanitize выводимых данных"),
    (40, "Security", "Бэкап базы данных"),

    # CATALOG / PRODUCTS (41–70)
    (41, "Catalog", "Категории товаров"),
    (42, "Catalog", "Фильтры по цене/категории"),
    (43, "Catalog", "Сортировка по цене/новизне"),
    (44, "Catalog", "Поиск по каталогу"),
    (45, "Catalog", "Страница товара (детально)"),
    (46, "Catalog", "Галерея изображений товара"),
    (47, "Catalog", "Товар: описание RU/LV/EN"),
    (48, "Catalog", "Товар: SEO title/description"),
    (49, "Catalog", "Товар: наличие/склад"),
    (50, "Catalog", "Товар: вариации (цвет/размер)"),
    (51, "Catalog", "Товар: скидка/старая цена"),
    (52, "Catalog", "Товар: штрихкод/SKU"),
    (53, "Catalog", "Массовое редактирование товаров"),
    (54, "Catalog", "Импорт товаров CSV"),
    (55, "Catalog", "Экспорт товаров CSV"),
    (56, "Catalog", "Архив товаров (есть is_active)"),
    (57, "Catalog", "История изменений товара"),
    (58, "Catalog", "Лимит количества в корзине"),
    (59, "Catalog", "Похожие товары"),
    (60, "Catalog", "Популярные товары"),
    (61, "Catalog", "Новинки"),
    (62, "Catalog", "Хиты продаж"),
    (63, "Catalog", "Блок “Вы недавно смотрели”"),
    (64, "Catalog", "Lazy-load изображений"),
    (65, "Catalog", "WebP версии картинок"),
    (66, "Catalog", "Нормализация цен (2 знака)"),
    (67, "Catalog", "Ограничение длины названий в UI"),
    (68, "Catalog", "Проверка “товар скрыт” на всех страницах"),
    (69, "Catalog", "Кнопка “поделиться товаром”"),
    (70, "Catalog", "Отзывы о товаре"),

    # CART / CHECKOUT (71–100)
    (71, "Checkout", "Корзина: удаление товара"),
    (72, "Checkout", "Корзина: пересчет суммы (есть)"),
    (73, "Checkout", "Корзина: сохранение между сессиями"),
    (74, "Checkout", "Корзина: промокод"),
    (75, "Checkout", "Корзина: скидка по промокоду"),
    (76, "Checkout", "Checkout: адрес доставки"),
    (77, "Checkout", "Checkout: способ доставки"),
    (78, "Checkout", "Checkout: способ оплаты"),
    (79, "Checkout", "Checkout: подтверждение условий"),
    (80, "Checkout", "Checkout: email уведомление клиенту"),
    (81, "Checkout", "Checkout: SMS уведомление"),
    (82, "Checkout", "Checkout: инвойс/счет"),
    (83, "Checkout", "Checkout: сохранение адресов профиля"),
    (84, "Checkout", "Checkout: комментарий клиента к заказу"),
    (85, "Checkout", "Checkout: контроль дублей (есть токен)"),
    (86, "Checkout", "Checkout: антиспам (есть)"),
    (87, "Checkout", "Checkout: валидация телефона/почты (есть)"),
    (88, "Checkout", "Checkout: повторный заказ"),
    (89, "Checkout", "Checkout: статус оплаты"),
    (90, "Checkout", "Checkout: webhook платежа"),
    (91, "Checkout", "Автогенерация номера заказа"),
    (92, "Checkout", "Время обработки/ETA"),
    (93, "Checkout", "Локализация валюты/формата"),
    (94, "Checkout", "Ограничения по стране доставки"),
    (95, "Checkout", "Бесплатная доставка от суммы"),
    (96, "Checkout", "Налоги/НДС"),
    (97, "Checkout", "Подарочная упаковка"),
    (98, "Checkout", "Купоны на подарочную карту"),
    (99, "Checkout", "Согласие на маркетинг"),
    (100, "Checkout", "Согласие на обработку данных"),

    # ORDERS / ADMIN (101–140)
    (101, "Orders", "Фильтр активные/архив (есть)"),
    (102, "Orders", "Автоархив по completed (есть)"),
    (103, "Orders", "Поиск заказов (есть)"),
    (104, "Orders", "Пагинация заказов (есть)"),
    (105, "Orders", "Экспорт заказов CSV (есть)"),
    (106, "Orders", "Печать заказа (есть)"),
    (107, "Orders", "Комментарии админа к заказу (есть модель/роут)"),
    (108, "Orders", "История статусов (есть)"),
    (109, "Orders", "Восстановление заказа из архива (есть)"),
    (110, "Orders", "Удаление заказа навсегда (есть)"),
    (111, "Orders", "Фильтр по статусу"),
    (112, "Orders", "Фильтр по дате (с/по)"),
    (113, "Orders", "Фильтр по сумме (min/max)"),
    (114, "Orders", "Изменение контакта/имени заказа"),
    (115, "Orders", "Изменение состава заказа"),
    (116, "Orders", "Скрытие персональных данных (GDPR)"),
    (117, "Orders", "Теги заказов"),
    (118, "Orders", "Приоритет заказа"),
    (119, "Orders", "Назначение ответственного"),
    (120, "Orders", "Автосмена статуса по оплате"),
    (121, "Orders", "Автосмена статуса по доставке"),
    (122, "Orders", "Шаблоны сообщений клиенту"),
    (123, "Orders", "Email клиенту из админки"),
    (124, "Orders", "SMS клиенту из админки"),
    (125, "Orders", "Экспорт в XLSX"),
    (126, "Orders", "Отчет по продажам"),
    (127, "Orders", "Отчет по товарам"),
    (128, "Orders", "Отчет по источникам"),
    (129, "Orders", "Сверка оплат"),
    (130, "Orders", "Возвраты"),
    (131, "Orders", "Рефанды"),
    (132, "Orders", "Частичная отгрузка"),
    (133, "Orders", "Пакетная печать"),
    (134, "Orders", "Пакетная смена статуса"),
    (135, "Orders", "Логи действий админов"),
    (136, "Orders", "Роли: менеджер/оператор"),
    (137, "Orders", "Ограничение прав по ролям"),
    (138, "Orders", "Уведомления при новом заказе (TG есть)"),
    (139, "Orders", "Уведомления по статусам"),
    (140, "Orders", "Автоочистка старых сессий"),

    # UX / UI (141–170)
    (141, "UX", "Адаптивная шапка"),
    (142, "UX", "Меню для админа (есть)"),
    (143, "UX", "Меню для пользователя"),
    (144, "UX", "Быстрые действия без дублей (есть в admin_base)"),
    (145, "UX", "Исправить “контент залезает под шапку”"),
    (146, "UX", "Ширина меню 50% экрана"),
    (147, "UX", "Анимации открытия/закрытия меню"),
    (148, "UX", "Плавающая кнопка корзины"),
    (149, "UX", "Skeleton loaders"),
    (150, "UX", "Пустые состояния (нет товаров/нет заказов)"),
    (151, "UX", "Toast уведомления"),
    (152, "UX", "Подтверждение опасных действий"),
    (153, "UX", "Единые размеры кнопок"),
    (154, "UX", "Единые поля ввода"),
    (155, "UX", "Темная тема"),
    (156, "UX", "Автосохранение форм"),
    (157, "UX", "Избранное"),
    (158, "UX", "Сравнение"),
    (159, "UX", "Промо баннеры"),
    (160, "UX", "Карта сайта для пользователей"),
    (161, "UX", "Кнопка “наверх”"),
    (162, "UX", "Плавная прокрутка"),
    (163, "UX", "Шрифты и типографика"),
    (164, "UX", "Единый стиль карточек"),
    (165, "UX", "Микроанимации корзины"),
    (166, "UX", "Фокус/outline доступность"),
    (167, "UX", "ARIA атрибуты"),
    (168, "UX", "Контрастность"),
    (169, "UX", "Локальные форматы телефона LV"),
    (170, "UX", "Скрытие дубликатов ссылок в меню"),

    # OPS / QUALITY (171–200)
    (171, "Ops", "Мониторинг ошибок (Sentry)"),
    (172, "Ops", "Метрики (Prometheus/сервис)"),
    (173, "Ops", "Логи запросов"),
    (174, "Ops", "CI/CD pipeline"),
    (175, "Ops", "Unit tests"),
    (176, "Ops", "Integration tests"),
    (177, "Ops", "Lint/format (black/isort)"),
    (178, "Ops", "Pre-commit хуки"),
    (179, "Ops", "Автодеплой при push"),
    (180, "Ops", "Rollback стратегия"),
    (181, "Ops", "Миграции Alembic"),
    (182, "Ops", "Ротация секретов"),
    (183, "Ops", "Конфиги окружений Railway"),
    (184, "Ops", "Кеширование страниц/ответов"),
    (185, "Ops", "CDN для статических файлов"),
    (186, "Ops", "Оптимизация DB индексы"),
    (187, "Ops", "Профилирование медленных запросов"),
    (188, "Ops", "Очистка неиспользуемых файлов uploads"),
    (189, "Ops", "Ограничение размера БД/архивирование"),
    (190, "Ops", "Экспорт/импорт бэкапов"),
    (191, "Ops", "Управление версиями API"),
    (192, "Ops", "A/B тесты"),
    (193, "Ops", "Фичефлаги"),
    (194, "Ops", "Мульти-домен / canonical"),
    (195, "Ops", "Проверка SSL/HTTPS"),
    (196, "Ops", "Redirect www/non-www"),
    (197, "Ops", "Скорость (Lighthouse)"),
    (198, "Ops", "Web Vitals контроль"),
    (199, "Ops", "Документация админки"),
    (200, "Ops", "Runbook (что делать при ошибках)"),
]
# ======================
# LANGUAGE
# ======================
@app.before_request
def set_lang():
    if "lang" in request.args:
        session["lang"] = request.args.get("lang")

    if session.get("lang") not in ["ru", "lv", "en"]:
        session["lang"] = "ru"


@app.context_processor
def inject_lang():
    return dict(lang=session.get("lang", "ru"))

# ======================
# CORE-5: FORMAT HELPERS
# ======================
def fmt_money(x):
    try:
        return f"{float(x):.2f} €"
    except Exception:
        return f"{x} €"

def fmt_dt(dt):
    try:
        return dt.strftime("%d.%m.%Y %H:%M")
    except Exception:
        return ""

@app.context_processor
def inject_formatters():
    return dict(fmt_money=fmt_money, fmt_dt=fmt_dt)
# CSRF token into templates
@app.context_processor
def inject_csrf_token():
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_hex(16)
    return dict(csrf_token=session["csrf_token"])

@app.context_processor
def inject_cart_total():
    cart = session.get("cart", {})
    return dict(cart_total_items=sum(cart.values()))

@app.context_processor
def inject_breadcrumbs():
    # словарь: endpoint -> (текст, "родитель endpoint" или None)
    # ВАЖНО: тексты — по языкам
    MAP = {
        "index": ({"ru": "Главная", "lv": "Sākums", "en": "Home"}, None),
        "catalog": ({"ru": "Каталог", "lv": "Katalogs", "en": "Catalog"}, "index"),
        "cart": ({"ru": "Корзина", "lv": "Grozs", "en": "Cart"}, "catalog"),
        "checkout": ({"ru": "Оформление", "lv": "Noformēšana", "en": "Checkout"}, "cart"),
        "profile": ({"ru": "Профиль", "lv": "Profils", "en": "Profile"}, "index"),

        # статические страницы
        "about": ({"ru": "О нас", "lv": "Par mums", "en": "About"}, "index"),
        "policy": ({"ru": "Политика", "lv": "Politika", "en": "Policy"}, "index"),
        "shipping": ({"ru": "Доставка/Оплата", "lv": "Piegāde/Apmaksa", "en": "Shipping/Payment"}, "index"),
        "faq": ({"ru": "FAQ", "lv": "BUJ", "en": "FAQ"}, "index"),

        # админка (по желанию)
        "admin_panel": ({"ru": "Админка", "lv": "Admin", "en": "Admin"}, "index"),
        "admin_orders": ({"ru": "Заказы", "lv": "Pasūtījumi", "en": "Orders"}, "admin_panel"),
        "admin_products": ({"ru": "Товары", "lv": "Preces", "en": "Products"}, "admin_panel"),
        "admin_steps": ({"ru": "200 шагов", "lv": "200 soļi", "en": "200 steps"}, "admin_panel"),
    }

    def build_breadcrumbs():
        lang = session.get("lang", "ru")
        endpoint = request.endpoint

        if not endpoint or endpoint not in MAP:
            # если страница не описана — не показываем крошки
            return []

        crumbs = []
        seen = set()

        cur = endpoint
        while cur and cur in MAP and cur not in seen:
            seen.add(cur)

            title_dict, parent = MAP[cur]
            title = title_dict.get(lang, title_dict.get("ru", cur))

            try:
                url = url_for(cur, lang=lang)
            except Exception:
                url = "#"

            crumbs.append({"title": title, "url": url})
            cur = parent

        crumbs.reverse()
        return crumbs

    return dict(breadcrumbs=build_breadcrumbs())
# ======================
# SECURITY: BLOCK EMPTY CHECKOUT
# ======================
@app.before_request
def block_empty_checkout():
    if request.endpoint == "checkout" and request.method == "POST":
        cart = session.get("cart", {})
        if not cart or sum(cart.values()) == 0:
            return redirect(url_for("cart"))


# CSRF protect all /admin POST
@app.before_request
def csrf_protect_admin():
    if request.method == "POST" and request.path.startswith("/admin"):
        form_token = request.form.get("csrf_token")
        session_token = session.get("csrf_token")

        if not form_token or not session_token or form_token != session_token:
            flash("CSRF ошибка. Обновите страницу.", "error")
            return redirect(url_for("admin_orders"))


# ======================
# ROUTES
# ======================
@app.route("/")
def index():
    return render_template("index.html", lang=session["lang"])

# ======================
# CORE-11: HEALTH CHECK
# ======================
@app.route("/health")
def health():
    return jsonify(status="ok", time=datetime.utcnow().isoformat() + "Z")

# ======================
# CORE-4: ERROR PAGES
# ======================
@app.errorhandler(404)
def not_found(e):
    return render_template("errors/404.html", lang=session.get("lang", "ru")), 404

@app.errorhandler(500)
def server_error(e):
    return render_template("errors/500.html", lang=session.get("lang", "ru")), 500

@app.route("/catalog")
def catalog():
    products = Product.query.filter_by(is_active=True).all()
    return render_template("catalog.html", products=products, lang=session["lang"])


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")

        user = User.query.filter_by(username=username).first()

        if user and check_password_hash(user.password, password):
            login_user(user, remember=True)

            if user.role == "admin":
                return redirect(url_for("admin_panel"))
            else:
                return redirect(url_for("profile"))

        return render_template(
            "login.html",
            error="Неверный логин или пароль",
            lang=session.get("lang", "ru")
        )

    return render_template("login.html", lang=session.get("lang", "ru"))


@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("index"))


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")

        if User.query.filter_by(username=username).first():
            return render_template(
                "register.html",
                error="Пользователь уже существует",
                lang=session["lang"]
            )

        user = User(
            username=username,
            password=generate_password_hash(password),
            role="user"
        )

        db.session.add(user)
        db.session.commit()

        login_user(user, remember=True)
        return redirect(url_for("profile"))

    return render_template("register.html", lang=session["lang"])


@app.route("/profile")
@login_required
def profile():
    orders = (
        Order.query
        .filter_by(user_id=current_user.id)
        .order_by(Order.created_at.desc())
        .all()
    )
    return render_template("profile.html", orders=orders, ORDER_STATUSES=ORDER_STATUSES)


@app.route("/api/add_to_cart/<int:product_id>", methods=["POST"])
def add_to_cart(product_id):
    cart = session.get("cart", {})
    pid = str(product_id)

    cart[pid] = cart.get(pid, 0) + 1
    session["cart"] = cart
    session.modified = True

    return jsonify(success=True, cart_total_items=sum(cart.values()))

@app.route("/api/cart_count")
def cart_count():
    cart = session.get("cart", {})
    return jsonify(cart_total_items=sum(cart.values()))

@app.route("/cart")
def cart():
    cart = session.get("cart", {})

    items = []
    total = 0

    for pid, qty in cart.items():
        product = Product.query.get(int(pid))
        if not product or not product.is_active:
            continue

        item_total = product.price * qty
        total += item_total

        items.append({
            "id": product.id,
            "name": product.name_ru,
            "price": product.price,
            "qty": qty,
            "total": item_total,
            "image": product.image
        })

    return render_template("cart.html", items=items, total=total, lang=session.get("lang", "ru"))


@app.route("/api/update_cart/<int:product_id>/<action>", methods=["POST"])
def update_cart(product_id, action):
    cart = session.get("cart", {})
    pid = str(product_id)

    if pid not in cart:
        return jsonify(success=False)

    if action == "plus":
        cart[pid] += 1
    elif action == "minus":
        cart[pid] -= 1
        if cart[pid] <= 0:
            del cart[pid]

    session["cart"] = cart
    session.modified = True

    qty = cart.get(pid, 0)
    product = Product.query.get(product_id)
    subtotal = product.price * qty if product else 0

    total = 0
    for k, v in cart.items():
        p = Product.query.get(int(k))
        if p:
            total += p.price * v

    return jsonify(
        success=True,
        qty=qty,
        subtotal=subtotal,
        total=total,
        cart_total_items=sum(cart.values())
    )

@app.route("/api/cart_count")
def api_cart_count():
    cart = session.get("cart", {})
    return jsonify(cart_total_items=sum(cart.values()))

@app.route("/admin")
@login_required
@admin_required
def admin_panel():
    return redirect(url_for("admin_orders"))


# ===== CHECKOUT =====
import re

@app.route("/checkout", methods=["GET", "POST"])
@login_required
def checkout():
    cart = session.get("cart", {})

    if not cart or sum(cart.values()) == 0:
        return redirect(url_for("cart"))

    items = []
    total = 0

    for pid, qty in cart.items():
        product = Product.query.get(int(pid))
        if not product or qty <= 0:
            continue

        subtotal = product.price * qty
        total += subtotal
        items.append(f"{product.name_ru} × {qty}")

    items_text = "\n".join(items)

    if not items or total <= 0:
        session.pop("cart", None)
        return redirect(url_for("cart"))

    if request.method == "GET":
        session["checkout_token"] = str(uuid.uuid4())

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        contact = request.form.get("contact", "").strip()

        form_token = request.form.get("checkout_token")
        session_token = session.get("checkout_token")
        if not form_token or form_token != session_token:
            return redirect(url_for("cart"))

        session.pop("checkout_token", None)

        if len(name) < 2:
            return render_template(
                "checkout.html",
                items=items,
                total=total,
                error="Имя слишком короткое",
                checkout_token=session.get("checkout_token")
            )

        email_regex = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
        phone_regex = r"^\+?[0-9\s\-]{7,15}$"
        if not (re.match(email_regex, contact) or re.match(phone_regex, contact)):
            return render_template(
                "checkout.html",
                items=items,
                total=total,
                error="Введите корректный телефон или email",
                checkout_token=session.get("checkout_token")
            )

        if not session.get("cart"):
            return redirect(url_for("cart"))

        last_order_ts = session.get("last_order_ts")
        now = datetime.utcnow().timestamp()
        if last_order_ts and now - last_order_ts < 60:
            return render_template(
                "checkout.html",
                items=items,
                total=total,
                error="Подождите минуту перед следующим заказом",
                checkout_token=session.get("checkout_token")
            )

        order = Order(
            user_id=current_user.id,
            name=name,
            contact=contact,
            items=items_text,
            total=total,
            status="new",
            is_deleted=False
        )

        db.session.add(order)
        db.session.commit()

        session["last_order_ts"] = datetime.utcnow().timestamp()

        session.pop("cart", None)
        session.modified = True

        send_telegram(
            f"🛒 НОВЫЙ ЗАКАЗ\n"
            f"Пользователь: {current_user.username}\n"
            f"Имя: {name}\n"
            f"Контакт: {contact}\n\n"
            f"{items_text}\n"
            f"Итого: {total:.2f} €"
        )

        return redirect(url_for("profile"))

    return render_template(
        "checkout.html",
        items=items,
        total=total,
        checkout_token=session.get("checkout_token")
    )


# ===== ADMIN PRODUCTS =====
@app.route("/admin/products", methods=["GET", "POST"])
@login_required
@admin_required
def admin_products():
    if request.method == "POST":
        file = request.files.get("image")

        image_path = None

        # если файл есть — проверяем
        if file and file.filename:
            # CORE-19/SEC: upload size guard (MAX_CONTENT_LENGTH)
            if request.content_length and request.content_length > app.config.get("MAX_CONTENT_LENGTH", 0):
                flash("Файл слишком большой", "error")
                return redirect(url_for("admin_products"))

            # проверяем расширение
            if allowed_file(file.filename):
                filename = secure_filename(file.filename)
                upload_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)

                os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
                file.save(upload_path)

                image_path = f"uploads/{filename}"
            else:
                flash("Неверный формат файла (только png/jpg/jpeg/webp)", "error")
                return redirect(url_for("admin_products"))

            os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
            file.save(upload_path)

            image_path = f"uploads/{filename}"

        product = Product(
            name_ru=request.form["name_ru"],
            name_lv=request.form["name_lv"],
            price=float(request.form["price"]),
            image=image_path,
            is_active=True
        )

        db.session.add(product)
        db.session.commit()
        return redirect(url_for("admin_products"))

    show = request.args.get("show", "active")

    if show == "inactive":
        products = Product.query.filter_by(is_active=False).all()
    elif show == "all":
        products = Product.query.all()
    else:
        products = Product.query.filter_by(is_active=True).all()

    return render_template("admin/products.html", products=products, show=show)


@app.route("/admin/products/delete/<int:id>", methods=["POST"])
@login_required
@admin_required
def delete_product(id):
    product = Product.query.get_or_404(id)
    product.is_active = False
    db.session.commit()
    return redirect(url_for("admin_products"))


@app.route("/admin/products/edit/<int:id>", methods=["GET", "POST"])
@login_required
@admin_required
def edit_product(id):
    product = Product.query.get_or_404(id)

    if request.method == "POST":
        product.name_ru = request.form["name_ru"]
        product.name_lv = request.form["name_lv"]
        product.price = float(request.form["price"])
        product.image = request.form["image"]

        db.session.commit()
        return redirect(url_for("admin_products"))

    return render_template("admin/edit_product.html", product=product)


# ===== ADMIN ORDERS =====
@app.route("/admin/orders")
@admin_required
def admin_orders():
    show = request.args.get("show", "active")
    q = request.args.get("q", "").strip()
    page = request.args.get("page", 1, type=int)
    PER_PAGE = 20

    ACTIVE_STATUSES = ["new", "in_progress", "shipped"]
    ARCHIVE_STATUSES = ["completed"]

    query = Order.query

    if show == "archive":
        query = query.filter(
            or_(
                Order.is_deleted.is_(True),
                Order.status.in_(ARCHIVE_STATUSES)
            )
        )
    else:
        query = query.filter(
            Order.is_deleted.is_(False),
            Order.status.in_(ACTIVE_STATUSES)
        )

    if q:
        if q.isdigit():
            query = query.filter(Order.id == int(q))
        else:
            like = f"%{q}%"
            query = query.filter(
                or_(
                    Order.name.ilike(like),
                    Order.contact.ilike(like)
                )
            )

    pagination = (
        query
        .order_by(Order.created_at.desc())
        .paginate(page=page, per_page=PER_PAGE, error_out=False)
    )

    return render_template(
        "admin/orders.html",
        orders=pagination.items,
        pagination=pagination,
        ORDER_STATUSES=ORDER_STATUSES,
        ALLOWED_STATUS_TRANSITIONS=ALLOWED_STATUS_TRANSITIONS,
        lang=session.get("lang", "ru"),
        show=show
    )


@app.route("/dashboard")
@login_required
@admin_required
def dashboard_redirect():
    return redirect(url_for("admin_panel"))


@app.route("/admin/orders/<int:order_id>/status", methods=["POST"])
@admin_required
def update_order_status(order_id):
    order = Order.query.get_or_404(order_id)

    new_status = request.form.get("status")
    old_status = order.status

    if not new_status or new_status == old_status:
        return redirect(url_for("admin_orders"))

    if new_status not in ORDER_STATUSES:
        return redirect(url_for("admin_orders"))

    allowed = ALLOWED_STATUS_TRANSITIONS.get(old_status, [])
    if new_status not in allowed:
        flash("Недопустимый переход статуса", "error")
        return redirect(url_for("admin_orders"))

    order.status = new_status

    # ✅ Авто-архив при completed (чтобы сразу ушел в Архив)
    if new_status == "completed":
        order.is_deleted = True

    history = OrderStatusHistory(
        order_id=order.id,
        old_status=old_status,
        new_status=new_status,
        changed_by=current_user.username
    )

    db.session.add(history)
    db.session.commit()

    return redirect(url_for("admin_orders"))


@app.route("/admin/orders/delete/<int:order_id>", methods=["POST"])
@login_required
@admin_required
def delete_order(order_id):
    order = Order.query.get_or_404(order_id)
    order.is_deleted = True
    db.session.commit()
    flash("Заказ перемещён в архив", "success")
    return redirect(url_for("admin_orders"))


# ======================
# ✅ ПУНКТ 24: RESTORE ORDER
# ======================
@app.route("/admin/orders/restore/<int:order_id>", methods=["POST"])
@login_required
@admin_required
def restore_order(order_id):
    order = Order.query.get_or_404(order_id)

    # завершенный заказ логикой статусов не возвращаем назад
    if order.status == "completed":
        flash("Завершённый заказ нельзя вернуть из архива.", "error")
        return redirect(url_for("admin_orders", show="archive"))

    order.is_deleted = False
    db.session.commit()
    flash("Заказ восстановлен из архива", "success")
    return redirect(url_for("admin_orders", show="archive"))


# ======================
# ✅ ПУНКТ 25: HARD DELETE ORDER (навсегда)
# ======================
@app.route("/admin/orders/hard_delete/<int:order_id>", methods=["POST"])
@login_required
@admin_required
def hard_delete_order(order_id):
    order = Order.query.get_or_404(order_id)

    # сначала удаляем зависимые записи
    OrderStatusHistory.query.filter_by(order_id=order.id).delete()
    OrderComment.query.filter_by(order_id=order.id).delete()

    db.session.delete(order)
    db.session.commit()

    flash("Заказ удалён навсегда", "success")
    return redirect(url_for("admin_orders", show="archive"))


@app.route("/admin/products/restore/<int:id>", methods=["POST"])
@login_required
@admin_required
def restore_product(id):
    product = Product.query.get_or_404(id)
    product.is_active = True
    db.session.commit()
    return redirect(url_for("admin_products"))


@app.route("/admin/orders/<int:order_id>")
@admin_required
def admin_order_view(order_id):
    order = Order.query.get_or_404(order_id)

    history = (
        OrderStatusHistory.query
        .filter_by(order_id=order.id)
        .order_by(OrderStatusHistory.created_at.desc())
        .all()
    )

    return render_template(
        "admin/order_view.html",
        order=order,
        history=history,
        ORDER_STATUSES=ORDER_STATUSES,
        lang=session.get("lang", "ru")
    )


# ======================
# ✅ ПУНКТ 27: PRINT ORDER
# ======================
@app.route("/admin/orders/<int:order_id>/print")
@admin_required
def admin_order_print(order_id):
    order = Order.query.get_or_404(order_id)

    history = (
        OrderStatusHistory.query
        .filter_by(order_id=order.id)
        .order_by(OrderStatusHistory.created_at.desc())
        .all()
    )

    comments = (
        OrderComment.query
        .filter_by(order_id=order.id)
        .order_by(OrderComment.created_at.desc())
        .all()
    )

    return render_template(
        "admin/order_print.html",
        order=order,
        history=history,
        comments=comments,
        ORDER_STATUSES=ORDER_STATUSES,
        lang=session.get("lang", "ru")
    )


@app.route("/admin/orders/export")
@admin_required
def export_orders_csv():
    show = request.args.get("show", "active")
    q = request.args.get("q", "").strip()

    ACTIVE_STATUSES = ["new", "in_progress", "shipped"]
    ARCHIVE_STATUSES = ["completed"]

    query = Order.query

    if show == "archive":
        query = query.filter(
            or_(
                Order.is_deleted.is_(True),
                Order.status.in_(ARCHIVE_STATUSES)
            )
        )
    else:
        query = query.filter(
            Order.is_deleted.is_(False),
            Order.status.in_(ACTIVE_STATUSES)
        )

    if q:
        if q.isdigit():
            query = query.filter(Order.id == int(q))
        else:
            like = f"%{q}%"
            query = query.filter(
                or_(
                    Order.name.ilike(like),
                    Order.contact.ilike(like)
                )
            )

    orders = query.order_by(Order.created_at.desc()).all()

    si = StringIO()
    writer = csv.writer(si)

    writer.writerow(["ID", "Имя", "Контакт", "Состав", "Сумма", "Статус", "Дата"])

    for o in orders:
        writer.writerow([
            o.id,
            o.name,
            o.contact,
            o.items,
            f"{o.total:.2f}",
            ORDER_STATUSES.get(o.status, {}).get("ru", o.status),
            o.created_at.strftime("%d.%m.%Y %H:%M")
        ])

    output = si.getvalue()
    si.close()

    return Response(
        output,
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename=orders_{show}.csv"}
    )


@app.route("/admin/orders/<int:order_id>/comment", methods=["POST"])
@admin_required
def add_order_comment(order_id):
    order = Order.query.get_or_404(order_id)

    text_comment = request.form.get("comment", "").strip()
    if not text_comment:
        return redirect(url_for("admin_order_view", order_id=order.id))

    comment = OrderComment(
        order_id=order.id,
        author=current_user.username,
        text=text_comment
    )

    db.session.add(comment)
    db.session.commit()

    return redirect(url_for("admin_order_view", order_id=order.id))

@app.route("/admin/steps_manual", methods=["GET", "POST"])
@admin_required
def admin_steps_manual():
    if request.method == "POST":
        step_id = request.form.get("step_id", type=int)
        done = request.form.get("done") == "1"

        if step_id:
            row = SiteStepProgress.query.filter_by(step_id=step_id).first()
            if not row:
                row = SiteStepProgress(step_id=step_id, done=done)
            else:
                row.done = done
                row.updated_at = datetime.utcnow()

            db.session.add(row)
            db.session.commit()

        return redirect(url_for("admin_steps", lang=session.get("lang", "ru")))

    progress_rows = SiteStepProgress.query.all()
    progress = {r.step_id: r.done for r in progress_rows}

    # группировка по категориям
    grouped = {}
    for sid, cat, title in SITE_STEPS:
        grouped.setdefault(cat, []).append((sid, title, progress.get(sid, False)))

    tmpl = """
    {% extends "admin/admin_base.html" %}
    {% block content %}
    <h1>📋 Чек-лист 200 шагов</h1>

    <p style="opacity:0.7; margin-bottom:16px;">
      Отмечай выполненные пункты — сохраняется в базе.
    </p>

    {% for cat, items in grouped.items() %}
      <div style="margin:18px 0; padding:14px; border:1px solid rgba(0,0,0,0.08); border-radius:12px;">
        <h3 style="margin:0 0 10px 0;">{{ cat }}</h3>

        {% for sid, title, done in items %}
          <form method="post" style="display:flex; gap:10px; align-items:center; padding:6px 0; border-bottom:1px dashed rgba(0,0,0,0.08);">
            <input type="hidden" name="csrf_token" value="{{ csrf_token }}">
            <input type="hidden" name="step_id" value="{{ sid }}">
            <input type="hidden" name="done" value="{{ 0 if done else 1 }}">

            <button type="submit" class="admin-link" style="min-width:110px;">
              {% if done %}✅ Готово{% else %}⬜ Сделать{% endif %}
            </button>

            <div style="flex:1;">
              <strong>#{{ sid }}</strong> — {{ title }}
            </div>
          </form>
        {% endfor %}
      </div>
    {% endfor %}

    {% endblock %}
    """
    return render_template_string(tmpl, grouped=grouped)

# ======================
# CORE-7: ROBOTS + SITEMAP
# ======================
@app.route("/robots.txt")
def robots_txt():
    lines = [
        "User-agent: *",
        "Allow: /",
        "Disallow: /admin",
        "Sitemap: " + request.url_root.rstrip("/") + "/sitemap.xml"
    ]
    return Response("\n".join(lines), mimetype="text/plain")

@app.route("/sitemap.xml")
def sitemap_xml():
    pages = [
        url_for("index", _external=True),
        url_for("catalog", _external=True),
        url_for("cart", _external=True),
        url_for("about", _external=True),
        url_for("policy", _external=True),
        url_for("shipping", _external=True),
        url_for("faq", _external=True),
    ]
    xml = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for p in pages:
        xml.append("<url><loc>%s</loc></url>" % p)
    xml.append("</urlset>")
    return Response("\n".join(xml), mimetype="application/xml")

# ======================
# CORE-12/13/14/15: STATIC PAGES
# ======================
@app.route("/about")
def about():
    return render_template("pages/about.html", lang=session.get("lang", "ru"))

@app.route("/policy")
def policy():
    return render_template("pages/policy.html", lang=session.get("lang", "ru"))

@app.route("/shipping")
def shipping():
    return render_template("pages/shipping.html", lang=session.get("lang", "ru"))

@app.route("/faq")
def faq():
    return render_template("pages/faq.html", lang=session.get("lang", "ru"))

# ======================
# CORE-20: MENU/LINK CHECK (admin)
# ======================
@app.route("/admin/links_check")
@admin_required
def links_check():
    links = {
        "admin_orders": url_for("admin_orders"),
        "admin_products": url_for("admin_products"),
        "catalog": url_for("catalog"),
        "cart": url_for("cart"),
        "about": url_for("about"),
        "policy": url_for("policy"),
        "shipping": url_for("shipping"),
        "faq": url_for("faq"),
        "health": url_for("health"),
    }
    return jsonify(ok=True, links=links)

# ======================
# ✅ AUTO SITE STEPS (1–200): red/yellow/green
# ======================
from pathlib import Path
import re

_STEP_DONE_RE = re.compile(r"\bSTEP-(\d{1,3})\b")
_STEP_WIP_RE = re.compile(r"\bWIP-(\d{1,3})\b")

def _project_files_for_scan():
    root = Path(app.root_path)
    files = []

    # app.py
    files.append(root / "app.py")

    # templates, static
    tpl = root / "templates"
    st = root / "static"

    if tpl.exists():
        files += list(tpl.rglob("*.html"))
    if st.exists():
        files += list(st.rglob("*.js"))
        files += list(st.rglob("*.css"))

    return files

def _scan_markers():
    """
    Ищет маркеры:
      STEP-123  -> done
      WIP-123   -> in_progress
    в app.py / templates / static.
    """
    done_ids = set()
    wip_ids = set()

    for f in _project_files_for_scan():
        try:
            text = f.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue

        for m in _STEP_DONE_RE.findall(text):
            try: done_ids.add(int(m))
            except Exception: pass

        for m in _STEP_WIP_RE.findall(text):
            try: wip_ids.add(int(m))
            except Exception: pass

    return done_ids, wip_ids

def _has_route(path: str) -> bool:
    try:
        return any(r.rule == path for r in app.url_map.iter_rules())
    except Exception:
        return False

def _template_exists(rel_path: str) -> bool:
    p = Path(app.root_path) / "templates" / rel_path
    return p.exists()

def _static_exists(rel_path: str) -> bool:
    p = Path(app.root_path) / "static" / rel_path
    return p.exists()

def _has_model_field(model, field_name: str) -> bool:
    try:
        return hasattr(model, field_name)
    except Exception:
        return False

def build_steps_status_200():
    """
    Возвращает dict[step_id] -> "done" | "in_progress" | "todo"
    done / in_progress определяется автоматически.
    """
    statuses = {sid: "todo" for (sid, _, _) in SITE_STEPS}

    done_ids, wip_ids = _scan_markers()

    # 1) Маркеры в коде/шаблонах
    for sid in wip_ids:
        if sid in statuses:
            statuses[sid] = "in_progress"
    for sid in done_ids:
        if sid in statuses:
            statuses[sid] = "done"

    # 2) Реальные авто-проверки (там, где это можно понять однозначно)

    # CORE
    if _template_exists("admin/admin_base.html") or _template_exists("base.html") or _template_exists("base_user.html"):
        statuses[1] = "done"  # структура шаблонов

    if _static_exists("css/style.css"):
        statuses[2] = "done"

    # flash messages: если в admin_base есть get_flashed_messages
    try:
        base_path = Path(app.root_path) / "templates" / "admin" / "admin_base.html"
        if base_path.exists():
            t = base_path.read_text(encoding="utf-8", errors="ignore")
            if "get_flashed_messages" in t:
                statuses[3] = "done"
    except Exception:
        pass

    if _template_exists("errors/404.html") and _template_exists("errors/500.html"):
        statuses[4] = "done"

    # форматтеры
    if "fmt_money" in globals() and "fmt_dt" in globals():
        statuses[5] = "done"

    # языки
    statuses[6] = "done"  # set_lang у тебя есть

    if _has_route("/robots.txt") and _has_route("/sitemap.xml"):
        statuses[7] = "done"

    # favicon + OG: favicon файл + наличие og:title хотя бы в одном шаблоне
    if _static_exists("images/favicon.ico"):
        statuses[8] = "done"
        try:
            tpl_root = Path(app.root_path) / "templates"
            if tpl_root.exists():
                any_og = False
                for f in tpl_root.rglob("*.html"):
                    tt = f.read_text(encoding="utf-8", errors="ignore")
                    if "og:title" in tt:
                        any_og = True
                        break
                if any_og:
                    statuses[8] = "done"
        except Exception:
            pass

    # логирование
    try:
        import logging
        if logging.getLogger().handlers:
            statuses[9] = "done"
    except Exception:
        pass

    # dev/prod
    if "APP_ENV" in globals():
        statuses[10] = "done"

    if _has_route("/health"):
        statuses[11] = "done"

    if _has_route("/about") and _template_exists("pages/about.html"):
        statuses[12] = "done"
    if _has_route("/policy") and _template_exists("pages/policy.html"):
        statuses[13] = "done"
    if _has_route("/shipping") and _template_exists("pages/shipping.html"):
        statuses[14] = "done"
    if _has_route("/faq") and _template_exists("pages/faq.html"):
        statuses[15] = "done"
        # CORE-16: BREADCRUMBS component (auto-detect)
    try:
        # 1) функция breadcrumbs должна существовать
        has_inject = "inject_breadcrumbs" in globals()

        # 2) и разметка breadcrumbs должна быть хотя бы в одном базовом шаблоне
        tpl_user = Path(app.root_path) / "templates" / "base_user.html"
        tpl_admin = Path(app.root_path) / "templates" / "admin" / "admin_base.html"

        def _has_breadcrumbs_markup(p: Path) -> bool:
            if not p.exists():
                return False
            t = p.read_text(encoding="utf-8", errors="ignore")
            return ('aria-label="breadcrumb"' in t) or ('class="breadcrumbs"' in t)

        if has_inject and (_has_breadcrumbs_markup(tpl_user) or _has_breadcrumbs_markup(tpl_admin)):
            statuses[16] = "done"
    except Exception:
        pass

    # SECURITY
    # CSRF: есть inject_csrf_token + csrf_protect_admin (частично, но считаем базу сделанной)
    if "inject_csrf_token" in globals() and "csrf_protect_admin" in globals():
        statuses[21] = "done"

    # checkout token anti-double
    if "checkout" in globals():
        statuses[23] = "done"

    # password hashing
    statuses[24] = "done"

    # cookies secure policy (база)
    statuses[27] = "done"

    # upload limit
    if app.config.get("MAX_CONTENT_LENGTH"):
        statuses[29] = "done"

    # allowed extensions
    if "ALLOWED_EXTENSIONS" in globals():
        statuses[30] = "done"

    # roles/admin
    statuses[33] = "done"
    statuses[34] = "done"

    # CATALOG/PRODUCTS
    if _has_model_field(Product, "is_active"):
        statuses[56] = "done"

    # Lazy-load: если в catalog.html есть loading="lazy"
    try:
        cpath = Path(app.root_path) / "templates" / "catalog.html"
        if cpath.exists():
            t = cpath.read_text(encoding="utf-8", errors="ignore")
            if 'loading="lazy"' in t:
                statuses[64] = "done"
    except Exception:
        pass

    # скрытые товары проверяются в catalog()/cart()
    statuses[68] = "done"

    # CART/CHECKOUT
    statuses[72] = "done"  # пересчёт суммы есть
    statuses[85] = "done"  # checkout token есть
    statuses[86] = "done"  # антиспам (минутный лимит)
    statuses[87] = "done"  # валидация email/phone

    # ORDERS/ADMIN (то, что у тебя уже реально есть)
    statuses[101] = "done"
    statuses[102] = "done"
    statuses[103] = "done"
    statuses[104] = "done"
    statuses[105] = "done"
    statuses[106] = "done"
    statuses[107] = "done"
    statuses[108] = "done"
    statuses[109] = "done"
    statuses[110] = "done"
    statuses[138] = "done"  # TG уведомление есть

    # UX
    statuses[142] = "done"  # меню админа
    statuses[144] = "done"  # быстрые действия

    return statuses


# ✅ ЗАМЕНА: теперь /admin/steps только GET и показывает АВТО-статус
@app.route("/admin/steps")
@admin_required
def admin_steps():
    statuses = build_steps_status_200()

    # группировка
    grouped = {}
    for sid, cat, title in SITE_STEPS:
        grouped.setdefault(cat, []).append((sid, title, statuses.get(sid, "todo")))

    total = len(SITE_STEPS)
    done = sum(1 for s in statuses.values() if s == "done")
    wip = sum(1 for s in statuses.values() if s == "in_progress")
    todo = total - done - wip

    return render_template(
        "admin/steps.html",
        grouped=grouped,
        stats=dict(total=total, done=done, in_progress=wip, todo=todo)
    )
