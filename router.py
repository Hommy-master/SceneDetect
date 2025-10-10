from fastapi import APIRouter
import schemas
import service
from logger import logger


# 创建路由器实例，定义API版本前缀
router = APIRouter(prefix="/v1", tags=["v1"])

@router.post("/video/scene-split", response_model=schemas.VideoSceneSplitResponse)
def video_scene_split(video: schemas.VideoSceneSplitRequest):
    """
    视频场景分割API接口
    
    接收用户上传的视频URL，执行场景检测并返回分割后的视频片段链接
    
    Args:
        video: 视频分割请求参数，包含API Key、视频URL和灵敏度参数
        
    Returns:
        VideoSceneSplitResponse: 包含分割后视频片段链接列表的响应
    """
    
    # 记录API调用开始
    logger.info("Video scene split API called")
    
    # 调用service层处理业务逻辑
    scene_list = service.video_scene_split(
        api_key=video.apiKey,
        video_url=str(video.video_url),
        threshold=video.threshold,
    )
    
    # 记录API调用结束
    logger.info("Video scene split API completed successfully")
    
    return schemas.VideoSceneSplitResponse(scene_list=scene_list)

# 健康检查端点
@router.get("/health", summary="健康检查")
def health_check():
    """
    检查服务是否正常运行
    
    返回服务的基本状态信息，用于负载均衡器或监控系统检查服务可用性
    
    Returns:
        dict: 包含状态码和消息的字典
    """
    return {"code": 0, "message": "VideoDetect Service is running"}
