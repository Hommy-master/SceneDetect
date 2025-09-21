from logger import logger
from exceptions import CustomException, CustomError
import traceback
import helper
import config
import os
import subprocess


def video_scene_split(
    video_url: str, 
    threshold: float = 30.0, 
    min_scene_length: int = 2,
    timeout: int = 180) -> list:
    """
    视频场景分割
    
    Args:
        video_url: 视频URL
        threshold: 场景切换阈值，默认30.0
        min_scene_length: 最小场景长度，默认2秒
        timeout: 超时时间，默认180秒
    
    Returns:
        scene_list: 视频场景列表

    Raises:
        CustomException: 自定义异常
    """
    # 1. 下载视频文件
    video_file = helper.download(video_url, config.TEMP_DIR)
    logger.info(f"video_file: {video_file}")

    # 2. 获取文件名称
    video_name = os.path.basename(video_file)
    base_name = os.path.splitext(video_name)[0]

    # 3. 构建命令参数
    command = [
        'scenedetect',
        '-i', video_file,
        'detect-content',
        '-t', str(threshold),
        '-m', str(min_scene_length),
        'split-video',
        '-o', config.VIDEO_OUTPUT_DIR
    ]
    
    # 4. 执行命令
    try:
        # 执行场景检测和视频分割命令
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=True
        )
        logger.debug(f"stdout: {result.stdout}, stderr: {result.stderr}")
        
        # 文件名格式为 ${原文件名}-Scenes-${场景编号}.mp4
        output_pattern = os.path.join(config.VIDEO_OUTPUT_DIR, f"{base_name}-Scenes-*.mp4")
        
        # 获取所有匹配的分割后视频文件
        import glob
        output_files = glob.glob(output_pattern)
        logger.info(f"output_files: {output_files}")
        
        # 按场景编号排序（更符合直观顺序）
        output_files.sort()
        
        return output_files
    except subprocess.TimeoutExpired:
        logger.warning(f"Video scene split timeout, video_url: {video_url}")
        raise CustomException(err=CustomError.VIDEO_SCENE_SPLIT_TIMEOUT)
    except subprocess.CalledProcessError as e:
        logger.error(f"Video scene split failed, video_url: {video_url}, returncode: {e.returncode}, stderr: {e.stderr}")
        raise CustomException(err=CustomError.VIDEO_SCENE_SPLIT_FAILED)
    except Exception as e:
        logger.error(f"Video scene split unknown error, video_url: {video_url}, detail: {traceback.format_exc()}")
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
