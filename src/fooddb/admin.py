"""SQLAdmin at /admin: the pending review queue, read-only, with accept and reject actions."""

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from sqladmin import Admin, ModelView, action
from sqlalchemy import func, select
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from starlette.concurrency import run_in_threadpool

from fooddb import review
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
                await run_in_threadpool(review.decide, int(pk), decision, "admin")
            except (LookupError, review.NotPending):
                pass  # decided meanwhile (by an agent or a second click): the first decision stands
        return RedirectResponse(request.url_for("admin:list", identity=self.identity), status_code=302)


def mount(app: FastAPI) -> None:
    admin = Admin(app, session_maker=sessionmaker(class_=PendingSession), title="fooddb review")
    admin.add_view(PendingView)
