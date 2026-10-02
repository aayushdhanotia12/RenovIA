"""Request bodies. Lengths are integer millimetres; a float or a string is refused."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CountertopRunIn(Strict):
    run_id: str = Field(pattern=r"^[A-D]$")
    length_mm: StrictInt = Field(ge=300, le=12000)
    depth_mm: StrictInt = Field(default=645, ge=300, le=1000)


class SplashRunIn(Strict):
    run_id: str = Field(pattern=r"^S[1-4]$")
    length_mm: StrictInt = Field(ge=300, le=12000)
    height_mm: StrictInt = Field(default=600, ge=50, le=1500)


class MeasurementsIn(Strict):
    countertop_runs: list[CountertopRunIn] = Field(min_length=1, max_length=4)
    splash_runs: list[SplashRunIn] = Field(default_factory=list, max_length=4)
    sinks: StrictInt = Field(default=0, ge=0, le=4)
    confirmed_questions: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("countertop_runs", "splash_runs")
    @classmethod
    def unique_run_ids(cls, runs: list) -> list:
        ids = [r.run_id for r in runs]
        if len(ids) != len(set(ids)):
            raise ValueError("run ids must be unique")
        return runs


def plausibility_questions(m: MeasurementsIn) -> list[dict]:
    """Values that are possible but unusual: ask the customer, don't block (see MEASUREMENT.md)."""
    qs = []
    for r in m.countertop_runs:
        if r.length_mm > 6000:
            qs.append({"id": f"{r.run_id}-long", "field": f"countertop {r.run_id} length",
                       "message": f"{r.length_mm / 1000:.2f} m is a long countertop run. Is that right?"})
        if r.length_mm < 600:
            qs.append({"id": f"{r.run_id}-short", "field": f"countertop {r.run_id} length",
                       "message": f"{r.length_mm / 1000:.2f} m is a short countertop run. Is that right?"})
        if not 450 <= r.depth_mm <= 700:
            qs.append({"id": f"{r.run_id}-depth", "field": f"countertop {r.run_id} depth",
                       "message": f"Most countertops are 64.5 cm deep; you entered {r.depth_mm / 10:.1f} cm. Is that right?"})
    for r in m.splash_runs:
        if r.height_mm > 1200:
            qs.append({"id": f"{r.run_id}-tall", "field": f"backsplash {r.run_id} height",
                       "message": f"{r.height_mm / 10:.0f} cm is taller than one Spläsh panel (120 cm). Is that right?"})
    return [q for q in qs if q["id"] not in m.confirmed_questions]


class SurfaceIn(Strict):
    surface_id: str = Field(pattern=r"^[a-z]+_[0-9]+$")
    surface_class: Literal["countertop", "backsplash"]
    run_id: str = Field(pattern=r"^([A-D]|S[1-4])$")
    quad: list[list[StrictInt]] = Field(min_length=4, max_length=4)
    polygon: list[list[StrictInt]] | None = Field(default=None, max_length=2000)
    mask_file: str | None = Field(default=None, pattern=r"^masks/[A-Za-z0-9_]+\.png$")
    score: float | None = None

    @field_validator("quad", "polygon")
    @classmethod
    def points(cls, pts: list | None) -> list | None:
        if pts is not None and any(len(p) != 2 for p in pts):
            raise ValueError("points must be [x, y] pairs")
        return pts


class SurfacesIn(Strict):
    photo_id: str
    items: list[SurfaceIn] = Field(min_length=1, max_length=8)


class AnalyseIn(Strict):
    photo_id: str
    language: Literal["es", "en"] = "es"


StyleId = Literal["minimalista", "calido", "contraste", "creativo"]


class SuggestIn(Strict):
    style: str = Field(default="", max_length=200)
    style_id: StyleId | None = None
    budget: Literal["economy", "mid", "premium"] | None = None
    language: Literal["es", "en"] = "es"


class StyleBoardIn(Strict):
    photo_id: str
    budget: Literal["economy", "mid", "premium"] | None = None
    language: Literal["es", "en"] = "es"


class DesignIn(Strict):
    photo_id: str
    countertop_finish_id: str
    profile_id: str
    splash_finish_id: str | None = None
    fulfilment_type: Literal["SELF", "MANAGED"] = "MANAGED"
    language: Literal["es", "en"] = "es"


class BookingIn(Strict):
    design_id: str | None = None
    name: str = Field(min_length=1, max_length=120)
    phone: str = Field(min_length=6, max_length=30)
    address: str = Field(min_length=5, max_length=300)
    preferred_window: str | None = Field(default=None, max_length=60)
    fulfilment_type: Literal["SELF", "MANAGED"] = "MANAGED"
    notes: str | None = Field(default=None, max_length=500)


BookingStatus = Literal["new", "scheduled", "visited", "cancelled"]


class BookingUpdateIn(Strict):
    """What the field team edits on a visit request; every field optional."""
    status: BookingStatus | None = None
    scheduled_at: str | None = Field(default=None, max_length=40)
    assigned_to: str | None = Field(default=None, max_length=80)
    staff_notes: str | None = Field(default=None, max_length=2000)


class VisitIn(Strict):
    """The team's own measurements at the visit, in integer millimetres."""
    countertop_runs: list[CountertopRunIn] = Field(min_length=1, max_length=4)
    splash_runs: list[SplashRunIn] = Field(default_factory=list, max_length=4)
    sinks: StrictInt = Field(default=0, ge=0, le=4)
    tool: Literal["laser", "tape", "other"] = "laser"
    measured_by: str | None = Field(default=None, max_length=80)
    notes: str | None = Field(default=None, max_length=1000)
    language: Literal["es", "en"] = "es"

    @field_validator("countertop_runs", "splash_runs")
    @classmethod
    def unique_run_ids(cls, runs: list) -> list:
        ids = [r.run_id for r in runs]
        if len(ids) != len(set(ids)):
            raise ValueError("run ids must be unique")
        return runs
