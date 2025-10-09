from pydantic import BaseModel, Field, HttpUrl


class VideoSceneSplitRequest(BaseModel):
    """视频场景分割请求参数"""
    apiKey: str = Field(description="API Key")
    video_url: HttpUrl = Field(description="视频文件URL")
    threshold: int = Field(default=27, ge=1, le=254, description="场景分割阈值，调节切分的灵敏度，值越小越灵敏，取值范围(0, 255)")

class VideoSceneSplitResponse(BaseModel):
    """视频场景分割响应参数"""
    scene_list: list = Field(default=[], description="视频场景列表")
