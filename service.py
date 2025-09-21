from logger import logger
from exceptions import CustomException, CustomError
import traceback
import helper
import config


# 加载模型（只加载一次）
model = None

def video_scene_split(video_url: str) -> list:
    """
    视频场景分割
    
    Args:
        video_url: 视频URL
    
    Returns:
        scene_list: 视频场景列表

    Raises:
        CustomException: 自定义异常
    """
    try:
        # 1. 下载视频文件
        video_file = helper.download(video_url, config.TEMP_DIR)
        logger.info(f"video_file: {video_file}")
        # 2. 视频场景分割
        return []
    except CustomException:
        # 自定义异常直接抛出
        raise
    except Exception as e:
        logger.error(f"Video scene split failed: {str(e)}, detail: {traceback.format_exc()}")
        raise CustomException(err=CustomError.VIDEO_SCENE_SPLIT_FAILED)

def gen_download_url(file_path: str) -> str:
    """
    生成下载URL，将文件路径中的/app/替换成DOWNLOAD_URL
    
    Args:
        file_path: 文件路径
    
    Returns:
        download_url: 下载URL
    """
    # 替换文件路径中的/app/为DOWNLOAD_URL
    download_url = file_path.replace("/app/", config.DOWNLOAD_URL)
    return download_url
