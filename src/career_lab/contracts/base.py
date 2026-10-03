from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

Identifier = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
NonNegativeInt = Annotated[int, Field(ge=0, strict=True)]
PositiveInt = Annotated[int, Field(gt=0, strict=True)]


class Contract(BaseModel):
    # Reject accidental metadata (particularly gold) at every typed boundary.
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

