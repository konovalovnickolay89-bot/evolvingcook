"""Login rate limits (per IP and per username) and token expiry."""
from __future__ import annotations

import os
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import Client, TestCase, override_settings

from api.auth import issue_token, user_from_token
from config.settings import env_int

LOC_MEM = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "auth-hardening-tests",
    }
}


@override_settings(CACHES=LOC_MEM)
class LoginRateLimitTests(TestCase):
    def setUp(self):
        self.client = Client()
        get_user_model().objects.create_user(
            "chef", "chef@kitchen.test", "correct-horse-battery"
        )

    def _login(self, email: str, *, cf: str | None = None, xff: str | None = None, password: str = "nope"):
        extra = {}
        if cf is not None:
            extra["HTTP_CF_CONNECTING_IP"] = cf
        if xff is not None:
            extra["HTTP_X_FORWARDED_FOR"] = xff
        return self.client.post(
            "/api/v1/auth/login",
            data={"email": email, "password": password},
            content_type="application/json",
            **extra,
        )

    @override_settings(AUTH_LOGIN_RATELIMIT="2/m", AUTH_LOGIN_USERNAME_RATELIMIT="100/m")
    def test_per_ip_limit_ignores_forwarded_for(self):
        cache.clear()
        codes = [
            self._login(f"a{i}@kitchen.test", xff=f"198.51.100.{i}").status_code
            for i in range(1, 4)
        ]
        self.assertEqual(codes, [401, 401, 429])

    @override_settings(AUTH_LOGIN_RATELIMIT="2/m", AUTH_LOGIN_USERNAME_RATELIMIT="100/m")
    def test_cf_connecting_ip_is_the_ip_bucket(self):
        cache.clear()
        codes = [
            self._login(f"b{i}@kitchen.test", cf=f"198.51.100.{i}").status_code
            for i in range(1, 4)
        ]
        self.assertEqual(codes, [401, 401, 401])

    @override_settings(AUTH_LOGIN_RATELIMIT="100/m", AUTH_LOGIN_USERNAME_RATELIMIT="2/m")
    def test_per_username_limit_across_ips_and_case(self):
        cache.clear()
        first = self._login("Chef@Kitchen.test", cf="198.51.100.1")
        second = self._login("chef@kitchen.test", cf="198.51.100.2")
        third = self._login("CHEF@kitchen.test", cf="198.51.100.3")
        self.assertEqual(
            [first.status_code, second.status_code, third.status_code],
            [401, 401, 429],
        )
        self.assertEqual(third.json()["code"], "rate_limited")

    @override_settings(
        AUTH_LOGIN_RATELIMIT="100/m",
        AUTH_LOGIN_USERNAME_RATELIMIT="100/m",
        AUTH_TOKEN_MAX_AGE=43200,
    )
    def test_login_returns_configured_expiry(self):
        cache.clear()
        res = self._login("chef@kitchen.test", password="correct-horse-battery")
        self.assertEqual(res.status_code, 200, res.content)
        body = res.json()
        self.assertEqual(body["expires_in"], 43200)
        self.assertEqual(body["token_type"], "Bearer")
        self.assertTrue(body["access_token"])


class TokenExpiryTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            "chef", "chef@kitchen.test", "correct-horse-battery"
        )
        self.client = Client()

    @override_settings(AUTH_TOKEN_MAX_AGE=100)
    def test_token_rejected_after_max_age(self):
        issued_at = 1_700_000_000
        with patch("django.core.signing.time.time", return_value=issued_at):
            token = issue_token(self.user)
        with patch("django.core.signing.time.time", return_value=issued_at + 50):
            self.assertIsNotNone(user_from_token(token))
        with patch("django.core.signing.time.time", return_value=issued_at + 101):
            self.assertIsNone(user_from_token(token))
            res = self.client.post(
                "/api/v1/auth/refresh",
                data={"access_token": token},
                content_type="application/json",
            )
        self.assertEqual(res.status_code, 401)
        self.assertEqual(res.json()["code"], "token_expired_or_invalid")

    def test_env_int_default_and_reject(self):
        self.assertEqual(env_int("EC_TEST_TOKEN_AGE_UNSET", 30), 30)
        with patch.dict(os.environ, {"EC_TEST_TOKEN_AGE": "12"}):
            self.assertEqual(env_int("EC_TEST_TOKEN_AGE", 30), 12)
        with patch.dict(os.environ, {"EC_TEST_TOKEN_AGE": "0"}):
            with self.assertRaises(RuntimeError):
                env_int("EC_TEST_TOKEN_AGE", 30)
        with patch.dict(os.environ, {"EC_TEST_TOKEN_AGE": "soon"}):
            with self.assertRaises(RuntimeError):
                env_int("EC_TEST_TOKEN_AGE", 30)
