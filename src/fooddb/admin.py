"""SQLAdmin at /admin: the pending review queue with accept and reject actions (also on each row), the Review page with one
card per food record that has pending values (failed checks explained, all latest values, the photo of a label or brand
record), and the merge log with a split action. Accounts and purchases are read-only here. Every list has filters, search
and sortable columns. The menu has three sections: Review, Platform and Customers. `templates/sqladmin/base.html` adds the
admin's CSS and JS to every page, and `sqladmin/login.html` takes the key.
The Overview, Jobs, Requests and Users pages (adminpages.py) show the platform and run its few actions. Login takes an
API key with the admin scope. Without FOODDB__BACKEND__SECRET_KEY the admin is not served."""

import logging
import os
import posixpath
import secrets
from pathlib import Path
from urllib.parse import quote, urlencode, urlsplit

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse, Response
from markupsafe import Markup
from sqladmin import Admin, BaseView, Flash, ModelView, action, expose
from sqladmin.authentication import AuthenticationBackend, login_required
from sqladmin.filters import AllUniqueStringValuesFilter, BooleanFilter, StaticValuesFilter, get_column_obj
from sqlalchemy import func, select
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from starlette.concurrency import run_in_threadpool

from fooddb import adminpages, auth, checks, export, ops, resolve, review
from fooddb.db import account, engine, food, merge_log, observation, purchase
from fooddb.labels import photos


class Base(DeclarativeBase):
    pass


class Observation(Base):
    __table__ = observation

    @property
    def decide(self) -> int:
        return self.id


class PendingSession(Session):
    def __init__(self, bind=None, **kw):
        super().__init__(bind=bind or engine(), **kw)  # the engine needs the database URL: bind on first use


def when(value) -> str:
    return value.strftime("%Y-%m-%d %H:%M") if value else "-"


class PendingOnly(AllUniqueStringValuesFilter):
    """The distinct values among the pending rows only: the table holds every observation ever made."""

    async def lookups(self, request, model, run_query):
        column = get_column_obj(self.column, model)
        rows = await run_query(select(column).where(model.status == "pending").distinct().order_by(column))
        return [("__all", "All")] + [(v[0], v[0]) for v in rows]


def decision_buttons(row, attr, request: Request) -> Markup:
    here = quote(request.url.path + (f"?{request.url.query}" if request.url.query else ""), safe="")
    link = lambda name, cls, label: Markup('<a class="btn btn-sm {}" href="{}?pks={}&next={}">{}</a>').format(
        cls, request.url_for(f"admin:action-observation-{name}"), row.id, here, label)
    return Markup('<span class="row-actions">{} {}</span>').format(link("accept", "btn-success", "Accept"),
                                                                   link("reject", "btn-outline-danger", "Reject"))


class PendingView(ModelView, model=Observation):
    identity = "observation"
    name = "Pending value"
    name_plural = "Pending values"
    category = "Review"
    icon = "fa-solid fa-hourglass-half"
    can_create = can_edit = can_delete = False
    column_list = ["id", "food_id", "nutrient", "value_per_100", "source", "observed_at", "decide"]
    column_labels = {"food_id": "Record", "value_per_100": "Value", "observed_at": "Observed", "decide": "Decision"}
    column_searchable_list = ["food_id", "nutrient", "source"]
    column_sortable_list = ["id", "food_id", "nutrient", "value_per_100", "source", "observed_at"]
    column_filters = [PendingOnly(Observation.source), PendingOnly(Observation.nutrient), PendingOnly(Observation.basis)]
    column_default_sort = ("observed_at", True)
    column_export_exclude_list = ["decide"]
    column_formatters = {Observation.value_per_100: lambda m, a: "withdrawn" if m.value_per_100 is None else f"{float(m.value_per_100):.6g} {m.unit}/{m.basis}",
                         Observation.observed_at: lambda m, a: m.observed_at.strftime("%Y-%m-%d"), "decide": decision_buttons}
    column_details_list = ["id", "food_id", "nutrient", "value_per_100", "unit", "basis", "status", "source", "licence", "observed_at",
                           "ingested_at", "evidence"]
    column_formatters_detail = {Observation.observed_at: lambda m, a: when(m.observed_at),
                                Observation.ingested_at: lambda m, a: when(m.ingested_at)}
    page_size = 25
    page_size_options = [25, 50, 100, 200]

    def list_query(self, request: Request):
        return select(Observation).where(Observation.status == "pending")

    def count_query(self, request: Request):
        return select(func.count()).select_from(Observation).where(Observation.status == "pending")

    @action("accept", "Accept", "Serve the selected values from the next snapshot on?")
    async def accept(self, request: Request):
        return await self._decide(request, "accept")

    @action("reject", "Reject", "Never serve the selected values?")
    async def reject(self, request: Request):
        return await self._decide(request, "reject")

    async def _decide(self, request: Request, decision) -> RedirectResponse:
        decided = []
        for pk in filter(None, request.query_params.get("pks", "").split(",")):
            try:
                decided.append((await run_in_threadpool(review.decide, int(pk), decision, request.session["key_name"]))["id"])
            except (LookupError, review.NotPending):
                pass  # decided meanwhile (by an agent or a second click): the first decision stands
        if decided:
            flash_decided(request, review.STATUS[decision].capitalize(), await run_in_threadpool(describe, decided), decided)
        else:
            Flash.warning(request, "Nothing to decide: already decided")
        return RedirectResponse(back_to(request, str(request.url_for("admin:list", identity=self.identity))),
                                status_code=302)


def describe(ids: list[int]) -> str:
    """What the given values are, for a toast: the value and record name when it is one value of one record."""
    o = observation.c
    with engine().connect() as conn:
        rows = conn.execute(select(o.nutrient, o.value_per_100, o.unit, o.basis, food.c.name, food.c.id)
                            .join_from(observation, food).where(o.id.in_(ids))).all()
    records = {r.id: r.name or r.id for r in rows}
    what = (f"{rows[0].nutrient} " + ("withdrawn" if rows[0].value_per_100 is None else f"{checks.short(float(rows[0].value_per_100))} {rows[0].unit}/{rows[0].basis}")
            if len(rows) == 1 else f"{len(rows)} values")
    return what + " \u00b7 " + (next(iter(records.values())) if len(records) == 1 else f"{len(records)} records")


def flash_decided(request: Request, verb: str, what: str, ids: list[int]) -> None:
    """A toast with an Undo button: `templates/sqladmin/flash.html` posts the ids to the Review page's undo."""
    Flash.success(request, f"{verb} {what}")
    request.session["_messages"][-1]["undo"] = ",".join(map(str, ids))


def undo_decisions(ids: list[int], by: str) -> int:
    with engine().begin() as conn:
        n = review.undo(ids, by, conn)
        if n:
            ops.audit(conn, by, "review-undo", {"observations": ids, "reverted": n})
    return n


def back_to(request: Request, default: str) -> str:
    """The `next` query parameter when it is a path under the admin mount, else `default`: a redirect stays in the app."""
    nxt = urlsplit(request.query_params.get("next", ""))
    path = posixpath.normpath(nxt.path)
    mount = urlsplit(str(request.url_for("admin:index"))).path
    if nxt.scheme or nxt.netloc or "\\" in nxt.path or not f"{path}/".startswith(mount):
        return default
    return path + (f"?{nxt.query}" if nxt.query else "")


class MergeLog(Base):
    __table__ = merge_log

    @property
    def undo(self) -> int:
        return self.id


def split_merge(merge_id: int, by: str) -> None:
    """Split a logged merge's records back out of the product they are in now."""
    with engine().connect() as conn:
        row = conn.execute(select(merge_log.c.into_product, merge_log.c.food_ids)
                           .where(merge_log.c.id == merge_id, merge_log.c.kind == "merge")).first()
        if row is None:
            raise LookupError(f"merge {merge_id} not found")
        [pid] = resolve.canonical([row.into_product], conn)
    review.split(pid, row.food_ids, by, f"split of merge {merge_id}")


def records(row, attr) -> Markup:
    ids = row.food_ids or []
    return Markup('<span class="clip" title="{}">{}</span>').format(", ".join(ids), ", ".join(ids[:2]) + (f" +{len(ids) - 2}" if len(ids) > 2 else ""))


def split_button(row, attr, request: Request) -> Markup:
    if row.kind != "merge":
        return Markup("")
    return Markup('<a class="btn btn-sm btn-outline-danger" href="{}?pks={}">Split</a>').format(
        request.url_for("admin:action-merge-log-split"), row.id)


class MergeLogView(ModelView, model=MergeLog):
    name = "Merge"
    name_plural = "Merge log"
    category = "Review"
    icon = "fa-solid fa-code-merge"
    can_create = can_edit = can_delete = False
    column_list = ["id", "at", "kind", "from_product", "into_product", "food_ids", "probability", "by", "note", "undo"]
    column_labels = {"at": "When (UTC)", "from_product": "From product", "into_product": "Into product", "food_ids": "Records",
                     "by": "By", "undo": ""}
    column_searchable_list = ["by", "note"]
    column_sortable_list = ["id", "at", "kind", "from_product", "into_product", "probability", "by"]
    column_filters = [StaticValuesFilter(MergeLog.kind, [("merge", "merge"), ("split", "split")], title="Kind")]
    column_default_sort = ("id", True)
    column_export_exclude_list = ["undo"]
    column_formatters = {MergeLog.at: lambda m, a: when(m.at), MergeLog.food_ids: records, "undo": split_button,
                         MergeLog.probability: lambda m, a: "-" if m.probability is None else f"{m.probability:.3f}"}
    column_formatters_detail = {MergeLog.at: lambda m, a: when(m.at), MergeLog.food_ids: lambda m, a: ", ".join(m.food_ids or ())}
    page_size = 25

    @action("split", "Split", "Move the records of the selected merges back out of the product they were merged into?")
    async def split(self, request: Request) -> RedirectResponse:
        for pk in filter(None, request.query_params.get("pks", "").split(",")):
            try:
                await run_in_threadpool(split_merge, int(pk), request.session["key_name"])
            except (LookupError, ValueError):
                pass  # split meanwhile, or the records moved on: nothing left to undo
        return RedirectResponse(request.url_for("admin:list", identity=self.identity), status_code=302)


PAGE_SIZE = 25


class ReviewView(BaseView):
    """Each food record with pending values: why its checks failed, all its latest values next to the values served now,
    and the photo of a label or brand record. Filters: `check`, `source`; paging: `offset`.
    SQLAdmin registers exposed methods last line first, and the last one names the menu link: `page` stays first."""

    name = "Review"
    category = "Review"
    icon = "fa-solid fa-clipboard-check"

    @expose("/review", identity="review")
    async def page(self, request: Request):
        q = request.query_params
        check, source = q.get("check") or None, q.get("source") or None
        offset = int(q["offset"]) if q.get("offset", "").isdigit() else 0
        items = await run_in_threadpool(lambda: review.queue(PAGE_SIZE, offset=offset, check=check, source=source, detail=True))
        facets = await run_in_threadpool(review.facets, ("%",), check, source)
        days = await run_in_threadpool(export.days)
        page = lambda off: "?" + urlencode({k: v for k, v in (("check", check), ("source", source), ("offset", off)) if v})
        return await self.templates.TemplateResponse(request, "review.html", {
            "title": "Review", "subtitle": "One card per food record with pending values", "items": items, "facets": facets, "snapshot_day": days[0]["day"] if days else None, "check": check, "source": source, "offset": offset,
            "back": request.url.path + (f"?{request.url.query}" if request.url.query else ""),
            "prev": page(max(offset - PAGE_SIZE, 0)) if offset else None,
            "next": page(offset + PAGE_SIZE) if offset + PAGE_SIZE < facets["total"] else None,
            "first": offset + 1, "last": offset + len(items)})

    @expose("/review/undo", methods=["POST"], identity="review-undo")
    async def undo(self, request: Request):
        if (form := await adminpages._form(request)) is None:
            return adminpages.EXPIRED
        ids = [int(i) for i in str(form.get("ids", "")).split(",") if i.isdigit()]
        n = await run_in_threadpool(undo_decisions, ids, request.session["key_name"])
        Flash.success(request, f"Undone: {n} values back to pending")
        return RedirectResponse(back_to(request, str(request.url_for("admin:view-review"))), status_code=303)

    @expose("/review/photo/{sha}", identity="review-photo")
    async def label_photo(self, request: Request) -> Response:
        try:
            data = await run_in_threadpool(photos.load, request.path_params["sha"])
        except LookupError:
            return Response("no such photo", status_code=404)
        return Response(data, media_type=photos.sniff(data),
                        headers={"Cache-Control": "private, max-age=86400", "X-Content-Type-Options": "nosniff"})


class Account(Base):
    __table__ = account


class Purchase(Base):
    __table__ = purchase


class AccountView(ModelView, model=Account):
    name = "Account"
    name_plural = "Accounts"
    category = "Customers"
    icon = "fa-solid fa-address-book"
    can_create = can_edit = can_delete = False
    column_list = ["id", "email", "credits", "unlimited", "created_at"]
    column_labels = {"created_at": "Created (UTC)"}
    column_searchable_list = ["email"]
    column_sortable_list = ["id", "email", "credits", "unlimited", "created_at"]
    column_filters = [BooleanFilter(Account.unlimited, title="Unlimited")]
    column_default_sort = ("id", True)
    column_formatters = {Account.credits: lambda m, a: f"{m.credits:,}", Account.created_at: lambda m, a: when(m.created_at),
                         Account.unlimited: lambda m, a: Markup('<span class="badge bg-blue-lt">unlimited</span>') if m.unlimited else "no"}
    column_formatters_detail = {Account.created_at: lambda m, a: when(m.created_at)}
    page_size = 25


class PurchaseView(ModelView, model=Purchase):
    name = "Purchase"
    name_plural = "Purchases"
    category = "Customers"
    icon = "fa-solid fa-receipt"
    can_create = can_edit = can_delete = False
    column_list = ["id", "account_id", "stripe_session_id", "amount_cents", "credits", "created_at"]
    column_labels = {"account_id": "Account", "stripe_session_id": "Stripe session", "amount_cents": "Amount", "created_at": "When (UTC)"}
    column_searchable_list = ["stripe_session_id"]
    column_sortable_list = ["id", "account_id", "amount_cents", "credits", "created_at"]
    column_filters = [AllUniqueStringValuesFilter(Purchase.currency, title="Currency")]
    column_default_sort = ("id", True)
    column_formatters = {Purchase.amount_cents: lambda m, a: f"{m.currency.upper()} {m.amount_cents / 100:.2f}",
                         Purchase.credits: lambda m, a: f"{m.credits:,}", Purchase.created_at: lambda m, a: when(m.created_at)}
    column_formatters_detail = {Purchase.created_at: lambda m, a: when(m.created_at)}
    page_size = 25


class KeyLogin(AuthenticationBackend):
    """The password field takes an admin-scope key. Each request checks that the key is still active."""

    async def login(self, request: Request) -> bool:
        caller = await run_in_threadpool(auth.lookup, str((await request.form()).get("password", "")))
        if caller is None or "admin" not in caller.scopes:
            return False
        request.session.update(key_id=caller.key_id, key_name=caller.name, csrf=secrets.token_urlsafe(24))
        return True

    async def logout(self, request: Request) -> bool:
        request.session.clear()
        return True

    async def authenticate(self, request: Request) -> bool:
        key_id = request.session.get("key_id")
        caller = key_id is not None and await run_in_threadpool(auth.by_id, key_id)
        return bool(caller) and "admin" in caller.scopes


class FooddbAdmin(Admin):
    @login_required
    async def index(self, request: Request) -> Response:
        """The landing page is the Overview dashboard."""
        return RedirectResponse(request.url_for("admin:view-overview"), status_code=302)


def mount(app: FastAPI) -> None:
    secret = os.environ.get("FOODDB__BACKEND__SECRET_KEY")
    if not secret:
        logging.getLogger(__name__).warning("FOODDB__BACKEND__SECRET_KEY is unset: /admin is not served")
        return
    # The actions are GET links (SQLAdmin builds them so). A strict SameSite cookie keeps a link on
    # another site from carrying the session, so such a link cannot decide anything.
    login = KeyLogin(secret_key=secret, same_site="strict", max_age=8 * 3600)
    admin = FooddbAdmin(app, session_maker=sessionmaker(class_=PendingSession), title="fooddb admin",
                  authentication_backend=login, templates_dir=str(Path(__file__).parent / "templates"))
    admin.templates.env.filters["short"] = checks.short
    admin.add_base_view(adminpages.OverviewView)
    admin.add_base_view(ReviewView)
    admin.add_view(PendingView)
    admin.add_view(MergeLogView)
    admin.add_base_view(adminpages.JobsView)
    admin.add_base_view(adminpages.RequestsView)
    admin.add_base_view(adminpages.UsersView)
    admin.add_view(AccountView)
    admin.add_view(PurchaseView)
