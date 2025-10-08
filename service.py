import os
import subprocess
import traceback
import glob
from typing import List

from logger import logger
from exceptions import CustomException, CustomError
import helper
import config

# 常量定义
PRICE_PER_SECOND: float = 0.01  # 每秒视频的价格
MIN_POINTS_THRESHOLD: float = 0  # 最小积分阈值

def _validate_api_key_and_get_points(api_key: str, video_url: str) -> float:
    """
    验证API密钥并获取用户积分
    
    Args:
        api_key: 用户API密钥
        video_url: 视频URL（用于日志）
    
    Returns:
        float: 用户当前积分
    
    Raises:
        CustomException: API密钥无效或其他错误
    """
    try:
        user_points = helper.get_user_points(api_key)
        logger.info(f"Successfully retrieved user points: {user_points} for video: {video_url}")
        return user_points
    except CustomException as e:
        if e.err == CustomError.INVALID_APIKEY:
            logger.error(f"Invalid API key for video: {video_url}")
            raise e
        logger.warning(f"Failed to get user points for video: {video_url}, error: {str(e)}")
        # 返回-1表示获取失败，但不阻断后续流程
        return -1.0


def _validate_user_balance(user_points: float, price: float, video_url: str) -> None:
    """
    验证用户余额是否足够
    
    Args:
        user_points: 用户当前积分
        price: 所需费用
        video_url: 视频URL（用于日志）
    
    Raises:
        CustomException: 余额不足
    """
    if user_points < price and user_points > MIN_POINTS_THRESHOLD:
        logger.info(f"Insufficient points, video_url: {video_url}, price: {price}, total points: {user_points}")
        raise CustomException(err=CustomError.INSUFFICIENT_ACCOUNT_BALANCE)
    else:
        logger.info(f"Balance check passed, video_url: {video_url}, price: {price}, total points: {user_points}")


def _execute_scene_detection(video_file: str, base_name: str, min_scene_length: float, timeout: int) -> List[str]:
    """
    执行场景检测和视频分割
    
    Args:
        video_file: 视频文件路径
        base_name: 基础文件名（不包含扩展名）
        min_scene_length: 最小场景长度
        timeout: 超时时间
    
    Returns:
        List[str]: 分割后的视频文件路径列表
    
    Raises:
        subprocess.TimeoutExpired: 命令执行超时
        subprocess.CalledProcessError: 命令执行失败
        Exception: 其他错误
    """
    # 构建命令参数
    command = [
        'scenedetect',
        '-i', video_file,
        'detect-content',
        '-m', str(min_scene_length),
        'split-video',
        '-o', config.VIDEO_OUTPUT_DIR,
        '-q'
    ]
    
    # 执行场景检测和视频分割命令
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=True
    )
    logger.info(f"Scene detection completed. stdout: {result.stdout}, stderr: {result.stderr}")
    
    # 文件名格式为 ${原文件名}-Scene-${场景编号}.mp4
    output_pattern = os.path.join(config.VIDEO_OUTPUT_DIR, f"{base_name}-Scene-*.mp4")
    
    # 获取所有匹配的分割后视频文件
    output_files = glob.glob(output_pattern)
    logger.info(f"Found {len(output_files)} output files: {output_files}")
    
    # 按场景编号排序（更符合直观顺序）
    output_files.sort()
    
    return output_files


def video_scene_split(
    api_key: str,
    video_url: str, 
    min_scene_length: float = 2.0,
    timeout: int = 180) -> List[str]:
    """
    视频场景分割
    
    Args:
        api_key: 用户API密钥
        video_url: 视频URL地址
        min_scene_length: 最小场景长度（秒），默认2.0秒
        timeout: 超时时间（秒），默认180秒
    
    Returns:
        List[str]: 分割后的视频文件下载链接列表

    Raises:
        CustomException: 业务异常（API密钥无效、余额不足、分割失败等）
    """
    # 1. 验证API密钥并获取用户积分
    user_points = _validate_api_key_and_get_points(api_key, video_url)
    
    # 2. 下载视频文件
    video_file = helper.download(video_url, config.TEMP_DIR)
    
    try:
        # 3. 获取视频时长并计算价格
        duration = helper.get_video_duration(video_file)
        price = duration * PRICE_PER_SECOND
        
        # 4. 检查用户积分是否足够
        _validate_user_balance(user_points, price, video_url)
        
        # 5. 获取文件名称
        video_name = os.path.basename(video_file)
        base_name = os.path.splitext(video_name)[0]
        logger.info(f"video_file: {video_file}, base_name: {base_name}")
        
        # 6. 执行场景检测和视频分割
        try:
            output_files = _execute_scene_detection(video_file, base_name, min_scene_length, timeout)
            
            # 消减用户的帐户余额，这里的判断是保证上面的查询是成功的，如果上面的查询失败了，这里就不做处理了
            if user_points > MIN_POINTS_THRESHOLD:
                helper.deduct_user_points(api_key, price, '调用按镜头切分视频')
            
            return gen_download_urls(output_files)
        except subprocess.TimeoutExpired:
            logger.warning(f"Video scene split timeout, video_url: {video_url}")
            raise CustomException(err=CustomError.VIDEO_SCENE_SPLIT_TIMEOUT)
        except subprocess.CalledProcessError as e:
            logger.error(f"Video scene split failed, video_url: {video_url}, returncode: {e.returncode}, stderr: {e.stderr}")
            raise CustomException(err=CustomError.VIDEO_SCENE_SPLIT_FAILED)
        except Exception as e:
            logger.error(f"Video scene split unknown error, video_url: {video_url}, detail: {traceback.format_exc()}")
            raise CustomException(err=CustomError.VIDEO_SCENE_SPLIT_FAILED)
    
    finally:
        # 7. 清理临时下载的视频文件
        helper.cleanup_temp_file(video_file)

def gen_download_url(file_path: str) -> str:
    """
    生成下载 URL，将文件路径中的 /app/ 替换成 DOWNLOAD_URL
    
    Args:
        file_path: 文件路径
    
    Returns:
        str: 下载 URL
    """
    # 替换文件路径中的 /app/ 为 DOWNLOAD_URL
    download_url = file_path.replace("/app/", config.DOWNLOAD_URL)
    logger.debug(f"Generated download URL: {file_path} -> {download_url}")
    return download_url


def gen_download_urls(files: List[str]) -> List[str]:
    """
    批量生成下载 URL
    
    Args:
        files: 文件路径列表
    
    Returns:
        List[str]: 下载 URL 列表
    """
    download_urls = [gen_download_url(file) for file in files]
    logger.info(f"Generated {len(download_urls)} download URLs from {len(files)} files")
    return download_urls
