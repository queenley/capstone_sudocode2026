from pydantic import Field
from .catalog import StrictModel

class CustomerReply(StrictModel):
    """Câu khách nói tiếp theo, do simulator viết lại từ dàn ý."""

    text: str = Field(min_length=1, max_length=600,
                      description="Một câu nói ngắn tự nhiên bằng tiếng Việt, không thêm thông tin ngoài dàn ý")
