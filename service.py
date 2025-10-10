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
EXEC_TIMEOUT: int = 180

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


def _execute_scene_detection(video_file: str, base_name: str, threshold: int, timeout: int) -> List[str]:
    """
    执行场景检测和视频分割
    
    Args:
        video_file: 视频文件路径
        base_name: 基础文件名（不包含扩展名）
        threshold: 灵敏度
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
        '--threshold', str(threshold),
        '--min-scene-len', '2',
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
    threshold: int = 27
    ) -> List[str]:
    """
    视频场景分割主流程：验证用户、下载视频、计算费用、执行分割、生成下载链接
    
    Args:
        api_key: 用户API密钥
        video_url: 视频URL地址
        threshold: 场景分割灵敏度，默认27
    
    Returns:
        List[str]: 分割后的视频文件下载链接列表

    Raises:
        CustomException: 业务异常（API密钥无效、余额不足、分割失败等）
    """
    logger.info(f"开始视频场景分割处理, API Key: {api_key[:8]}***, URL: {video_url}")
    
    # 步骤1：验证API密钥并获取用户积分
    user_points = _validate_api_key_and_get_points(api_key, video_url)
    
    # 步骤2：下载视频文件
    video_file = helper.download(video_url, config.TEMP_DIR)
    
    try:
        # 步骤3：获取视频时长并计算费用
        duration_and_price = _calculate_video_cost(video_file)
        duration = duration_and_price['duration']
        price = duration_and_price['price']
        
        logger.info(f"视频时长: {duration}秒, 预估费用: {price:.2f}积分")
        
        # 步骤4：检查用户积分是否足够
        _validate_user_balance(user_points, price, video_url)
        
        # 步骤5：执行视频场景分割
        output_files = _perform_scene_detection_and_split(video_file, threshold)
        
        # 步骤6：扣减用户积分（仅在积分查询成功时执行）
        _deduct_user_points_if_possible(user_points, api_key, price)
        
        # 步骤7：生成下载链接并返回
        download_urls = gen_download_urls(output_files)
        logger.info(f"视频场景分割完成，生成 {len(download_urls)} 个视频片段")
        return download_urls
    
    finally:
        # 步骤8：清理临时下载的视频文件
        helper.cleanup_temp_file(video_file)


def _calculate_video_cost(video_file: str) -> dict:
    """
    计算视频处理成本
    
    Args:
        video_file: 视频文件路径
    
    Returns:
        dict: 包含时长和价格的字典
    """
    duration = helper.get_video_duration(video_file)
    price = duration * PRICE_PER_SECOND
    
    return {
        'duration': duration,
        'price': price
    }


def _perform_scene_detection_and_split(video_file: str, threshold: int) -> List[str]:
    """
    执行视频场景检测和分割操作
    
    Args:
        video_file: 视频文件路径
        threshold: 场景切分灵敏度
    
    Returns:
        List[str]: 分割后的视频文件路径列表
        
    Raises:
        CustomException: 场景分割失败时抛出异常
    """
    try:
        # 获取文件名称信息
        video_name = os.path.basename(video_file)
        base_name = os.path.splitext(video_name)[0]
        logger.info(f"准备分割视频: {video_file}, 基础文件名: {base_name}")
        
        # 执行场景检测
        output_files = _execute_scene_detection(video_file, base_name, threshold, EXEC_TIMEOUT)
        
        logger.info(f"场景分割成功，生成 {len(output_files)} 个文件: {output_files}")
        return output_files
        
    except subprocess.TimeoutExpired:
        logger.warning(f"视频场景分割超时, 文件: {video_file}")
        raise CustomException(err=CustomError.VIDEO_SCENE_SPLIT_TIMEOUT)
    except subprocess.CalledProcessError as e:
        logger.error(f"视频场景分割失败, 文件: {video_file}, 返回码: {e.returncode}, 错误: {e.stderr}")
        raise CustomException(err=CustomError.VIDEO_SCENE_SPLIT_FAILED)
    except Exception as e:
        logger.error(f"视频场景分割未知错误, 文件: {video_file}, 详情: {traceback.format_exc()}")
        raise CustomException(err=CustomError.VIDEO_SCENE_SPLIT_FAILED)


def _deduct_user_points_if_possible(user_points: float, api_key: str, price: float) -> None:
    """
    如果用户积分查询成功，则执行积分扣减
    
    Args:
        user_points: 用户当前积分
        api_key: API密钥
        price: 需要扣减的积分
    """
    # 仅在积分查询成功时才执行扣减操作
    if user_points > MIN_POINTS_THRESHOLD:
        success = helper.deduct_user_points(api_key, price, '调用按镜头切分视频')
        if success:
            logger.info(f"成功扣减积分: {price:.2f}, API Key: {api_key[:8]}***")
        else:
            logger.warning(f"积分扣减失败，但不影响业务结果, API Key: {api_key[:8]}***")

def gen_download_url(file_path: str) -> str:
    """
    生成下载 URL，将文件路径中的 /app/ 替换成 DOWNLOAD_URL
    
    Args:
        file_path: 文件路径
    
    Returns:
        str: 下载 URL
    """
    # 1. 如果没有COS配置，则使用本地存储
    if config.COS_BUCKET_NAME == "" or config.COS_SECRET_ID == "" \
        or config.COS_SECRET_KEY == "" or config.COS_REGION == "":
        # 2. 替换文件路径中的 /app/ 为 DOWNLOAD_URL
        download_url = file_path.replace("/app/", config.DOWNLOAD_URL)
        logger.debug(f"Generated download URL: {file_path} -> {download_url}")
        return download_url        

    # 2. 如果有COS配置，则使用COS
    try:
        # 上传文件
        download_url = helper.cos_upload_file(file_path)
        # 删除临时文件
        helper.cleanup_temp_file(file_path)
        return download_url
    except Exception as e:
        logger.info(f"Failed to upload file to COS, file_path: {file_path}, detail: {traceback.format_exc()}")

    # 3. 兜底：使用本地存储，替换文件路径中的 /app/ 为 DOWNLOAD_URL
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
