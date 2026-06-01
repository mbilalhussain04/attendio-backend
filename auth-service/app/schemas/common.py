from pydantic import BaseModel
from typing import Any


class Envelope(BaseModel):
    message: str
    data: Any | None = None
