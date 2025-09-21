from fastapi import APIRouter, Request
from logger import logger
import schemas
import service


router = APIRouter(prefix="/v1", tags=["v1"])

@router.post("/video/scene-split", response_model=schemas.VideoSceneSplitResponse)
def video_scene_split(video: schemas.VideoSceneSplitRequest):
    """
    视频场景分割
    """
    
    # 调用service层处理业务逻辑
    scene_list = service.video_scene_split(
        video_url=video.video_url,
    )

    return schemas.VideoSceneSplitResponse(scene_list=scene_list)

# 健康检查端点
@router.get("/health", summary="健康检查")
def health_check():
    """检查服务是否正常运行"""
    return {"code": 0, "message": "VideoDetect Service is running"}
