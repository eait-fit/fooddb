"""SQLAdmin at /admin: the pending review queue with accept and reject actions, the label reads and brand uploads that
wait for review next to their photo, and the merge log with a split action. Accounts and purchases are read-only here. Read-only otherwise. Login takes an API key with the admin scope.
Without FOODDB__BACKEND__SECRET_KEY the admin is not served."""

import logging
import os
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse, Response
from sqladmin import Admin, BaseView, ModelView, action, expose
from sqladmin.authentication import AuthenticationBackend
from sqlalchemy import func, select
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from starlette.concurrency import run_in_threadpool

from fooddb import auth, resolve, review
from fooddb.db import account, engine, merge_log, observation, purchase
from fooddb.labels import photos


class Base(DeclarativeBase):
    pass


class Observation(Base):
    __table__ = observation


class PendingSession(Session):
    def __init__(self, bind=None, **kw):
        super().__init__(bind=bind or engine(), **kw)  # the engine needs the database URL: bind on first use


class PendingView(ModelView, model=Observation):
    identity = "observation"
    name_plural = "Pending values"
    can_create = can_edit = can_delete = False
    column_list = ["id", "food_id", "nutrient", "value_per_100", "unit", "basis", "source", "observed_at"]
    column_searchable_list = ["food_id", "nutrient"]
    column_default_sort = ("observed_at", True)

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
        for pk in filter(None, request.query_params.get("pks", "").split(",")):
            try:
                await run_in_threadpool(review.decide, int(pk), decision, request.session["key_name"])
            except (LookupError, review.NotPending):
                pass  # decided meanwhile (by an agent or a second click): the first decision stands
        return RedirectResponse(request.url_for("admin:list", identity=self.identity), status_code=302)


class MergeLog(Base):
    __table__ = merge_log


def split_merge(merge_id: int, by: str) -> None:
    """Split a logged merge's records back out of the product they are in now."""
    with engine().connect() as conn:
        row = conn.execute(select(merge_log.c.into_product, merge_log.c.food_ids)
                           .where(merge_log.c.id == merge_id, merge_log.c.kind == "merge")).first()
        if row is None:
            raise LookupError(f"merge {merge_id} not found")
        [pid] = resolve.canonical([row.into_product], conn)
    review.split(pid, row.food_ids, by, f"split of merge {merge_id}")


class MergeLogView(ModelView, model=MergeLog):
    name_plural = "Merge log"
    can_create = can_edit = can_delete = False
    column_list = ["id", "at", "kind", "from_product", "into_product", "food_ids", "probability", "by", "note"]
    column_default_sort = ("id", True)

    @action("split", "Split", "Move the records of the selected merges back out of the product they were merged into?")
    async def split(self, request: Request) -> RedirectResponse:
        for pk in filter(None, request.query_params.get("pks", "").split(",")):
            try:
                await run_in_threadpool(split_merge, int(pk), request.session["key_name"])
            except (LookupError, ValueError):
                pass  # split meanwhile, or the records moved on: nothing left to undo
        return RedirectResponse(request.url_for("admin:list", identity=self.identity), status_code=302)


class LabelView(BaseView):
    """Each label or brand record with pending values: the photo, the values read from it, and the values served now.
    SQLAdmin registers exposed methods last line first, and the last one names the menu link: `page` stays first."""

    name = "Label reads"
    icon = "fa-solid fa-camera"

    @expose("/labels", identity="labels")
    async def page(self, request: Request):
        items = await run_in_threadpool(review.queue, 100, ("label:%", "brand:%"))
        return await self.templates.TemplateResponse(request, "labels.html", {"items": items})

    @expose("/labels/photo/{sha}", identity="label-photo")
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
    name_plural = "Accounts"
    can_create = can_edit = can_delete = False
    column_list = ["id", "email", "credits", "unlimited", "created_at"]
    column_searchable_list = ["email"]
    column_default_sort = ("id", True)


class PurchaseView(ModelView, model=Purchase):
    name_plural = "Purchases"
    can_create = can_edit = can_delete = False
    column_list = ["id", "account_id", "stripe_session_id", "amount_cents", "currency", "credits", "created_at"]
    column_default_sort = ("id", True)


class KeyLogin(AuthenticationBackend):
    """The password field takes an admin-scope key. Each request checks that the key is still active."""

    async def login(self, request: Request) -> bool:
        caller = await run_in_threadpool(auth.lookup, str((await request.form()).get("password", "")))
        if caller is None or "admin" not in caller.scopes:
            return False
        request.session.update(key_id=caller.key_id, key_name=caller.name)
        return True

    async def logout(self, request: Request) -> bool:
        request.session.clear()
        return True

    async def authenticate(self, request: Request) -> bool:
        key_id = request.session.get("key_id")
        caller = key_id is not None and await run_in_threadpool(auth.by_id, key_id)
        return bool(caller) and "admin" in caller.scopes


def mount(app: FastAPI) -> None:
    secret = os.environ.get("FOODDB__BACKEND__SECRET_KEY")
    if not secret:
        logging.getLogger(__name__).warning("FOODDB__BACKEND__SECRET_KEY is unset: /admin is not served")
        return
    # The actions are GET links (SQLAdmin builds them so). A strict SameSite cookie keeps a link on
    # another site from carrying the session, so such a link cannot decide anything.
    login = KeyLogin(secret_key=secret, same_site="strict", max_age=8 * 3600)
    admin = Admin(app, session_maker=sessionmaker(class_=PendingSession), title="fooddb review",
                  authentication_backend=login, templates_dir=str(Path(__file__).parent / "templates"))
    admin.add_view(PendingView)
    admin.add_base_view(LabelView)
    admin.add_view(MergeLogView)
    admin.add_view(AccountView)
    admin.add_view(PurchaseView)
