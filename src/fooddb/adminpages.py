"""The admin panel pages next to the SQLAdmin model views: Overview, Jobs, Requests and Users. Each page is server-rendered.
The actions are POST forms, because SQLAdmin builds its own actions as GET links. Each form carries the CSRF token of the
admin session (a random value in the signed session cookie), and each action records the admin key's name.
SQLAdmin registers exposed methods last line first, and the last one names the menu link: `page` stays first."""

import hmac
import secrets

from sqladmin import BaseView, Flash, expose
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import RedirectResponse, Response

from fooddb import ops


def _csrf(request: Request) -> str:
    return request.session.setdefault("csrf", secrets.token_urlsafe(24))


async def _render(view: BaseView, request: Request, template: str, data: dict, subtitle: str = ""):
    return await view.templates.TemplateResponse(request, template, {"csrf": _csrf(request), "title": view.name, "subtitle": subtitle} | data)


async def _form(request: Request) -> dict | None:
    """The posted fields, or None when the CSRF token is not the session's own."""
    form = await request.form()
    want = request.session.get("csrf", "")
    return dict(form) if want and hmac.compare_digest(str(form.get("csrf", "")).encode(), want.encode()) else None


EXPIRED = Response("form expired: go back, reload the page and try again", status_code=403)


def _back(request: Request, page: str, message: str, ok: bool = True) -> RedirectResponse:
    (Flash.success if ok else Flash.error)(request, message)
    return RedirectResponse(str(request.url_for(f"admin:view-{page}")), status_code=303)


def _int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


class OverviewView(BaseView):
    name = "Overview"
    icon = "fa-solid fa-gauge"

    @expose("/overview", identity="overview")
    async def page(self, request: Request):
        return await _render(self, request, "admin_overview.html", await run_in_threadpool(ops.overview), "The platform at a glance")


class JobsView(BaseView):
    name = "Jobs"
    category = "Platform"
    icon = "fa-solid fa-list-check"

    @expose("/jobs", identity="jobs")
    async def page(self, request: Request):
        return await _render(self, request, "admin_jobs.html", await run_in_threadpool(ops.jobs_report), "Fetchers, the queue, schedules and fetch runs")

    @expose("/jobs/run", methods=["POST"], identity="jobs-run")
    async def run(self, request: Request):
        if (form := await _form(request)) is None:
            return EXPIRED
        fetcher = str(form.get("fetcher", ""))
        try:
            task = await run_in_threadpool(ops.run_now, fetcher, request.session["key_name"])
        except ValueError as e:
            return _back(request, "jobs", str(e), ok=False)
        if task is None:
            return _back(request, "jobs", f"{fetcher} already waits in the queue", ok=False)
        return _back(request, "jobs", f"queued {fetcher} as task {task}")


class RequestsView(BaseView):
    name = "Requests"
    category = "Platform"
    icon = "fa-solid fa-chart-column"

    @expose("/requests", identity="requests")
    async def page(self, request: Request):
        data = await run_in_threadpool(ops.requests_report, _int(request.query_params.get("hours"), 24))
        return await _render(self, request, "admin_requests.html", data, "API traffic from the request log")


class UsersView(BaseView):
    name = "Users"
    category = "Customers"
    icon = "fa-solid fa-users"

    @expose("/users", identity="users")
    async def page(self, request: Request):
        return await _render(self, request, "admin_users.html", await run_in_threadpool(ops.users_report, request.query_params.get("q", "")),
                              "Accounts, credits and API keys")

    @expose("/users/{account_id:int}/grant", methods=["POST"], identity="users-grant")
    async def grant(self, request: Request):
        if (form := await _form(request)) is None:
            return EXPIRED
        try:
            balance = await run_in_threadpool(ops.grant_credits, request.path_params["account_id"], _int(form.get("credits")),
                                              request.session["key_name"])
        except (ValueError, LookupError) as e:
            return _back(request, "users", str(e), ok=False)
        return _back(request, "users", f"credits granted, balance {balance}")

    @expose("/users/{account_id:int}/unlimited", methods=["POST"], identity="users-unlimited")
    async def unlimited(self, request: Request):
        if (form := await _form(request)) is None:
            return EXPIRED
        try:
            await run_in_threadpool(ops.set_unlimited, request.path_params["account_id"], form.get("on") == "1",
                                    request.session["key_name"])
        except LookupError as e:
            return _back(request, "users", str(e), ok=False)
        return _back(request, "users", "unlimited " + ("on" if form.get("on") == "1" else "off"))

    @expose("/keys/{key_id:int}/revoke", methods=["POST"], identity="users-revoke")
    async def revoke(self, request: Request):
        if (form := await _form(request)) is None:
            return EXPIRED
        key_id = request.path_params["key_id"]
        if key_id == request.session.get("key_id"):
            return _back(request, "users", "that is the key of this session: revoke it from the CLI", ok=False)
        name = await run_in_threadpool(ops.revoke_key, key_id, request.session["key_name"])
        return _back(request, "users", f"revoked {name}" if name else "no such active key", ok=name is not None)
