"""Request models shared by route groups."""

from pydantic import BaseModel, StrictBool


class PublishedIn(BaseModel):
    value: StrictBool  # JSON true / false only
