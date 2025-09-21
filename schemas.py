from pydantic import BaseModel, Field, HttpUrl


class VideoSceneSplitRequest(BaseModel):
    """视频场景分割请求参数"""
    video_url: HttpUrl = Field(description="视频文件URL")
    min_scene_length: float = Field(default=2, description="最小场景长度，单位：秒")

class VideoSceneSplitResponse(BaseModel):
    """视频场景分割响应参数"""
    scene_list: list = Field(default=[], description="视频场景列表")
