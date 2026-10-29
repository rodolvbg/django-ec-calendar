"""Unfold's sidebar: a model's list and its calendar, each marked active on
its own page (the calendar's URL is under the list's, which Unfold would
mark active on both)::

    from django_ec_calendar.unfold import calendar_navigation

    UNFOLD = {
        "SIDEBAR": {
            "navigation": [
                {"title": "Agenda", "items": calendar_navigation("agenda.Booking")},
            ],
        },
    }
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from django.apps import apps
from django.urls import reverse, reverse_lazy
from django.utils.functional import lazy
from django.utils.text import capfirst
from django.utils.translation import gettext_lazy

if TYPE_CHECKING:
    from collections.abc import Callable

    from django.http import HttpRequest


def _names(model: str, site: str) -> tuple[str, str, str, str]:
    app_label, model_name = model.lower().split(".")
    prefix = f"{site}:{app_label}_{model_name}"
    return app_label, model_name, f"{prefix}_changelist", f"{prefix}_calendar"


def _may_view(app_label: str, model_name: str) -> Callable[[HttpRequest], bool]:
    def permission(request: HttpRequest) -> bool:
        user = request.user
        return user.has_perm(f"{app_label}.view_{model_name}") or user.has_perm(
            f"{app_label}.change_{model_name}"
        )

    return permission


def calendar_item(
    model: str,
    *,
    site: str = "admin",
    title: Any = None,
    icon: str = "calendar_month",
) -> dict[str, Any]:
    """The sidebar's item of ``model``'s calendar (``"app_label.Model"``),
    active on its page; for those who may view or change its objects."""
    app_label, model_name, _, calendar = _names(model, site)
    return {
        "title": title or gettext_lazy("Calendar"),
        "icon": icon,
        "link": reverse_lazy(calendar),
        "active": lambda request: request.path.startswith(reverse(calendar)),
        "permission": _may_view(app_label, model_name),
    }


def changelist_item(
    model: str,
    *,
    site: str = "admin",
    title: Any = None,
    icon: str = "list",
) -> dict[str, Any]:
    """The sidebar's item of ``model``'s list (``"app_label.Model"``,
    titled by its plural name), active on its pages but the calendar's."""
    app_label, model_name, changelist, calendar = _names(model, site)

    def plural() -> str:
        opts = apps.get_model(app_label, model_name)._meta
        return capfirst(str(opts.verbose_name_plural))

    return {
        "title": title or lazy(plural, str)(),
        "icon": icon,
        "link": reverse_lazy(changelist),
        "active": lambda request: (
            request.path.startswith(reverse(changelist))
            and not request.path.startswith(reverse(calendar))
        ),
        "permission": _may_view(app_label, model_name),
    }


def calendar_navigation(
    model: str, *, site: str = "admin", **titles: Any
) -> list[dict[str, Any]]:
    """Both: ``model``'s list and its calendar (``list_title``,
    ``calendar_title``)."""
    return [
        changelist_item(model, site=site, title=titles.get("list_title")),
        calendar_item(model, site=site, title=titles.get("calendar_title")),
    ]
