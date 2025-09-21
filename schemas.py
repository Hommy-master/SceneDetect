from pydantic import BaseModel, Field


class VideoSceneSplitRequest(BaseModel):
    """视频场景分割请求参数"""
    video_url: str = Field(default="", description="视频文件URL")

class VideoSceneSplitResponse(BaseModel):
    """视频场景分割响应参数"""
    scene_list: list = Field(default=[], description="视频场景列表")
