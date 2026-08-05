#!/usr/bin/env python3
"""Create the single staff account if missing.

Password is never invented here. On create only: unusable password until
Mykola runs manage.py changepassword. Existing accounts keep their password.
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

import django

django.setup()

from django.contrib.auth import get_user_model

User = get_user_model()
email = os.environ.get("DJANGO_SUPERUSER_EMAIL", "mykola@apidiscoverysolution.uk")
username = "mykola"
u, created = User.objects.get_or_create(
    username=username,
    defaults={"email": email, "is_staff": True, "is_superuser": True},
)
if created:
    u.set_unusable_password()
    u.save()
else:
    changed = False
    if u.email != email:
        u.email = email
        changed = True
    if not u.is_staff:
        u.is_staff = True
        changed = True
    if not u.is_superuser:
        u.is_superuser = True
        changed = True
    if changed:
        u.save()
print(
    f"user={u.username} email={u.email} created={created} "
    f"has_usable_password={u.has_usable_password()}"
)
