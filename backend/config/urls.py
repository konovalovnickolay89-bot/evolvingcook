from django.contrib import admin
from django.urls import path

from api.api import api
from assist.views import agent_events

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/v1/", api.urls),
    # D11 internal — NOT on /api/v1 (tunnel must not expose agent-events)
    path("api/internal/agent-events", agent_events, name="agent-events"),
]
