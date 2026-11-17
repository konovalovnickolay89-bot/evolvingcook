from django.contrib import admin
from django.urls import path

from api.api import api
from assist.views import agent_events, intelligence_assign

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/v1/", api.urls),
    # Internal — NOT on /api/v1. direct_loopback_or_response rejects the
    # Cloudflare tunnel (it dials 127.0.0.1 and sets CF-* / forwarded headers).
    # intelligence/assign also requires X-Internal-Token.
    path("api/internal/agent-events", agent_events, name="agent-events"),
    path(
        "api/internal/intelligence/assign",
        intelligence_assign,
        name="intelligence-assign",
    ),
]
