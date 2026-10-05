"""SQLAdmin at /admin: the pending review queue, read-only, with accept and reject actions.
Login takes an API key with the admin scope. Without FOODDB__BACKEND__SECRET_KEY the admin is not served."""

import logging
import os

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from sqladmin import Admin, ModelView, action
from sqladmin.authentication import AuthenticationBackend
from sqlalchemy import func, select
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from starlette.concurrency import run_in_threadpool

from fooddb import auth, review
from fooddb.db import engine, observation


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
                  authentication_backend=login)
    admin.add_view(PendingView)
