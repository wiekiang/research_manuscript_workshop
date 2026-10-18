"""Import every model module so Alembic and the RLS helper see the full metadata."""

from . import (  # noqa: F401
    cfp,
    contribution,
    core,
    experiment,
    latex,
    literature,
    manuscript,
    review,
    submission,
    synthesis,
)
