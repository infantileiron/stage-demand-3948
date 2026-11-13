from pydantic import BaseModel, Field

class MergeCreate(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    plan_ids: list[int] = Field(min_length=2, max_length=3, description="同一日期范围内每厅一份已完成预演的编排ID")
    daily_capacity: int = Field(ge=2, le=200, description="每日三厅合计可用引导员人数")
