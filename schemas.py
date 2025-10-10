from pydantic import BaseModel, Field, HttpUrl
from typing import List


class VideoSceneSplitRequest(BaseModel):
    """
    视频场景分割请求参数模型
    
    包含用户API密钥、视频文件URL和场景切分灵敏度参数
    """
    apiKey: str = Field(description="用户API密钥，用于身份验证和费用统计")
    
    video_url: HttpUrl = Field(description="需要分割的视频文件URL地址，支持HTTP/HTTPS协议")
    
    threshold: int = Field(
        default=27, 
        ge=1, 
        le=254, 
        description="场景分割阈值，调节切分的灵敏度，值越小越灵敏，取值范围(1, 254)"
    )


class VideoSceneSplitResponse(BaseModel):
    """
    视频场景分割响应参数模型
    
    返回分割后的视频片段下载链接列表
    """
    scene_list: List[str] = Field(
        default=[], 
        description="分割后的视频场景片段下载链接列表，按时间顺序排列"
    )
