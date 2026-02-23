"""
Shared pytest fixtures for Collector.shop test suite.
"""

import os
import sys
import tempfile
import pytest

# Ensure the app root is on the path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


@pytest.fixture(scope="session")
def app():
    """Create the Flask app with an in-memory/temp SQLite database."""
    from app import app as flask_app, init_db

    db_fd, db_path = tempfile.mkstemp(suffix=".sqlite3")
    flask_app.config.update(
        TESTING=True,
        DATABASE=db_path,
        SECRET_KEY="test-secret-key",
        WTF_CSRF_ENABLED=False,
        USE_2FA=False,
        ADMIN_EMAIL="admin@test.com",
        UPLOAD_FOLDER=tempfile.mkdtemp(),
    )

    with flask_app.app_context():
        init_db()

    yield flask_app

    os.close(db_fd)
    os.unlink(db_path)


@pytest.fixture
def client(app):
    """Flask test client (fresh per test)."""
    return app.test_client()


@pytest.fixture
def runner(app):
    """Flask CLI test runner."""
    return app.test_cli_runner()


def _register(client, email, password="password123", role="acheteur",
               first_name="Test", last_name="User"):
    """Register a user and seed the captcha in the session first."""
    with client.session_transaction() as sess:
        sess["captcha_answer"] = "5"
        sess["captcha_question"] = "3 + 2"
    return client.post(
        "/inscription",
        data={
            "first_name": first_name,
            "last_name": last_name,
            "role": role,
            "email": email,
            "password": password,
            "password2": password,
            "captcha": "5",
        },
        follow_redirects=True,
    )


def _login(client, email, password="password123"):
    return client.post(
        "/connexion",
        data={"email": email, "password": password},
        follow_redirects=True,
    )


def _logout(client):
    return client.get("/deconnexion", follow_redirects=True)


@pytest.fixture
def register_fn():
    return _register


@pytest.fixture
def login_fn():
    return _login


@pytest.fixture
def logout_fn():
    return _logout


@pytest.fixture
def registered_user(client):
    """Registers and returns (client, email, password) for a buyer."""
    email = "buyer@test.com"
    password = "buyerpass1"
    _register(client, email, password=password, role="acheteur")
    return client, email, password


@pytest.fixture
def logged_in_user(client, registered_user):
    """Returns a client that is already logged in as a buyer."""
    c, email, password = registered_user
    _login(c, email, password)
    return c, email


@pytest.fixture
def registered_seller(client):
    """Registers and returns (client, email, password) for a seller."""
    email = "seller@test.com"
    password = "sellerpass1"
    _register(client, email, password=password, role="vendeur")
    return client, email, password


@pytest.fixture
def logged_in_seller(client, registered_seller):
    c, email, password = registered_seller
    _login(c, email, password)
    return c, email


@pytest.fixture
def admin_client(app, client):
    """Registers an admin user and returns a logged-in client."""
    email = app.config["ADMIN_EMAIL"]
    password = "adminpass1"
    _register(client, email, password=password, role="acheteur",
               first_name="Admin", last_name="User")
    # Promote to admin in DB
    import sqlite3
    conn = sqlite3.connect(app.config["DATABASE"])
    conn.execute(
        "UPDATE users SET role = 'admin' WHERE lower(email) = lower(?)", (email,)
    )
    conn.commit()
    conn.close()
    _login(client, email, password)
    return client
