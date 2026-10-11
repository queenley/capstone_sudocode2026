from pydantic import Field
from .catalog import StrictModel

class CustomerReply(StrictModel):
    text: str = Field(min_length=1, max_length=600)
