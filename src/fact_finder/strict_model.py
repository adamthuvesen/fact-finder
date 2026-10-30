from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class StrictModel(BaseModel):
    """The one Pydantic base. Unknown fields in any artifact fail loudly."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
