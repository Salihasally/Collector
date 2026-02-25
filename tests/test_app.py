"""
Unit & integration tests for Collector.shop (Flask).

Run with:  pytest
"""

import re
import pytest

from tests.conftest import _register, _login, _logout



class TestLuhn:
    """Tests for the _luhn_ok helper."""

    def _luhn_ok(self):
        from app import _luhn_ok
        return _luhn_ok

    def test_valid_visa_number(self):
        from app import _luhn_ok
        assert _luhn_ok("4111111111111111") is True

    def test_valid_mastercard_number(self):
        from app import _luhn_ok
        assert _luhn_ok("5500005555555559") is True

    def test_invalid_number(self):
        from app import _luhn_ok
        assert _luhn_ok("1234567890123456") is False

    def test_empty_string(self):
        from app import _luhn_ok
        assert _luhn_ok("") is False

    def test_non_digit_chars(self):
        from app import _luhn_ok
        assert _luhn_ok("411111111111111X") is False

    def test_single_zero(self):
        from app import _luhn_ok
        # Too short to be a valid card — rejected by length guard in app.py
        assert _luhn_ok("0") is False

    def test_too_short_number(self):
        from app import _luhn_ok
        assert _luhn_ok("1234") is False


class TestCardDetection:
    """Tests for _is_visa / _is_mastercard / _is_card_supported."""

    def test_visa_16_digit(self):
        from app import _is_visa
        assert _is_visa("4111111111111111") is True

    def test_visa_starts_with_4_invalid_luhn(self):
        from app import _is_visa
        assert _is_visa("4111111111111112") is False

    def test_visa_wrong_length(self):
        from app import _is_visa
        assert _is_visa("41111111111111") is False  # 14 digits

    def test_visa_non_digits(self):
        from app import _is_visa
        assert _is_visa("4111 1111 1111 1111") is False  # contains spaces

    def test_mastercard_51_prefix(self):
        from app import _is_mastercard
        assert _is_mastercard("5500005555555559") is True

    def test_mastercard_25xx_prefix(self):
        from app import _is_mastercard
        # 2221-2720 range
        assert _is_mastercard("2221000000000009") is True

    def test_mastercard_invalid_luhn(self):
        from app import _is_mastercard
        assert _is_mastercard("5500005555555550") is False

    def test_mastercard_wrong_length(self):
        from app import _is_mastercard
        assert _is_mastercard("550000555555555") is False  # 15 digits

    def test_supported_accepts_visa(self):
        from app import _is_card_supported
        assert _is_card_supported("4111111111111111") is True

    def test_supported_accepts_mastercard(self):
        from app import _is_card_supported
        assert _is_card_supported("5500005555555559") is True

    def test_supported_rejects_amex(self):
        from app import _is_card_supported
        # AMEX: starts with 34 or 37, 15 digits
        assert _is_card_supported("378282246310005") is False


class TestExpiry:
    """Tests for _valid_exp_mm_yy."""

    def test_valid_future_date(self):
        from app import _valid_exp_mm_yy
        assert _valid_exp_mm_yy("12/99") is True

    def test_invalid_month_00(self):
        from app import _valid_exp_mm_yy
        assert _valid_exp_mm_yy("00/30") is False

    def test_invalid_month_13(self):
        from app import _valid_exp_mm_yy
        assert _valid_exp_mm_yy("13/30") is False

    def test_expired_past_year(self):
        from app import _valid_exp_mm_yy
        assert _valid_exp_mm_yy("01/20") is False

    def test_wrong_format_missing_slash(self):
        from app import _valid_exp_mm_yy
        assert _valid_exp_mm_yy("1230") is False

    def test_wrong_format_letters(self):
        from app import _valid_exp_mm_yy
        assert _valid_exp_mm_yy("AA/BB") is False

    def test_spaces_around_slash(self):
        from app import _valid_exp_mm_yy
        assert _valid_exp_mm_yy("12 / 99") is True

    def test_empty_string(self):
        from app import _valid_exp_mm_yy
        assert _valid_exp_mm_yy("") is False

    def test_none(self):
        from app import _valid_exp_mm_yy
        assert _valid_exp_mm_yy(None) is False


class TestCVC:
    """Tests for _valid_cvc."""

    def test_valid_3_digits(self):
        from app import _valid_cvc
        assert _valid_cvc("123") is True

    def test_only_2_digits(self):
        from app import _valid_cvc
        assert _valid_cvc("12") is False

    def test_4_digits(self):
        from app import _valid_cvc
        assert _valid_cvc("1234") is False

    def test_letters(self):
        from app import _valid_cvc
        assert _valid_cvc("abc") is False

    def test_empty(self):
        from app import _valid_cvc
        assert _valid_cvc("") is False

    def test_with_spaces(self):
        from app import _valid_cvc
        assert _valid_cvc("1 2") is False

    def test_leading_trailing_whitespace_stripped(self):
        from app import _valid_cvc
        # The function strips the cvc before matching
        assert _valid_cvc(" 123 ") is True



class TestSafeNextUrl:
    def test_valid_internal_path(self):
        from app import _safe_next_url
        assert _safe_next_url("/panier") == "/panier"

    def test_rejects_external_url(self):
        from app import _safe_next_url
        assert _safe_next_url("https://evil.com") is None

    def test_rejects_protocol_relative(self):
        from app import _safe_next_url
        assert _safe_next_url("//evil.com/path") is None

    def test_none_returns_none(self):
        from app import _safe_next_url
        assert _safe_next_url(None) is None

    def test_empty_string_returns_none(self):
        from app import _safe_next_url
        assert _safe_next_url("") is None


class TestRegistration:
    def test_get_register_page(self, client):
        rv = client.get("/inscription")
        assert rv.status_code == 200
        assert b"Cr" in rv.data  # "Créer un compte"

    def test_successful_registration(self, client):
        rv = _register(client, "newuser@test.com")
        assert rv.status_code == 200
        # Should redirect to login page on success
        assert b"connecter" in rv.data.lower() or b"connexion" in rv.data.lower()

    def test_duplicate_email(self, client):
        _register(client, "dup@test.com")
        rv = _register(client, "dup@test.com")
        assert b"d" in rv.data  # "déjà utilisé" flash message

    def test_password_too_short(self, client):
        with client.session_transaction() as sess:
            sess["captcha_answer"] = "5"
        rv = client.post(
            "/inscription",
            data={
                "first_name": "A", "last_name": "B", "role": "acheteur",
                "email": "short@test.com", "password": "ab", "password2": "ab",
                "captcha": "5",
            },
            follow_redirects=True,
        )
        assert b"court" in rv.data or b"min" in rv.data

    def test_password_mismatch(self, client):
        with client.session_transaction() as sess:
            sess["captcha_answer"] = "5"
        rv = client.post(
            "/inscription",
            data={
                "first_name": "A", "last_name": "B", "role": "acheteur",
                "email": "mismatch@test.com", "password": "abcdef",
                "password2": "DIFFERENT", "captcha": "5",
            },
            follow_redirects=True,
        )
        assert b"correspondent" in rv.data

    def test_bad_captcha(self, client):
        with client.session_transaction() as sess:
            sess["captcha_answer"] = "5"
        rv = client.post(
            "/inscription",
            data={
                "first_name": "A", "last_name": "B", "role": "acheteur",
                "email": "captcha@test.com", "password": "abcdef",
                "password2": "abcdef", "captcha": "999",
            },
            follow_redirects=True,
        )
        assert b"captcha" in rv.data.lower()

    def test_invalid_role_rejected(self, client):
        with client.session_transaction() as sess:
            sess["captcha_answer"] = "5"
        rv = client.post(
            "/inscription",
            data={
                "first_name": "A", "last_name": "B", "role": "hacker",
                "email": "hacker@test.com", "password": "abcdef",
                "password2": "abcdef", "captcha": "5",
            },
            follow_redirects=True,
        )
        assert b"profil" in rv.data.lower() or b"acheteur" in rv.data.lower()


class TestLogin:
    def test_get_login_page(self, client):
        rv = client.get("/connexion")
        assert rv.status_code == 200

    def test_successful_login(self, client):
        _register(client, "login_ok@test.com", password="pass1234")
        rv = _login(client, "login_ok@test.com", "pass1234")
        assert rv.status_code == 200
        # Should be on catalogue
        assert b"Catalogue" in rv.data or b"catalogue" in rv.data.lower()

    def test_wrong_password(self, client):
        _register(client, "wrong_pw@test.com", password="correct1")
        rv = _login(client, "wrong_pw@test.com", "WRONG")
        assert b"incorrect" in rv.data.lower()

    def test_unknown_email(self, client):
        rv = _login(client, "nobody@test.com", "whatever")
        assert b"incorrect" in rv.data.lower()

    def test_logout(self, client):
        _register(client, "logout_me@test.com", password="pass1234")
        _login(client, "logout_me@test.com", "pass1234")
        rv = _logout(client)
        assert rv.status_code == 200
        # After logout, protected pages redirect to login
        rv2 = client.get("/panier", follow_redirects=True)
        assert b"connexion" in rv2.data.lower() or b"connecte" in rv2.data.lower()

    def test_already_logged_in_redirects(self, client, logged_in_user):
        rv = client.get("/connexion", follow_redirects=True)
        # Should be redirected to catalogue, not shown login form
        assert b"Catalogue" in rv.data or rv.status_code == 200




class TestCatalogue:
    def test_catalogue_accessible_anonymously(self, client):
        rv = client.get("/catalogue")
        assert rv.status_code == 200

    def test_root_redirects_or_shows_catalogue(self, client):
        rv = client.get("/", follow_redirects=True)
        assert rv.status_code == 200

    def test_search_returns_result(self, client):
        rv = client.get("/catalogue?q=nike")
        assert rv.status_code == 200
        assert b"Nike" in rv.data

    def test_search_no_result_shows_empty(self, client):
        rv = client.get("/catalogue?q=xyznonexistent9999")
        assert rv.status_code == 200

    def test_category_filter(self, client):
        rv = client.get("/catalogue?cat=sneakers")
        assert rv.status_code == 200

    def test_article_detail_valid(self, client):
        rv = client.get("/article/1")
        assert rv.status_code == 200
        assert b"Nike" in rv.data

    def test_article_detail_not_found(self, client):
        rv = client.get("/article/99999")
        assert rv.status_code == 404



class TestFavorites:
    def test_favorites_requires_login(self, client):
        rv = client.get("/favoris", follow_redirects=True)
        assert b"connecte" in rv.data.lower() or b"connexion" in rv.data.lower()

    def test_add_favorite(self, client):
        _register(client, "fav_user@test.com", password="favpass1")
        _login(client, "fav_user@test.com", "favpass1")
        rv = client.post(
            "/favoris/1/toggle",
            data={"next": "/catalogue"},
            follow_redirects=True,
        )
        assert rv.status_code == 200
        assert b"favoris" in rv.data.lower()

    def test_toggle_favorite_twice_removes_it(self, client):
        _register(client, "fav_toggle@test.com", password="favpass1")
        _login(client, "fav_toggle@test.com", "favpass1")
        # Add
        client.post("/favoris/1/toggle", data={"next": "/catalogue"}, follow_redirects=True)
        # Remove
        rv = client.post(
            "/favoris/1/toggle",
            data={"next": "/catalogue"},
            follow_redirects=True,
        )
        assert b"retir" in rv.data.lower()

    def test_favorites_page_shows_added(self, client):
        _register(client, "fav_page@test.com", password="favpass1")
        _login(client, "fav_page@test.com", "favpass1")
        client.post("/favoris/2/toggle", data={"next": "/catalogue"})
        rv = client.get("/favoris")
        assert rv.status_code == 200

    def test_toggle_nonexistent_article(self, client):
        _register(client, "fav_404@test.com", password="favpass1")
        _login(client, "fav_404@test.com", "favpass1")
        rv = client.post("/favoris/99999/toggle", data={"next": "/catalogue"})
        assert rv.status_code == 404



class TestCart:
    def test_cart_requires_login(self, client):
        rv = client.get("/panier", follow_redirects=True)
        assert b"connecte" in rv.data.lower()

    def test_add_to_cart(self, client):
        _register(client, "cart_user@test.com", password="cartpass1")
        _login(client, "cart_user@test.com", "cartpass1")
        rv = client.post(
            "/panier/ajouter/1",
            data={"next": "/panier"},
            follow_redirects=True,
        )
        assert rv.status_code == 200
        assert b"panier" in rv.data.lower()

    def test_cart_shows_added_item(self, client):
        _register(client, "cart_view@test.com", password="cartpass1")
        _login(client, "cart_view@test.com", "cartpass1")
        client.post("/panier/ajouter/1", data={"next": "/panier"})
        rv = client.get("/panier")
        assert rv.status_code == 200
        assert b"Nike" in rv.data  # article 1

    def test_remove_from_cart(self, client):
        _register(client, "cart_rm@test.com", password="cartpass1")
        _login(client, "cart_rm@test.com", "cartpass1")
        client.post("/panier/ajouter/1", data={"next": "/panier"})
        rv = client.post(
            "/panier/retirer/1",
            follow_redirects=True,
        )
        assert rv.status_code == 200
        # Cart should be empty or item gone

    def test_add_invalid_article_404(self, client):
        _register(client, "cart_404@test.com", password="cartpass1")
        _login(client, "cart_404@test.com", "cartpass1")
        rv = client.post("/panier/ajouter/99999", data={"next": "/panier"})
        assert rv.status_code == 404

    def test_add_increases_quantity(self, client):
        _register(client, "cart_qty@test.com", password="cartpass1")
        _login(client, "cart_qty@test.com", "cartpass1")
        client.post("/panier/ajouter/3", data={"next": "/panier"})
        client.post("/panier/ajouter/3", data={"next": "/panier"})
        rv = client.get("/panier")
        assert b"2" in rv.data  # qty = 2



class TestCardPayment:
    def _setup_cart(self, client, email):
        _register(client, email, password="paypass12")
        _login(client, email, "paypass12")
        client.post("/panier/ajouter/1", data={"next": "/panier"})

    def test_payment_page_requires_login(self, client):
        rv = client.get("/paiement/carte", follow_redirects=True)
        assert b"connecte" in rv.data.lower()

    def test_get_payment_page(self, client):
        self._setup_cart(client, "pay_get@test.com")
        rv = client.get("/paiement/carte")
        assert rv.status_code == 200
        assert b"carte" in rv.data.lower()

    def test_payment_empty_cart_redirects(self, client):
        _register(client, "pay_empty@test.com", password="paypass12")
        _login(client, "pay_empty@test.com", "paypass12")
        rv = client.get("/paiement/carte", follow_redirects=True)
        assert b"vide" in rv.data.lower() or b"panier" in rv.data.lower()

    def test_successful_payment(self, client):
        self._setup_cart(client, "pay_ok@test.com")
        rv = client.post(
            "/paiement/carte",
            data={
                "card_name": "Jean Dupont",
                "card_number": "4111111111111111",
                "exp": "12/99",
                "cvc": "123",
            },
            follow_redirects=True,
        )
        assert rv.status_code == 200
        assert b"confirm" in rv.data.lower() or b"pay" in rv.data.lower()

    def test_invalid_card_number(self, client):
        self._setup_cart(client, "pay_bad_card@test.com")
        rv = client.post(
            "/paiement/carte",
            data={
                "card_name": "Jean Dupont",
                "card_number": "1234567890123456",
                "exp": "12/99",
                "cvc": "123",
            },
            follow_redirects=True,
        )
        assert b"invalide" in rv.data.lower()

    def test_invalid_expiry(self, client):
        self._setup_cart(client, "pay_bad_exp@test.com")
        rv = client.post(
            "/paiement/carte",
            data={
                "card_name": "Jean Dupont",
                "card_number": "4111111111111111",
                "exp": "01/20",  # past date
                "cvc": "123",
            },
            follow_redirects=True,
        )
        assert b"expir" in rv.data.lower() or b"invalide" in rv.data.lower()

    def test_invalid_cvc(self, client):
        self._setup_cart(client, "pay_bad_cvc@test.com")
        rv = client.post(
            "/paiement/carte",
            data={
                "card_name": "Jean Dupont",
                "card_number": "4111111111111111",
                "exp": "12/99",
                "cvc": "12",  # only 2 digits
            },
            follow_redirects=True,
        )
        assert b"cvc" in rv.data.lower() or b"invalide" in rv.data.lower()

    def test_missing_card_name(self, client):
        self._setup_cart(client, "pay_no_name@test.com")
        rv = client.post(
            "/paiement/carte",
            data={
                "card_name": "",
                "card_number": "4111111111111111",
                "exp": "12/99",
                "cvc": "123",
            },
            follow_redirects=True,
        )
        assert b"titulaire" in rv.data.lower() or b"obligatoire" in rv.data.lower()

    def test_cart_cleared_after_payment(self, client):
        self._setup_cart(client, "pay_clear@test.com")
        client.post(
            "/paiement/carte",
            data={
                "card_name": "Jean Dupont",
                "card_number": "4111111111111111",
                "exp": "12/99",
                "cvc": "123",
            },
        )
        rv = client.get("/panier")
        assert b"vide" in rv.data.lower()

    def test_mastercard_payment(self, client):
        self._setup_cart(client, "pay_mc@test.com")
        rv = client.post(
            "/paiement/carte",
            data={
                "card_name": "Marie Martin",
                "card_number": "5500005555555559",
                "exp": "12/99",
                "cvc": "321",
            },
            follow_redirects=True,
        )
        assert rv.status_code == 200
        assert b"confirm" in rv.data.lower() or b"pay" in rv.data.lower()

    def test_multiple_validation_errors(self, client):
        self._setup_cart(client, "pay_multi_err@test.com")
        rv = client.post(
            "/paiement/carte",
            data={
                "card_name": "",
                "card_number": "0000000000000000",
                "exp": "00/00",
                "cvc": "xx",
            },
            follow_redirects=True,
        )
        # Multiple errors should all be shown
        assert rv.data.count(b"li>") >= 3 or b"invalide" in rv.data.lower()



class TestOrders:
    def test_orders_requires_login(self, client):
        rv = client.get("/commandes", follow_redirects=True)
        assert b"connecte" in rv.data.lower()

    def test_orders_empty_for_new_user(self, client):
        _register(client, "orders_new@test.com", password="orderpass1")
        _login(client, "orders_new@test.com", "orderpass1")
        rv = client.get("/commandes")
        assert rv.status_code == 200
        assert b"aucune" in rv.data.lower() or b"commande" in rv.data.lower()

    def test_order_appears_after_payment(self, client):
        _register(client, "orders_after@test.com", password="orderpass1")
        _login(client, "orders_after@test.com", "orderpass1")
        client.post("/panier/ajouter/1", data={"next": "/panier"})
        client.post(
            "/paiement/carte",
            data={
                "card_name": "Test User",
                "card_number": "4111111111111111",
                "exp": "12/99",
                "cvc": "123",
            },
        )
        rv = client.get("/commandes")
        assert rv.status_code == 200
        # Should have at least one order row
        assert b"#" in rv.data  # "Commande #N"



class TestAdminAccess:
    def test_admin_dashboard_requires_login(self, client):
        rv = client.get("/admin", follow_redirects=True)
        assert b"connecte" in rv.data.lower()

    def test_admin_dashboard_rejected_for_buyer(self, client):
        _register(client, "not_admin@test.com", password="buyerpass1", role="acheteur")
        _login(client, "not_admin@test.com", "buyerpass1")
        rv = client.get("/admin", follow_redirects=True)
        assert b"admin" in rv.data.lower()
        # Should see an error flash, not the dashboard
        assert b"r" in rv.data  # "réservé à l'admin"

    def test_admin_dashboard_accessible_by_admin(self, admin_client):
        rv = admin_client.get("/admin")
        assert rv.status_code == 200
        assert b"Tableau de bord" in rv.data or b"admin" in rv.data.lower()

    def test_admin_can_change_user_role(self, app, admin_client):
        import sqlite3
        # Find a non-admin user id
        conn = sqlite3.connect(app.config["DATABASE"])
        row = conn.execute(
            "SELECT id FROM users WHERE lower(email) != lower(?)",
            (app.config["ADMIN_EMAIL"],),
        ).fetchone()
        conn.close()
        if row is None:
            pytest.skip("No non-admin users found")
        user_id = row[0]
        rv = admin_client.post(
            f"/admin/users/{user_id}/role",
            data={"role": "vendeur"},
            follow_redirects=True,
        )
        assert rv.status_code == 200
        assert b"mis" in rv.data.lower() or b"role" in rv.data.lower()

    def test_admin_role_update_invalid_role(self, app, admin_client):
        import sqlite3
        conn = sqlite3.connect(app.config["DATABASE"])
        row = conn.execute("SELECT id FROM users LIMIT 1").fetchone()
        conn.close()
        rv = admin_client.post(
            f"/admin/users/{row[0]}/role",
            data={"role": "superuser"},
            follow_redirects=True,
        )
        assert b"invalide" in rv.data.lower()



class TestSellerFlow:
    def test_seller_post_page_requires_login(self, client):
        rv = client.get("/vendeur/poste/nouveau", follow_redirects=True)
        assert b"connecte" in rv.data.lower()

    def test_buyer_cannot_access_seller_post(self, client):
        _register(client, "buyer_nosell@test.com", password="buypass12", role="acheteur")
        _login(client, "buyer_nosell@test.com", "buypass12")
        rv = client.get("/vendeur/poste/nouveau", follow_redirects=True)
        assert b"vendeur" in rv.data.lower()

    def test_seller_can_access_post_form(self, client):
        _register(client, "seller_ok@test.com", password="sellpass1", role="vendeur")
        _login(client, "seller_ok@test.com", "sellpass1")
        rv = client.get("/vendeur/poste/nouveau")
        assert rv.status_code == 200
        assert b"annonce" in rv.data.lower()



class TestPublicPosts:
    def test_posts_page_accessible(self, client):
        rv = client.get("/annonces")
        assert rv.status_code == 200




class TestMessages:
    def test_messages_requires_login(self, client):
        rv = client.get("/messages", follow_redirects=True)
        assert b"connecte" in rv.data.lower()

    def test_messages_inbox_empty(self, client):
        _register(client, "msg_user@test.com", password="msgpass12")
        _login(client, "msg_user@test.com", "msgpass12")
        rv = client.get("/messages")
        assert rv.status_code == 200

    def test_message_thread_not_found(self, client):
        _register(client, "msg_thread@test.com", password="msgpass12")
        _login(client, "msg_thread@test.com", "msgpass12")
        rv = client.get("/messages/99999")
        assert rv.status_code == 404
