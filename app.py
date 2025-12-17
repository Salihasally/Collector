import os
import secrets
import sqlite3
import smtplib
import ssl
from email.message import EmailMessage
from functools import wraps
from datetime import datetime, timedelta
import re

from flask import Flask, render_template, abort, request, redirect, url_for, flash, session, g
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename


BASE_DIR = os.path.abspath(os.path.dirname(__file__))
SELLER_OFFSET = 100000  # article_id virtuel = SELLER_OFFSET + post.id

app = Flask(
    __name__,
    static_folder=os.path.join(BASE_DIR, "static"),
    static_url_path="/static",
    template_folder=os.path.join(BASE_DIR, "templates")
)

# NOTE: en prod, remplace par une vraie secret key (env var)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-change-me")
app.config["DATABASE"] = os.path.join(BASE_DIR, "collectorshop.sqlite3")

# Environnement (production/development)
app.config["APP_ENV"] = os.environ.get("APP_ENV", "development")
# Admin email (vision admin)
app.config["ADMIN_EMAIL"] = (os.environ.get("ADMIN_EMAIL") or "salihalainceur4@gmail.com").strip().lower()

# 2FA toggle (par défaut désactivé si non défini)
_use_2fa_env = (os.environ.get("USE_2FA") or "0").strip().lower()
app.config["USE_2FA"] = _use_2fa_env in {"1", "true", "yes", "on"}

if app.config["APP_ENV"] == "production":
    # Cookies de session plus sûrs en prod
    app.config.update(
        SESSION_COOKIE_SECURE=True,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
    )

# Uploads images (vendeur)
app.config["UPLOAD_FOLDER"] = os.path.join(app.static_folder, "uploads")
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024  # 10 MB
os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
ALLOWED_IMAGE_EXT = {"png", "jpg", "jpeg", "webp"}

def get_db():
    db = getattr(g, "_db", None)
    if db is None:
        db = sqlite3.connect(app.config["DATABASE"])
        db.row_factory = sqlite3.Row
        g._db = db
    return db


@app.teardown_appcontext
def close_db(exception):
    db = getattr(g, "_db", None)
    if db is not None:
        db.close()


def migrate_users_table(db: sqlite3.Connection) -> None:
    """Ajoute des colonnes si la DB existait déjà (migration légère)."""
    existing = {row["name"] for row in db.execute("PRAGMA table_info(users)").fetchall()}

    if "first_name" not in existing:
        db.execute("ALTER TABLE users ADD COLUMN first_name TEXT")
    if "last_name" not in existing:
        db.execute("ALTER TABLE users ADD COLUMN last_name TEXT")
    if "role" not in existing:
        db.execute("ALTER TABLE users ADD COLUMN role TEXT")


def migrate_orders_table(db: sqlite3.Connection) -> None:
    existing = {row["name"] for row in db.execute("PRAGMA table_info(orders)").fetchall()}

    if "payment_status" not in existing:
        db.execute("ALTER TABLE orders ADD COLUMN payment_status TEXT")
    if "paid_at" not in existing:
        db.execute("ALTER TABLE orders ADD COLUMN paid_at TEXT")


def init_db():
    db = sqlite3.connect(app.config["DATABASE"])
    db.row_factory = sqlite3.Row
    try:
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                first_name TEXT,
                last_name TEXT,
                role TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            """
        )

        migrate_users_table(db)

        # Bootstrap admin via variable d'env (facultatif)
        admin_email = os.environ.get("ADMIN_EMAIL")
        if admin_email:
            db.execute("UPDATE users SET role = 'admin' WHERE lower(email) = lower(?)", (admin_email,))

        # OTP pour 2FA (connexion)
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS login_otps (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                code_hash TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                used_at TEXT,
                FOREIGN KEY(user_id) REFERENCES users(id)
            );
            """
        )

        # Favoris
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS favorites (
                user_id INTEGER NOT NULL,
                article_id INTEGER NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                PRIMARY KEY (user_id, article_id),
                FOREIGN KEY(user_id) REFERENCES users(id)
            );
            """
        )

        # Panier
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS cart_items (
                user_id INTEGER NOT NULL,
                article_id INTEGER NOT NULL,
                qty INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                PRIMARY KEY (user_id, article_id),
                FOREIGN KEY(user_id) REFERENCES users(id)
            );
            """
        )

        # Commandes
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                total_cents INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                payment_status TEXT,
                paid_at TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY(user_id) REFERENCES users(id)
            );
            """
        )

        migrate_orders_table(db)

        # Posts vendeurs (listings)
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS posts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                description TEXT,
                price_cents INTEGER NOT NULL,
                image_path TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY(user_id) REFERENCES users(id)
            );
            """
        )

        db.execute(
            """
            CREATE TABLE IF NOT EXISTS order_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER NOT NULL,
                article_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                price_cents INTEGER NOT NULL,
                qty INTEGER NOT NULL,
                FOREIGN KEY(order_id) REFERENCES orders(id)
            );
            """
        )

        # Messagerie simple
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                buyer_id INTEGER NOT NULL,
                seller_id INTEGER NOT NULL,
                post_id INTEGER,
                subject TEXT,
                last_message_at TEXT NOT NULL DEFAULT (datetime('now')),
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY(buyer_id) REFERENCES users(id),
                FOREIGN KEY(seller_id) REFERENCES users(id),
                FOREIGN KEY(post_id) REFERENCES posts(id)
            );
            """
        )
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conv_id INTEGER NOT NULL,
                sender_id INTEGER NOT NULL,
                body TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                read_at TEXT,
                FOREIGN KEY(conv_id) REFERENCES conversations(id),
                FOREIGN KEY(sender_id) REFERENCES users(id)
            );
            """
        )
        db.execute("CREATE INDEX IF NOT EXISTS idx_messages_conv ON messages(conv_id)")

        db.commit()
    finally:
        db.close()


def _safe_next_url(next_url: str | None) -> str | None:
    """Autorise uniquement les redirections internes (évite open redirect)."""
    if not next_url:
        return None
    nxt = (next_url or "").strip()
    # Autoriser uniquement un chemin interne
    if not nxt.startswith("/"):
        return None
    if nxt.startswith("//"):
        return None
    return nxt


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            flash("Connecte-toi pour continuer.", "error")
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)

    return wrapped


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            flash("Connecte-toi pour continuer.", "error")
            return redirect(url_for("login", next=request.path))
        if (session.get("user_email") or "").strip().lower() != app.config["ADMIN_EMAIL"]:
            flash("Accès réservé à l’admin.", "error")
            return redirect(url_for("catalogue"))
        return view(*args, **kwargs)

    return wrapped


def seller_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            flash("Connecte-toi pour continuer.", "error")
            return redirect(url_for("login", next=request.path))
        db = get_db()
        row = db.execute("SELECT role FROM users WHERE id = ?", (int(session["user_id"]),)).fetchone()
        if not row or row["role"] != "vendeur":
            flash("Accès vendeur requis. Demande à l’admin ou passe ton rôle en ‘vendeur’.", "error")
            return redirect(url_for("catalogue"))
        return view(*args, **kwargs)

    return wrapped


def get_favorite_ids(user_id: int) -> set[int]:
    db = get_db()
    rows = db.execute(
        "SELECT article_id FROM favorites WHERE user_id = ?", (user_id,)
    ).fetchall()
    return {int(r["article_id"]) for r in rows}


def get_cart_count(user_id: int) -> int:
    db = get_db()
    row = db.execute(
        "SELECT COALESCE(SUM(qty), 0) AS c FROM cart_items WHERE user_id = ?",
        (user_id,),
    ).fetchone()
    return int(row["c"] or 0)


@app.context_processor
def inject_nav_counts():
    uid = session.get("user_id")
    user_email = (session.get("user_email") or "").strip().lower()
    is_admin_email = user_email == app.config.get("ADMIN_EMAIL")
    if not uid:
        return {"cart_count": 0, "user_role": None, "is_admin": is_admin_email}
    db = get_db()
    row = db.execute("SELECT role FROM users WHERE id = ?", (int(uid),)).fetchone()
    role = row["role"] if row else None
    return {"cart_count": get_cart_count(int(uid)), "user_role": role, "is_admin": is_admin_email}


def generate_captcha() -> str:
    """Captcha simple (addition/soustraction) stocké en session."""
    a = secrets.randbelow(9) + 1
    b = secrets.randbelow(9) + 1
    op = "+" if secrets.randbelow(2) == 0 else "-"

    if op == "-" and b > a:
        a, b = b, a

    answer = a + b if op == "+" else a - b
    question = f"{a} {op} {b}"

    session["captcha_answer"] = str(answer)
    session["captcha_question"] = question
    return question


def create_login_otp(user_id: int) -> str:
    """Crée un code 2FA à 6 chiffres et le stocke hashé en BDD (valable 10 minutes)."""
    code = f"{secrets.randbelow(1_000_000):06d}"
    db = get_db()

    # Invalide les anciens codes non utilisés
    db.execute(
        "DELETE FROM login_otps WHERE user_id = ? AND used_at IS NULL", (user_id,)
    )

    db.execute(
        "INSERT INTO login_otps (user_id, code_hash, expires_at) VALUES (?, ?, datetime('now', '+10 minutes'))",
        (user_id, generate_password_hash(code)),
    )
    db.commit()

    return code


def verify_login_otp(user_id: int, code: str) -> bool:
    """Vérifie le dernier OTP non utilisé et non expiré."""
    db = get_db()
    row = db.execute(
        """
        SELECT id, code_hash
        FROM login_otps
        WHERE user_id = ?
          AND used_at IS NULL
          AND expires_at > datetime('now')
        ORDER BY id DESC
        LIMIT 1
        """,
        (user_id,),
    ).fetchone()

    if not row:
        return False

    if not check_password_hash(row["code_hash"], code):
        return False

    db.execute("UPDATE login_otps SET used_at = datetime('now') WHERE id = ?", (row["id"],))
    db.commit()
    return True


def send_email(to_email: str, subject: str, body: str) -> bool:
    """Envoie un email via SMTP si configuré.

    Variables requises:
      SMTP_HOST, SMTP_PORT (default 587), SMTP_USER, SMTP_PASSWORD, SMTP_FROM

    Options:
      SMTP_USE_SSL=1  -> utilise SMTP_SSL (souvent port 465)
      SMTP_STARTTLS=0 -> désactive STARTTLS (par défaut activé si pas SSL)
    """
    host = os.environ.get("SMTP_HOST")
    user = os.environ.get("SMTP_USER")
    password = os.environ.get("SMTP_PASSWORD")
    from_email = os.environ.get("SMTP_FROM") or user
    port = int(os.environ.get("SMTP_PORT", "587"))

    smtp_use_ssl = (os.environ.get("SMTP_USE_SSL") or "").strip().lower() in {"1", "true", "yes", "on"}
    smtp_starttls_env = (os.environ.get("SMTP_STARTTLS") or "").strip().lower()
    smtp_starttls = True if smtp_starttls_env == "" else smtp_starttls_env in {"1", "true", "yes", "on"}

    # Heuristique: si on est sur 465, on part sur SSL sauf si l'utilisateur a explicitement demandé STARTTLS
    if port == 465 and smtp_starttls_env == "":
        smtp_use_ssl = True

    missing = []
    if not host:
        missing.append("SMTP_HOST")
    if not user:
        missing.append("SMTP_USER")
    if not password:
        missing.append("SMTP_PASSWORD")
    if not from_email:
        missing.append("SMTP_FROM")

    if missing:
        # Log utile pour debug (sans exposer le mot de passe)
        try:
            app.logger.warning("SMTP not configured: missing %s", ", ".join(missing))
        except Exception:
            pass
        return False

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = from_email
    msg["To"] = to_email
    msg.set_content(body.strip())

    context = ssl.create_default_context()

    try:
        if smtp_use_ssl:
            with smtplib.SMTP_SSL(host, port, context=context) as server:
                server.ehlo()
                server.login(user, password)
                server.send_message(msg)
            return True

        with smtplib.SMTP(host, port) as server:
            server.ehlo()
            if smtp_starttls:
                server.starttls(context=context)
                server.ehlo()
            server.login(user, password)
            server.send_message(msg)
        return True
    except Exception:
        # Traceback complet côté serveur Flask
        try:
            app.logger.exception(
                "SMTP send failed (host=%s port=%s ssl=%s starttls=%s user=%s from=%s to=%s)",
                host,
                port,
                smtp_use_ssl,
                smtp_starttls,
                user,
                from_email,
                to_email,
            )
        except Exception:
            pass
        return False


def send_otp_email(to_email: str, code: str) -> bool:
    body = f"""
Ton code de vérification Collector.shop est :

{code}

Ce code expire dans 10 minutes.
"""
    return send_email(to_email, "Collector.shop — Code de vérification", body)


def _format_eur(cents: int) -> str:
    return (f"{cents/100:.2f} €").replace(".", ",")


def send_order_confirmation_email(to_email: str, order_id: int, total_cents: int, items: list[tuple[str, int, int]]) -> bool:
    """Envoie l'email de confirmation de commande.

    items: liste de tuples (title, price_cents, qty)
    """
    lines = [
        f"Commande #{order_id} confirmée.",
        "",
        "Détails:",
    ]
    for title, price_cents, qty in items:
        lines.append(f"- {title} x{qty} — {_format_eur(price_cents)}")
    lines.append("")
    lines.append(f"Total: {_format_eur(total_cents)}")
    lines.append("")
    lines.append("Merci pour votre achat !")

    return send_email(to_email, "Collector.shop — Confirmation de commande", "\n".join(lines))

ARTICLES = {
    1: {"titre": "Baskets Nike édition limitée", "prix": 220, "categorie": "Sneakers", "description": "Paire rare en excellent état.", "image": "1.png"},
    2: {"titre": "Figurine Star Wars vintage", "prix": 150, "categorie": "Figurines", "description": "Original années 80.", "image": "2.png"},
    3: {"titre": "Poster cinéma dédicacé", "prix": 95, "categorie": "Posters", "description": "Signature authentique.", "image": "3.png"},
    4: {"titre": "Casquette NBA rétro", "prix": 70, "categorie": "Mode", "description": "Édition collector.", "image": "4.png"},
    5: {"titre": "Vinyle Rock 1975", "prix": 130, "categorie": "Musique", "description": "Pressage original.", "image": "5.png"},
    6: {"titre": "Console Game Boy", "prix": 180, "categorie": "Jeux vidéo", "description": "Fonctionnelle, très bon état.", "image": "6.png"},
    7: {"titre": "Montre digitale vintage", "prix": 210, "categorie": "Accessoires", "description": "Années 90.", "image": "7.png"},
    8: {"titre": "Carte Pokémon rare", "prix": 300, "categorie": "Cartes", "description": "Première édition.", "image": "8.png"},
    9: {"titre": "Magazine culte 1989", "prix": 60, "categorie": "Presse", "description": "Très bon état.", "image": "9.png"},
}

@app.route("/")
@app.route("/catalogue")
def catalogue():
    uid = session.get("user_id")
    favorite_ids = set()
    if uid:
        favorite_ids = get_favorite_ids(int(uid))

    q = (request.args.get("q") or "").strip().lower()
    cat = (request.args.get("cat") or "").strip().lower()

    # Catégories à partir du catalogue fixe + pseudo-catégorie pour les annonces
    categories = sorted({a["categorie"] for a in ARTICLES.values()})
    if "Annonces" not in categories:
        categories.append("Annonces")

    def match_article(a):
        if cat:
            # si l'utilisateur filtre sur "annonces", on n'affiche pas les articles fixes
            if cat == "annonces":
                return False
            if a["categorie"].strip().lower() != cat:
                return False
        if not q:
            return True
        return q in a["titre"].strip().lower() or q in a["categorie"].strip().lower()

    filtered_articles = {aid: a for aid, a in ARTICLES.items() if match_article(a)}

    # Annonces vendeurs (filtre texte + filtre catégorie)
    db = get_db()
    include_posts = (not cat) or (cat == "annonces")
    seller_posts = []
    if include_posts:
        if q:
            seller_posts = db.execute(
                "SELECT id, user_id, title, description, price_cents, image_path FROM posts WHERE lower(title) LIKE ? OR lower(description) LIKE ? ORDER BY id DESC",
                (f"%{q}%", f"%{q}%"),
            ).fetchall()
        else:
            seller_posts = db.execute(
                "SELECT id, user_id, title, description, price_cents, image_path FROM posts ORDER BY id DESC"
            ).fetchall()

    # Fusion dans une seule liste pour l'affichage
    items = []
    for aid, a in filtered_articles.items():
        items.append(
            {
                "type": "article",
                "id": int(aid),
                "title": a.get("titre"),
                "price": f"{a.get('prix')} €",
                "image": f"images/{a.get('image')}",
                "detail_url": url_for("article_detail", article_id=int(aid)),
                "cart_id": int(aid),
            }
        )

    for p in seller_posts:
        items.append(
            {
                "type": "post",
                "id": int(p["id"]),
                "seller_id": int(p["user_id"]),
                "title": p["title"],
                "price": _format_eur(int(p["price_cents"])) if p["price_cents"] is not None else "",
                "image": p["image_path"],
                "detail_url": url_for("post_detail", post_id=int(p["id"])),
                "cart_id": SELLER_OFFSET + int(p["id"]),
            }
        )

    return render_template(
        "catalogue.html",
        items=items,
        favorite_ids=favorite_ids,
        categories=categories,
        selected_cat=cat,
        search_q=q,
    )


@app.route("/article/<int:article_id>")
def article_detail(article_id):
    article = ARTICLES.get(article_id)
    if not article:
        abort(404)

    uid = session.get("user_id")
    is_favorite = False
    if uid:
        is_favorite = int(article_id) in get_favorite_ids(int(uid))

    image_files = [f"images/{article['image']}"] if article.get("image") else []

    return render_template(
        "article_detail.html",
        article=article,
        article_id=article_id,
        is_favorite=is_favorite,
        image_files=image_files,
    )


@app.route("/post/<int:post_id>")
def post_detail(post_id: int):
    db = get_db()
    post = db.execute(
        """
        SELECT p.id, p.user_id, p.title, p.description, p.price_cents, p.image_path, p.created_at,
               u.email AS seller_email
        FROM posts p
        JOIN users u ON u.id = p.user_id
        WHERE p.id = ?
        """,
        (post_id,),
    ).fetchone()

    if not post:
        abort(404)

    item_id = SELLER_OFFSET + int(post_id)
    image_files = [post["image_path"]] if post["image_path"] else []

    return render_template(
        "post_detail.html",
        post=post,
        item_id=item_id,
        image_files=image_files,
    )


# --- Auth (SQLite) ---
@app.route("/inscription", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        first_name = (request.form.get("first_name") or "").strip()
        last_name = (request.form.get("last_name") or "").strip()
        role = (request.form.get("role") or "").strip()
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        password2 = request.form.get("password2") or ""
        captcha = (request.form.get("captcha") or "").strip()

        if not first_name or not last_name:
            flash("Nom et prénom obligatoires.", "error")
            return render_template(
                "register.html",
                captcha_question=generate_captcha(),
                form=request.form,
            )

        allowed_roles = {"acheteur", "vendeur"}
        if role not in allowed_roles:
            flash("Choisis un profil: acheteur ou vendeur.", "error")
            return render_template(
                "register.html",
                captcha_question=generate_captcha(),
                form=request.form,
            )

        if not email:
            flash("Email obligatoire.", "error")
            return render_template(
                "register.html",
                captcha_question=generate_captcha(),
                form=request.form,
            )

        if len(password) < 6:
            flash("Mot de passe trop court (min 6 caractères).", "error")
            return render_template(
                "register.html",
                captcha_question=generate_captcha(),
                form=request.form,
            )

        if password != password2:
            flash("Les mots de passe ne correspondent pas.", "error")
            return render_template(
                "register.html",
                captcha_question=generate_captcha(),
                form=request.form,
            )

        expected = session.get("captcha_answer")
        if not expected or captcha != expected:
            flash("Captcha incorrect.", "error")
            return render_template(
                "register.html",
                captcha_question=generate_captcha(),
                form=request.form,
            )

        db = get_db()
        try:
            db.execute(
                "INSERT INTO users (email, password_hash, first_name, last_name, role) VALUES (?, ?, ?, ?, ?)",
                (email, generate_password_hash(password), first_name, last_name, role),
            )
            db.commit()
        except sqlite3.IntegrityError:
            flash("Cet email est déjà utilisé.", "error")
            return render_template(
                "register.html",
                captcha_question=generate_captcha(),
                form=request.form,
            )

        # reset captcha session
        session.pop("captcha_answer", None)
        session.pop("captcha_question", None)

        flash("Compte créé ! Tu peux te connecter.", "success")
        return redirect(url_for("login"))

    # GET
    return render_template("register.html", captcha_question=generate_captcha(), form={})


@app.route("/connexion", methods=["GET", "POST"])
def login():
    # déjà connecté
    if session.get("user_id"):
        return redirect(url_for("catalogue"))

    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        next_url = _safe_next_url(request.form.get("next") or request.args.get("next"))

        db = get_db()
        user = db.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()

        if not user or not check_password_hash(user["password_hash"], password):
            flash("Email ou mot de passe incorrect.", "error")
            return render_template("login.html", next_url=next_url)

        # Si 2FA désactivée -> connexion directe
        if not app.config.get("USE_2FA"):
            session.clear()
            session["user_id"] = user["id"]
            session["user_email"] = user["email"]
            flash("Connexion réussie.", "success")
            return redirect(next_url or url_for("catalogue"))

        # Sinon, 2FA email
        session["pending_user_id"] = user["id"]
        session["pending_user_email"] = user["email"]
        session["otp_attempts"] = 0
        session["login_next"] = next_url

        code = create_login_otp(user["id"]) 

        sent = False
        try:
            sent = send_otp_email(user["email"], code)
        except Exception:
            try:
                app.logger.exception("Failed to send OTP email to %s", user["email"])
            except Exception:
                pass
            sent = False

        if sent:
            flash("Code de vérification envoyé par email.", "success")
            return redirect(url_for("verify_2fa"))
        else:
            flash("Impossible d'envoyer l'email de vérification (vérifie la config SMTP et les logs serveur).", "error")
            return redirect(url_for("login"))

    # GET
    next_url = _safe_next_url(request.args.get("next"))
    return render_template("login.html", next_url=next_url)


@app.route("/verification", methods=["GET", "POST"])
def verify_2fa():
    if not app.config.get("USE_2FA"):
        return redirect(url_for("login"))

    user_id = session.get("pending_user_id")
    email = session.get("pending_user_email")

    if not user_id:
        return redirect(url_for("login"))

    if request.method == "POST":
        code = (request.form.get("code") or "").strip()
        session["otp_attempts"] = int(session.get("otp_attempts", 0)) + 1

        if session["otp_attempts"] > 5:
            session.pop("pending_user_id", None)
            session.pop("pending_user_email", None)
            session.pop("otp_attempts", None)
            flash("Trop de tentatives. Recommence la connexion.", "error")
            return redirect(url_for("login"))

        if not code.isdigit() or len(code) != 6:
            flash("Le code doit contenir 6 chiffres.", "error")
            return render_template("verify.html", email=email)

        if not verify_login_otp(user_id, code):
            flash("Code invalide ou expiré.", "error")
            return render_template("verify.html", email=email)

        # Step 2 OK -> session finale
        session.pop("otp_attempts", None)
        session.pop("pending_user_id", None)
        session.pop("pending_user_email", None)
        next_url = _safe_next_url(session.pop("login_next", None))

        session["user_id"] = user_id
        session["user_email"] = email
        flash("Connexion réussie.", "success")
        return redirect(next_url or url_for("catalogue"))

    return render_template("verify.html", email=email)


@app.route("/verification/renvoyer")
def resend_2fa():
    if not app.config.get("USE_2FA"):
        return redirect(url_for("login"))

    user_id = session.get("pending_user_id")
    email = session.get("pending_user_email")

    if not user_id:
        return redirect(url_for("login"))

    code = create_login_otp(user_id)

    sent = False
    try:
        sent = send_otp_email(email, code)
    except Exception:
        try:
            app.logger.exception("Failed to resend OTP email to %s", email)
        except Exception:
            pass
        sent = False

    if sent:
        flash("Nouveau code envoyé par email.", "success")
        return redirect(url_for("verify_2fa"))
    else:
        flash("Impossible d'envoyer l'email (vérifie la config SMTP et les logs serveur).", "error")
        return redirect(url_for("login"))


@app.route("/favoris")
@login_required
def favoris():
    uid = int(session["user_id"])
    fav_ids = sorted(get_favorite_ids(uid))
    fav_articles = [(aid, ARTICLES.get(aid)) for aid in fav_ids if ARTICLES.get(aid)]
    return render_template("favorites.html", fav_articles=fav_articles)


@app.route("/favoris/<int:article_id>/toggle", methods=["POST"])
@login_required
def toggle_favorite(article_id):
    if article_id not in ARTICLES:
        abort(404)

    uid = int(session["user_id"])
    db = get_db()
    exists = db.execute(
        "SELECT 1 FROM favorites WHERE user_id = ? AND article_id = ?",
        (uid, article_id),
    ).fetchone()

    if exists:
        db.execute(
            "DELETE FROM favorites WHERE user_id = ? AND article_id = ?",
            (uid, article_id),
        )
        db.commit()
        flash("Retiré des favoris.", "success")
    else:
        db.execute(
            "INSERT INTO favorites (user_id, article_id) VALUES (?, ?)",
            (uid, article_id),
        )
        db.commit()
        flash("Ajouté aux favoris.", "success")

    nxt = _safe_next_url(request.form.get("next"))
    return redirect(nxt or url_for("catalogue"))


@app.route("/panier")
@login_required
def panier():
    uid = int(session["user_id"])
    db = get_db()
    rows = db.execute(
        "SELECT article_id, qty FROM cart_items WHERE user_id = ? ORDER BY created_at DESC",
        (uid,),
    ).fetchall()

    items = []
    total_cents = 0
    for r in rows:
        aid = int(r["article_id"])
        qty = int(r["qty"])
        art = ARTICLES.get(aid)
        if not art:
            continue
        price_cents = int(art["prix"] * 100)
        line_total = price_cents * qty
        total_cents += line_total
        items.append(
            {
                "article_id": aid,
                "article": art,
                "qty": qty,
                "price_cents": price_cents,
                "line_total_cents": line_total,
            }
        )

    return render_template("cart.html", items=items, total_cents=total_cents)


@app.route("/panier/ajouter/<int:article_id>", methods=["POST"])
@login_required
def cart_add(article_id):
    uid = int(session["user_id"]) 
    db = get_db()

    # Valider que l'article existe (catalogue fixe ou post vendeur)
    if article_id >= SELLER_OFFSET:
        post_id = article_id - SELLER_OFFSET
        exists = db.execute("SELECT 1 FROM posts WHERE id = ?", (post_id,)).fetchone()
        if not exists:
            abort(404)
    else:
        if article_id not in ARTICLES:
            abort(404)

    row = db.execute(
        "SELECT qty FROM cart_items WHERE user_id = ? AND article_id = ?",
        (uid, article_id),
    ).fetchone()

    if row:
        db.execute(
            "UPDATE cart_items SET qty = qty + 1 WHERE user_id = ? AND article_id = ?",
            (uid, article_id),
        )
        flash("Quantité mise à jour dans le panier.", "success")
    else:
        db.execute(
            "INSERT INTO cart_items (user_id, article_id, qty) VALUES (?, ?, 1)",
            (uid, article_id),
        )
        flash("Ajouté au panier.", "success")
    db.commit()

    nxt = _safe_next_url(request.form.get("next"))
    return redirect(nxt or url_for("panier"))


@app.route("/panier/retirer/<int:article_id>", methods=["POST"])
@login_required
def cart_remove(article_id):
    uid = int(session["user_id"])
    db = get_db()
    db.execute(
        "DELETE FROM cart_items WHERE user_id = ? AND article_id = ?",
        (uid, article_id),
    )
    db.commit()
    flash("Retiré du panier.", "success")
    return redirect(url_for("panier"))


def _cart_items_and_total(uid: int):
    db = get_db()
    rows = db.execute(
        "SELECT article_id, qty FROM cart_items WHERE user_id = ?",
        (uid,),
    ).fetchall()
    items = []
    total_cents = 0
    order_items = []
    for r in rows:
        aid = int(r["article_id"])
        qty = int(r["qty"])
        if aid >= SELLER_OFFSET:
            post_id = aid - SELLER_OFFSET
            post = db.execute(
                "SELECT id, title, price_cents, image_path FROM posts WHERE id = ?",
                (post_id,),
            ).fetchone()
            if not post:
                continue
            title = post["title"]
            price_cents = int(post["price_cents"])
            product = {"titre": title, "prix": price_cents / 100.0, "image": post["image_path"]}
        else:
            art = ARTICLES.get(aid)
            if not art:
                continue
            title = art["titre"]
            price_cents = int(art["prix"] * 100)
            product = art
        line_total = price_cents * qty
        total_cents += line_total
        items.append({
            "article_id": aid,
            "article": product,
            "qty": qty,
            "price_cents": price_cents,
            "line_total_cents": line_total,
        })
        order_items.append((aid, title, price_cents, qty))
    return items, order_items, total_cents


def _luhn_ok(num: str) -> bool:
    s = 0
    alt = False
    for ch in reversed(num):
        d = ord(ch) - 48
        if d < 0 or d > 9:
            return False
        if alt:
            d *= 2
            if d > 9:
                d -= 9
        s += d
        alt = not alt
    return (s % 10) == 0


def _is_mastercard(num: str) -> bool:
    # Mastercard: 51-55 or 2221-2720, length 16
    if len(num) != 16 or not num.isdigit():
        return False
    first2 = int(num[:2])
    first4 = int(num[:4])
    in_old_bin = 51 <= first2 <= 55
    in_new_bin = 2221 <= first4 <= 2720
    return (in_old_bin or in_new_bin) and _luhn_ok(num)


def _is_visa(num: str) -> bool:
    # Visa: starts with 4, length 13, 16, or 19
    if not num.isdigit() or not num.startswith("4"):
        return False
    if len(num) not in (13, 16, 19):
        return False
    return _luhn_ok(num)


def _is_card_supported(num: str) -> bool:
    return _is_mastercard(num) or _is_visa(num)


def _valid_exp_mm_yy(exp: str) -> bool:
    m = re.fullmatch(r"\s*(\d{2})\s*/\s*(\d{2})\s*", exp or "")
    if not m:
        return False
    mm = int(m.group(1))
    yy = int(m.group(2))
    if mm < 1 or mm > 12:
        return False
    # Interpret YY as 2000-2099
    year = 2000 + yy
    now = datetime.utcnow()
    # Card valid through end of month
    exp_month_end = datetime(year, mm, 1)
    # if same month/year, still valid until month ends
    if (exp_month_end.year, exp_month_end.month) < (now.year, now.month):
        return False
    return True


def _valid_cvc(cvc: str) -> bool:
    return bool(re.fullmatch(r"\d{3}", (cvc or "").strip()))




@app.route("/paiement/success")
@login_required
def payment_success():
    order_id = request.args.get("order_id")
    return render_template("payment_success.html", order_id=order_id)


@app.route("/paiement/carte", methods=["GET", "POST"])
@login_required
def card_payment():
    uid = int(session["user_id"])
    items, order_items, total_cents = _cart_items_and_total(uid)
    if not items:
        flash("Ton panier est vide.", "error")
        return redirect(url_for("panier"))

    errors = []
    form = {"card_name": "", "card_number": "", "exp": "", "cvc": ""}

    if request.method == "POST":
        form["card_name"] = (request.form.get("card_name") or "").strip()
        raw_number = (request.form.get("card_number") or "")
        number = re.sub(r"\D+", "", raw_number)
        form["card_number"] = raw_number.strip()
        form["exp"] = (request.form.get("exp") or "").strip()
        form["cvc"] = (request.form.get("cvc") or "").strip()

        if not form["card_name"]:
            errors.append("Nom du titulaire obligatoire.")
        if not _is_card_supported(number):
            errors.append("Numéro de carte invalide (Visa/Mastercard).")
        if not _valid_exp_mm_yy(form["exp"]):
            errors.append("Expiration invalide (MM/YY, carte non expirée).")
        if not _valid_cvc(form["cvc"]):
            errors.append("CVC invalide (3 chiffres).")


        if not errors:
            # Créer la commande directement en "paid"
            db = get_db()
            cur = db.execute(
                "INSERT INTO orders (user_id, total_cents, status, payment_status, paid_at) VALUES (?, ?, 'paid', 'paid', datetime('now'))",
                (uid, total_cents),
            )
            order_id = cur.lastrowid
            for aid, title, price_cents, qty in order_items:
                db.execute(
                    "INSERT INTO order_items (order_id, article_id, title, price_cents, qty) VALUES (?, ?, ?, ?, ?)",
                    (order_id, aid, title, price_cents, qty),
                )
            # vider panier
            db.execute("DELETE FROM cart_items WHERE user_id = ?", (uid,))
            db.commit()

            # email de confirmation
            try:
                send_order_confirmation_email(
                    session.get("user_email"),
                    order_id,
                    total_cents,
                    [(t, p, q) for (_, t, p, q) in order_items],
                )
            except Exception:
                pass

            return render_template("payment_success.html", order_id=order_id)

    return render_template("card_payment.html", items=items, total_cents=total_cents, form=form, errors=errors)




@app.route("/admin")
@admin_required
def admin_dashboard():
    db = get_db()
    # Stats ventes globales
    total_orders = db.execute("SELECT COUNT(1) FROM orders").fetchone()[0]
    paid_orders = db.execute("SELECT COUNT(1) FROM orders WHERE payment_status = 'paid'").fetchone()[0]
    revenue_cents = db.execute("SELECT COALESCE(SUM(total_cents),0) FROM orders WHERE payment_status = 'paid'").fetchone()[0]

    # Séries temporelles (14 derniers jours)
    paid_rows = db.execute(
        """
        SELECT strftime('%Y-%m-%d', paid_at) AS d, COUNT(1) AS c, COALESCE(SUM(total_cents),0) AS s
        FROM orders
        WHERE paid_at IS NOT NULL AND date(paid_at) >= date('now','-13 day')
        GROUP BY d
        """
    ).fetchall()
    all_rows = db.execute(
        """
        SELECT strftime('%Y-%m-%d', created_at) AS d, COUNT(1) AS c
        FROM orders
        WHERE date(created_at) >= date('now','-13 day')
        GROUP BY d
        """
    ).fetchall()

    paid_map = {r["d"]: (int(r["c"]), int(r["s"])) for r in paid_rows}
    all_map = {r["d"]: int(r["c"]) for r in all_rows}

    labels = []
    series_paid = []
    series_total = []
    series_rev = []
    today = datetime.utcnow().date()
    for i in range(13, -1, -1):
        d = today - timedelta(days=i)
        ds = d.strftime('%Y-%m-%d')
        labels.append(ds)
        c_paid, s_paid = paid_map.get(ds, (0, 0))
        series_paid.append(c_paid)
        series_total.append(all_map.get(ds, 0))
        series_rev.append(round(s_paid / 100.0, 2))

    # Top 5 articles vendus
    top_items = db.execute(
        """
        SELECT title, SUM(qty) as q, SUM(price_cents*qty) as amount
        FROM order_items oi
        JOIN orders o ON o.id = oi.order_id
        WHERE o.payment_status = 'paid'
        GROUP BY title
        ORDER BY q DESC
        LIMIT 5
        """
    ).fetchall()

    users = db.execute(
        "SELECT id, email, first_name, last_name, COALESCE(role, '') AS role, created_at FROM users ORDER BY id DESC"
    ).fetchall()

    return render_template(
        "admin.html",
        users=users,
        stats={
            "total_orders": int(total_orders or 0),
            "paid_orders": int(paid_orders or 0),
            "revenue_cents": int(revenue_cents or 0),
            "top_items": top_items,
            "chart": {
                "labels": labels,
                "paid": series_paid,
                "total": series_total,
                "revenue": series_rev,
            },
        },
    )


@app.route("/admin/users/<int:user_id>/role", methods=["POST"])
@admin_required
def admin_update_user_role(user_id: int):
    role = (request.form.get("role") or "").strip().lower()
    if role not in {"acheteur", "vendeur", "admin"}:
        flash("Rôle invalide.", "error")
        return redirect(url_for("admin_dashboard"))

    db = get_db()
    db.execute("UPDATE users SET role = ? WHERE id = ?", (role, user_id))
    db.commit()
    flash("Rôle mis à jour.", "success")
    return redirect(url_for("admin_dashboard"))


@app.route("/annonces")
def public_posts():
    db = get_db()
    rows = db.execute(
        "SELECT p.id, p.title, p.description, p.price_cents, p.image_path, u.email as seller, p.created_at FROM posts p JOIN users u ON u.id = p.user_id ORDER BY p.id DESC"
    ).fetchall()
    return render_template("posts.html", posts=rows)


@app.route("/vendeur/poste/nouveau", methods=["GET", "POST"])
@seller_required
def seller_new_post():
    form = {"title": "", "description": "", "price": ""}
    errors = []
    if request.method == "POST":
        form["title"] = (request.form.get("title") or "").strip()
        form["description"] = (request.form.get("description") or "").strip()
        form["price"] = (request.form.get("price") or "").strip()
        file = request.files.get("photo")

        if not form["title"]:
            errors.append("Titre obligatoire.")
        price_cents = 0
        try:
            price_cents = int(round(float(form["price"].replace(",", ".")) * 100))
            if price_cents <= 0:
                errors.append("Prix invalide.")
        except Exception:
            errors.append("Prix invalide.")

        image_path = None
        if file and file.filename:
            ext = file.filename.rsplit(".", 1)[-1].lower()
            if ext not in ALLOWED_IMAGE_EXT:
                errors.append("Format d'image non supporté (png, jpg, jpeg, webp).")
            else:
                filename = secure_filename(file.filename)
                unique = secrets.token_hex(8) + "." + ext
                dest = os.path.join(app.config["UPLOAD_FOLDER"], unique)
                file.save(dest)
                image_path = f"uploads/{unique}"
        else:
            errors.append("Photo obligatoire.")

        if not errors:
            db = get_db()
            db.execute(
                "INSERT INTO posts (user_id, title, description, price_cents, image_path) VALUES (?, ?, ?, ?, ?)",
                (int(session["user_id"]), form["title"], form["description"], price_cents, image_path),
            )
            db.commit()
            flash("Annonce publiée.", "success")
            return redirect(url_for("admin_dashboard"))

    return render_template("seller_post_new.html", form=form, errors=errors)


@app.route("/messages")
@login_required
def messages_inbox():
    uid = int(session["user_id"])
    db = get_db()
    convs = db.execute(
        """
        SELECT c.id, c.subject, c.last_message_at,
               u1.email AS buyer_email, u2.email AS seller_email,
               SUM(CASE WHEN m.read_at IS NULL AND m.sender_id != ? THEN 1 ELSE 0 END) AS unread
        FROM conversations c
        JOIN users u1 ON u1.id = c.buyer_id
        JOIN users u2 ON u2.id = c.seller_id
        LEFT JOIN messages m ON m.conv_id = c.id
        WHERE c.buyer_id = ? OR c.seller_id = ?
        GROUP BY c.id
        ORDER BY c.last_message_at DESC
        """,
        (uid, uid, uid),
    ).fetchall()
    return render_template("messages.html", convs=convs, uid=uid)


@app.route("/messages/new/<int:seller_id>")
@login_required
def messages_new(seller_id: int):
    uid = int(session["user_id"])
    post_id = request.args.get("post_id")
    subject = "Contact à propos d'une annonce"
    db = get_db()
    # trouver ou créer la conv
    row = db.execute(
        "SELECT id FROM conversations WHERE buyer_id = ? AND seller_id = ? AND (post_id = ? OR (? IS NULL AND post_id IS NULL)) ORDER BY id DESC LIMIT 1",
        (uid, seller_id, post_id, post_id),
    ).fetchone()
    if row:
        conv_id = int(row["id"])
    else:
        if post_id:
            p = db.execute("SELECT title FROM posts WHERE id = ?", (post_id,)).fetchone()
            if p:
                subject = f"À propos de: {p['title']}"
        cur = db.execute(
            "INSERT INTO conversations (buyer_id, seller_id, post_id, subject) VALUES (?, ?, ?, ?)",
            (uid, seller_id, post_id, subject),
        )
        conv_id = cur.lastrowid
        db.commit()
    return redirect(url_for("messages_thread", conv_id=conv_id))


@app.route("/messages/<int:conv_id>", methods=["GET", "POST"])
@login_required
def messages_thread(conv_id: int):
    uid = int(session["user_id"])
    db = get_db()
    conv = db.execute(
        "SELECT * FROM conversations WHERE id = ? AND (buyer_id = ? OR seller_id = ?)",
        (conv_id, uid, uid),
    ).fetchone()
    if not conv:
        abort(404)

    if request.method == "POST":
        body = (request.form.get("body") or "").strip()
        if len(body) >= 1:
            db.execute(
                "INSERT INTO messages (conv_id, sender_id, body) VALUES (?, ?, ?)",
                (conv_id, uid, body[:2000]),
            )
            db.execute(
                "UPDATE conversations SET last_message_at = datetime('now') WHERE id = ?",
                (conv_id,),
            )
            db.commit()
        return redirect(url_for("messages_thread", conv_id=conv_id))

    # mark others as read
    db.execute(
        "UPDATE messages SET read_at = datetime('now') WHERE conv_id = ? AND sender_id != ? AND read_at IS NULL",
        (conv_id, uid),
    )
    db.commit()

    msgs = db.execute(
        "SELECT m.*, u.email AS sender_email FROM messages m JOIN users u ON u.id = m.sender_id WHERE m.conv_id = ? ORDER BY m.id ASC",
        (conv_id,),
    ).fetchall()

    return render_template("thread.html", conv=conv, messages=msgs, uid=uid)


@app.route("/commandes")
@login_required
def orders():
    uid = int(session["user_id"])
    db = get_db()
    orders_rows = db.execute(
        "SELECT id, total_cents, status, created_at FROM orders WHERE user_id = ? ORDER BY id DESC",
        (uid,),
    ).fetchall()

    return render_template("orders.html", orders=orders_rows)


@app.route("/deconnexion")
def logout():
    session.clear()
    flash("Déconnecté.", "success")
    return redirect(url_for("catalogue"))


if __name__ == "__main__":
    init_db()
    debug_env = os.environ.get("FLASK_DEBUG")
    debug = bool(int(debug_env)) if debug_env is not None else app.config.get("APP_ENV") != "production"
    app.run(debug=debug)
