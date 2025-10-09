import os
import requests
import mimetypes
import datetime
import uuid
import subprocess
import json
import time
from typing import Dict, Any, Optional

from logger import logger
from exceptions import CustomException, CustomError
from qcloud_cos import CosConfig
from qcloud_cos import CosS3Client
import config

# 常量配置
DEFAULT_FILE_SIZE_LIMIT = 300 * 1024 * 1024  # 300MB
DEFAULT_DOWNLOAD_TIMEOUT = 300  # 5分钟，增加了超时时间
DEFAULT_CONNECT_TIMEOUT = 30  # 连接超时60秒，增加容忍度
DEFAULT_READ_TIMEOUT = 120  # 读取超时120秒，增加容忍度
DEFAULT_API_TIMEOUT = 30  # 30秒
DEFAULT_FFPROBE_TIMEOUT = 30  # 30秒
DEFAULT_RETRY_COUNT = 5  # 默认重试次数增加到5次
CHUNK_SIZE = 16384  # 16KB，增加块大小提高效率
CHUNK_READ_TIMEOUT = 30  # 每个块的读取超时时间增加到30秒
CONNECTION_RETRY_DELAY = 1  # 连接重试间隔时间（秒）
MAX_RETRY_DELAY = 60  # 最大重试等待时间（秒）
MIN_PARTIAL_SIZE = 1024  # 最小部分下载大小（字节），小于此尺寸不使用断点续传
USER_API_BASE_URL = "https://user.jcaigc.cn/openapi/user/v1"

# HTTP请求头（优化网络稳定性）
DOWNLOAD_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': '*/*',
    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
    'Accept-Encoding': 'identity',  # 禁用压缩，避免解压问题
    'Connection': 'keep-alive',  # 保持连接
    'Cache-Control': 'no-cache',  # 不使用缓存
    'Pragma': 'no-cache'  # 兼容性缓存控制
}

API_HEADERS = {
    'User-Agent': 'SceneDetect/1.0',
    'Accept': 'application/json',
    'Content-Type': 'application/json'
}


def download(url: str, save_dir: str, limit: int = DEFAULT_FILE_SIZE_LIMIT, timeout: int = DEFAULT_DOWNLOAD_TIMEOUT, retry: int = DEFAULT_RETRY_COUNT) -> str:
    """
    下载文件并根据Content-Type判断文件类型，支持高度稳定的断点续传和智能重试机制
    
    Args:
        url: 文件的URL地址
        save_dir: 文件保存目录
        limit: 文件大小限制（字节），默认300MB
        timeout: 整体下载超时时间（秒），默认5分钟
        retry: 下载失败时的重试次数，默认5次
    
    Returns:
        str: 完整的文件路径

    Raises:
        CustomException: 下载失败时抛出异常
    """
    # 生成固定的文件路径（不再每次重新生成）
    base_filename = gen_unique_id()
    temp_save_path = os.path.join(save_dir, base_filename)
    
    # 检查网络连接质量和服务器支持情况
    network_quality = _assess_network_quality(url)
    supports_range = _check_range_support_with_retry(url)
    
    logger.info(f"Network quality: {network_quality}, Range support: {supports_range} for {url}")
    
    # 根据网络质量调整超时参数
    adaptive_timeouts = _calculate_adaptive_timeouts(network_quality, timeout)
    
    last_exception = None
    consecutive_failures = 0  # 连续失败次数
    
    for attempt in range(retry + 1):  # 总共尝试 retry + 1 次（包括第一次）
        try:
            logger.info(f"Downloading file, attempt {attempt + 1}/{retry + 1}, url: {url}")
            
            # 检查是否存在部分下载的文件
            existing_size = 0
            if os.path.exists(temp_save_path):
                existing_size = os.path.getsize(temp_save_path)
                logger.info(f"Found existing partial file: {temp_save_path}, size: {existing_size} bytes")
            
            # 决定是否使用断点续传（仅在部分文件足够大时使用）
            use_resume = (
                supports_range and 
                existing_size >= MIN_PARTIAL_SIZE and 
                attempt > 0 and
                consecutive_failures <= 2  # 连续失败太多时不使用断点续传
            )
            
            if use_resume:
                logger.info(f"Resuming download from byte {existing_size}")
                response = _download_with_resume_enhanced(url, existing_size, adaptive_timeouts)
            else:
                if existing_size > 0 and (not supports_range or consecutive_failures > 2):
                    logger.info("Removing partial file due to server limitation or repeated failures")
                    _safe_remove_file(temp_save_path)
                    existing_size = 0
                logger.info("Starting fresh download with enhanced stability")
                response = _download_fresh_enhanced(url, adaptive_timeouts)
            
            # 获取并处理文件类型（只在首次下载时进行）
            if existing_size == 0:
                temp_save_path = _determine_file_path_with_extension(response, temp_save_path)
            
            # 下载文件并检查大小（增强版本）
            _download_file_with_enhanced_stability(
                response, temp_save_path, limit, url, adaptive_timeouts, 
                existing_size, use_resume
            )
            
            # 验证下载完整性
            _validate_download_integrity_with_resume(response, temp_save_path, url, use_resume)
            
            logger.info(f"Download success on attempt {attempt + 1}, url: {url}, save_path: {temp_save_path}")
            return temp_save_path
            
        except Exception as e:
            last_exception = e
            consecutive_failures += 1
            
            # 分类处理异常
            error_category = _classify_download_error(e)
            
            # 如果是不可恢复的错误，直接抛出
            if error_category == 'fatal':
                if os.path.exists(temp_save_path):
                    _safe_remove_file(temp_save_path)
                logger.error(f"Fatal error, no retry needed, url: {url}, error: {str(e)}")
                raise e
            
            # 如果不是最后一次尝试，记录警告并等待
            if attempt < retry:
                logger.warning(f"Download attempt {attempt + 1} failed, url: {url}, error: {str(e)}, category: {error_category}")
                
                # 根据错误类型决定是否清理文件
                should_cleanup = _should_cleanup_on_error(error_category, supports_range, consecutive_failures)
                if should_cleanup and os.path.exists(temp_save_path):
                    _safe_remove_file(temp_save_path)
                    logger.debug(f"Cleaned up partial download file: {temp_save_path}")
                
                # 智能重试等待策略
                wait_time = _calculate_retry_delay(attempt, error_category, consecutive_failures)
                logger.info(f"Waiting {wait_time}s before retry...")
                time.sleep(wait_time)
                
                # 在网络问题后重新评估网络质量
                if error_category == 'network':
                    network_quality = _assess_network_quality(url)
                    adaptive_timeouts = _calculate_adaptive_timeouts(network_quality, timeout)
                    logger.info(f"Re-assessed network quality: {network_quality}")
            else:
                logger.error(f"Download failed after {retry + 1} attempts, url: {url}, final error: {str(e)}")
                # 最后一次失败后清理文件
                if os.path.exists(temp_save_path):
                    _safe_remove_file(temp_save_path)
    
    # 所有重试都失败后，抛出最后一次的异常
    if isinstance(last_exception, CustomException):
        raise last_exception
    
    logger.error(f"Download failed after all retries, url: {url}, last error: {str(last_exception)}")
    raise CustomException(CustomError.DOWNLOAD_FILE_FAILED)

def gen_unique_id() -> str:
    """
    生成唯一ID
    
    Returns:
        str: 时间戳 + UUID的唯一标识符
    """
    timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
    unique_id = uuid.uuid4().hex[:8]
    return f"{timestamp}{unique_id}"


def _determine_file_path_with_extension(response: requests.Response, save_path: str) -> str:
    """
    根据HTTP响应的Content-Type确定文件路径和扩展名
    
    Args:
        response: HTTP响应对象
        save_path: 原始保存路径
    
    Returns:
        str: 带扩展名的文件路径
    """
    content_type = response.headers.get('Content-Type', '').split(';')[0].strip()
    extension = mimetypes.guess_extension(content_type)
    
    if extension:
        return save_path + extension
    return save_path


def _download_file_with_timeout_and_size_check(response: requests.Response, save_path: str, limit: int, url: str, total_timeout: int) -> None:
    """
    下载文件并实时检查文件大小，支持超时检测
    
    Args:
        response: HTTP响应对象
        save_path: 文件保存路径
        limit: 文件大小限制
        url: 文件URL（用于日志）
        total_timeout: 总超时时间（秒）
    
    Raises:
        CustomException: 文件大小超限或下载超时时抛出
    """
    downloaded_size = 0
    start_time = time.time()
    last_chunk_time = start_time
    
    with open(save_path, 'wb') as f:
        try:
            for chunk in response.iter_content(chunk_size=CHUNK_SIZE):
                current_time = time.time()
                
                # 检查总体超时
                if current_time - start_time > total_timeout:
                    raise CustomException(
                        CustomError.DOWNLOAD_FILE_TIMEOUT, 
                        detail=f"下载超时，总耗时{current_time - start_time:.1f}秒，超过{total_timeout}秒限制"
                    )
                
                # 检查单个块的读取超时（网络停滞检测）
                if current_time - last_chunk_time > CHUNK_READ_TIMEOUT:
                    raise CustomException(
                        CustomError.DOWNLOAD_FILE_FAILED, 
                        detail=f"网络连接中断，单个数据块读取超时{CHUNK_READ_TIMEOUT}秒"
                    )
                
                if chunk:
                    f.write(chunk)
                    downloaded_size += len(chunk)
                    last_chunk_time = current_time
                    
                    # 检查文件大小是否超过限制
                    if downloaded_size > limit:
                        f.close()
                        os.remove(save_path)
                        
                        limit_mb = limit / 1024 / 1024
                        logger.info(f"Download failed, url: {url}, error: File size exceeds the limit of {limit_mb:.2f}MB")
                        raise CustomException(CustomError.FILE_SIZE_LIMIT_EXCEEDED, detail=f"{limit_mb:.2f} MB")
                    
                    # 每下载10MB记录一次进度（避免日志过多）
                    if downloaded_size % (10 * 1024 * 1024) == 0:
                        logger.info(f"Downloaded {downloaded_size / 1024 / 1024:.1f}MB for {url}")
                        
        except requests.exceptions.ChunkedEncodingError as e:
            raise CustomException(
                CustomError.DOWNLOAD_FILE_FAILED, 
                detail=f"数据传输错误：{str(e)}"
            )
        except Exception as e:
            # 如果是我们自己的异常，直接重新抛出
            if isinstance(e, CustomException):
                raise e
            # 其他异常包装为下载失败
            raise CustomException(
                CustomError.DOWNLOAD_FILE_FAILED, 
                detail=f"下载过程中发生错误：{str(e)}"
            )


def _validate_download_integrity(response: requests.Response, save_path: str, url: str) -> None:
    """
    验证下载文件的完整性
    
    Args:
        response: HTTP响应对象
        save_path: 文件保存路径
        url: 文件URL（用于日志）
    
    Raises:
        CustomException: 文件不完整时抛出
    """
    content_length = response.headers.get('Content-Length')
    
    if content_length:
        expected_size = int(content_length)
        actual_size = os.path.getsize(save_path)
        
        if actual_size != expected_size:
            os.remove(save_path)
            logger.warning(f"Download failed, url: {url}, error: File download incomplete: expected {expected_size} bytes, actual {actual_size} bytes")
            raise CustomException(CustomError.DOWNLOAD_FILE_FAILED)


def _extract_points_from_response(result: Dict[str, Any]) -> float:
    """
    从响应中提取积分数据
    
    Args:
        result: API响应数据
    
    Returns:
        float: 积分值
    
    Raises:
        CustomException: 积分数据格式错误时
    """
    try:
        points = result.get('data', {}).get('points', 0.0)
        return float(points)
    except (ValueError, TypeError):
        logger.error(f"Invalid points format in API response, result: {result}")
        raise CustomException(CustomError.INTERNAL_SERVER_ERROR, detail="积分格式错误")


def get_user_points(api_key: str) -> float:
    """
    根据API Key获取用户积分
    
    Args:
        api_key: 用户的API Key
    
    Returns:
        float: 用户当前积分
    
    Raises:
        CustomException: 当获取积分失败时
    """
    try:
        # 调用获取积分API
        params = {'apiKey': api_key}
        result = _call_user_api('GET', '/points', params=params)
        
        # 检查响应码并处理结果
        code = result.get('code', -1)
        
        if code == 0:
            points = _extract_points_from_response(result)
            logger.info(f"Successfully retrieved user points: {points} for API key: {api_key}")
            return points
        elif code in (21002, 400):  # API Key无效
            logger.error(f"Invalid API key, result: {result}, code: {code}")
            raise CustomException(CustomError.INVALID_APIKEY, detail=f"{api_key}")
        else:
            logger.error(f"Failed to get user points: {result}, code: {code}")
            raise CustomException(CustomError.UNKNOWN_ERROR, detail=f"获取用户积分时发生未知错误: {result}, code: {code}")
            
    except CustomException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error getting user points for API key {api_key}: {str(e)}")
        raise CustomException(CustomError.UNKNOWN_ERROR, detail=f"获取用户积分时发生未知错误: {str(e)}")


def deduct_user_points(api_key: str, points: float, desc: str) -> bool:
    """
    根据API Key减少用户积分
    
    Args:
        api_key: 用户的API Key
        points: 要减少的积分数量（必须为正数）
        desc: 减少积分的原因描述
    
    Returns:
        bool: True表示扣减成功，False表示失败
    Raises:
        CustomException: 仅当apiKey无效时抛出异常
    """
    try:
        # 调用扣减积分API
        json_data = {
            'apiKey': api_key,
            'points': float(points),
            'desc': desc.strip()
        }
        
        result = _call_user_api('POST', '/points/deduct', json_data=json_data)
        code = result.get('code', -1)
        
        if code == 0:
            logger.info(f"Successfully deducted {points} points for API key {api_key}, reason: {desc}")
            return True
        elif code in (21002, 400):  # API Key无效
            logger.error(f"Invalid API key for deduct points: {result}, code: {code}")
            raise CustomException(CustomError.INVALID_APIKEY, detail=f"{api_key}")
        else:
            logger.error(f"Failed to deduct points: {result}, code: {code}")
            return False
    except CustomException as e:
        logger.warning(f"Deduct points failed, API key: {api_key}, error: {str(e)}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error deducting points for API key {api_key}: {str(e)}")
        return False

def _parse_api_response(response: requests.Response) -> Dict[str, Any]:
    """
    解析API响应的JSON数据
    
    Args:
        response: HTTP响应对象
    
    Returns:
        Dict[str, Any]: 解析后的JSON数据
    
    Raises:
        CustomException: JSON解析失败时
    """
    try:
        return response.json()
    except ValueError:
        logger.error(f"Failed to parse API response as JSON: {response.text}")
        raise CustomException(CustomError.INTERNAL_SERVER_ERROR, detail="API响应格式错误")


def _call_user_api(method: str, endpoint: str, params: Optional[dict] = None, json_data: Optional[dict] = None, timeout: int = DEFAULT_API_TIMEOUT) -> Dict[str, Any]:
    """
    调用用户积分相关API的通用方法
    
    Args:
        method: HTTP方法 ('GET' 或 'POST')
        endpoint: API端点路径
        params: 查询参数（用于GET请求）
        json_data: JSON数据（用于POST请求）
        timeout: 请求超时时间（秒）
    
    Returns:
        Dict[str, Any]: API响应的JSON数据
    
    Raises:
        CustomException: 当API调用失败或返回错误时
    """
    url = f"{USER_API_BASE_URL}{endpoint}"
    
    try:
        logger.info(f"Calling user API: {method} {url}")
        
        # 根据方法类型发送请求
        if method.upper() == 'GET':
            response = requests.get(url, params=params, headers=API_HEADERS, timeout=timeout)
        elif method.upper() == 'POST':
            response = requests.post(url, json=json_data, headers=API_HEADERS, timeout=timeout)
        else:
            raise ValueError(f"Unsupported HTTP method: {method}")
        
        response.raise_for_status()
        
        # 解析JSON响应
        return _parse_api_response(response)
        
    except requests.exceptions.Timeout:
        logger.error(f"User API timeout: {method} {url}")
        raise CustomException(CustomError.INTERNAL_SERVER_ERROR, detail="用户API调用超时")
    except requests.exceptions.ConnectionError:
        logger.error(f"User API connection error: {method} {url}")
        raise CustomException(CustomError.INTERNAL_SERVER_ERROR, detail="无法连接到用户API服务")
    except requests.exceptions.RequestException as e:
        logger.error(f"User API request failed: {method} {url}, error: {str(e)}")
        raise CustomException(CustomError.INTERNAL_SERVER_ERROR, detail=f"用户API请求失败: {str(e)}")
    except CustomException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error in user API call: {method} {url}, error: {str(e)}")
        raise CustomException(CustomError.UNKNOWN_ERROR, detail=f"调用用户API时发生未知错误: {str(e)}")


def get_video_duration(file_path: str) -> int:
    """
    获取音/视频时长
    
    Args:
        file_path: 音/视频文件路径
    
    Returns:
        int: 音/视频时长，单位：秒
    
    Raises:
        CustomException: 音/视频分析失败
    """
    logger.info(f"Using ffprobe to analyze file: {file_path}")
    
    try:
        # 构建并执行ffprobe命令
        ffprobe_data = _run_ffprobe_command(file_path)
        
        # 提取时长信息
        duration_seconds = _extract_duration_from_ffprobe_data(ffprobe_data)
        
        # 验证并返回时长
        return int(duration_seconds)
        
    except UnicodeDecodeError as e:
        logger.warning(f"FFprobe output encoding issue: {e}, trying binary mode")
        return _analyze_audio_with_ffprobe_binary(file_path)
    except subprocess.TimeoutExpired:
        logger.error("FFprobe command timed out")
        raise CustomException(CustomError.INTERNAL_SERVER_ERROR, "Audio analysis timed out")
    except subprocess.CalledProcessError as e:
        logger.error(f"FFprobe command failed with return code {e.returncode}")
        logger.error(f"FFprobe stderr: {e.stderr}")
        raise CustomException(CustomError.INTERNAL_SERVER_ERROR, f"FFprobe analysis failed: {e.stderr}")
    except FileNotFoundError:
        logger.error("FFprobe command not found. Please ensure FFprobe is installed and in PATH")
        raise CustomException(CustomError.INTERNAL_SERVER_ERROR, "FFprobe tool not available")


def _run_ffprobe_command(file_path: str) -> Dict[str, Any]:
    """
    执行ffprobe命令并返回解析结果
    
    Args:
        file_path: 音/视频文件路径
    
    Returns:
        Dict[str, Any]: ffprobe解析结果
    
    Raises:
        subprocess.TimeoutExpired: 命令超时
        subprocess.CalledProcessError: 命令执行失败
        FileNotFoundError: ffprobe工具未找到
    """
    cmd = [
        'ffprobe', 
        '-i', file_path,
        '-v', 'quiet',
        '-print_format', 'json',
        '-show_format',
        '-show_streams'
    ]
    
    logger.info(f"Executing ffprobe command: {' '.join(cmd)}")
    
    # 执行ffprobe命令
    result = subprocess.run(
        cmd, 
        capture_output=True, 
        text=True,
        encoding='utf-8',  # 明确指定UTF-8编码
        errors='replace',  # 遇到无法解码的字符时用替换字符代替
        timeout=DEFAULT_FFPROBE_TIMEOUT,
        check=True
    )
    
    logger.info("FFprobe analysis completed successfully")
    
    # 检查stdout是否为None或为空（编码问题可能导致这个情况）
    if result.stdout is None or not result.stdout.strip():
        logger.warning("FFprobe stdout is None or empty, likely due to encoding issues")
        raise UnicodeDecodeError("utf-8", b"", 0, 1, "Empty ffprobe output")
    
    # 解析ffprobe输出
    return _parse_ffprobe_output(result.stdout)


def _parse_ffprobe_output(stdout: str) -> Dict[str, Any]:
    """
    解析ffprobe的JSON输出
    
    Args:
        stdout: ffprobe的标准输出
    
    Returns:
        解析后的JSON数据
    
    Raises:
        CustomException: JSON解析失败
    """
    try:
        return json.loads(stdout)
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse ffprobe JSON output: {e}")
        logger.error(f"FFprobe stdout: {stdout}")
        raise CustomException(CustomError.INTERNAL_SERVER_ERROR, "Failed to parse audio analysis result")


def _extract_duration_from_ffprobe_data(ffprobe_data: Dict[str, Any]) -> float:
    """
    从ffprobe数据中提取时长信息
    
    Args:
        ffprobe_data: ffprobe解析后的数据
    
    Returns:
        时长（秒）
    
    Raises:
        CustomException: 无法提取时长信息
    """
    # 优先从format信息中获取时长
    if 'format' in ffprobe_data and 'duration' in ffprobe_data['format']:
        duration_seconds = float(ffprobe_data['format']['duration'])
        logger.info(f"Got duration from format info: {duration_seconds}s")
        return duration_seconds
    
    # 如果format中没有时长，尝试从音频流中获取
    if 'streams' in ffprobe_data:
        for stream in ffprobe_data['streams']:
            if stream.get('codec_type') == 'audio' and 'duration' in stream:
                duration_seconds = float(stream['duration'])
                logger.info(f"Got duration from audio stream: {duration_seconds}s")
                return duration_seconds
    
    # 无法提取时长
    logger.error("Unable to extract duration from ffprobe output")
    logger.error(f"FFprobe output: {json.dumps(ffprobe_data, indent=2)}")
    raise CustomException(CustomError.INTERNAL_SERVER_ERROR, "Unable to extract duration from audio file")


def cleanup_temp_file(temp_file_path: Optional[str]) -> None:
    """
    清理临时文件
    
    Args:
        temp_file_path: 临时文件路径，可能为None
    """
    if temp_file_path and os.path.exists(temp_file_path):
        try:
            os.remove(temp_file_path)
            logger.info(f"Temporary file removed: {temp_file_path}")
        except Exception as cleanup_error:
            logger.warning(f"Failed to cleanup temporary file {temp_file_path}: {cleanup_error}")


def _analyze_audio_with_ffprobe_binary(file_path: str) -> int:
    """
    使用二进制模式执行ffprobe，解决编码问题
    
    Args:
        file_path: 音频文件路径
    
    Returns:
        int: 音频时长，单位：秒（修正文档错误）
    
    Raises:
        CustomException: 音频分析失败
    """
    logger.info(f"Trying binary mode for ffprobe analysis: {file_path}")
    
    try:
        cmd = [
            'ffprobe', 
            '-i', file_path,
            '-v', 'quiet',
            '-print_format', 'json',
            '-show_format',
            '-show_streams'
        ]
        
        # 使用二进制模式执行命令
        result = subprocess.run(
            cmd, 
            capture_output=True, 
            text=False,  # 二进制模式
            timeout=DEFAULT_FFPROBE_TIMEOUT,
            check=True
        )
        
        # 手动解码，尝试多种编码
        stdout_text = _decode_ffprobe_output(result.stdout)
        
        # 解析ffprobe输出
        ffprobe_data = _parse_ffprobe_output(stdout_text)
        
        # 提取时长信息
        duration_seconds = _extract_duration_from_ffprobe_data(ffprobe_data)
        
        # 验证并转换时长
        return int(duration_seconds)
        
    except subprocess.CalledProcessError as e:
        logger.error(f"FFprobe binary mode failed with return code {e.returncode}")
        raise CustomException(CustomError.INTERNAL_SERVER_ERROR, f"FFprobe binary analysis failed: {e.returncode}")
    except Exception as e:
        logger.error(f"FFprobe binary mode failed with error: {str(e)}")
        raise CustomException(CustomError.INTERNAL_SERVER_ERROR, f"FFprobe binary analysis error: {str(e)}")


def _decode_ffprobe_output(stdout_bytes: bytes) -> str:
    """
    解码ffprobe的二进制输出，尝试多种编码
    
    Args:
        stdout_bytes: ffprobe的二进制输出
    
    Returns:
        str: 解码后的文本
    """
    # 尝试多种编码
    for encoding in ['utf-8', 'gbk', 'latin1']:
        try:
            stdout_text = stdout_bytes.decode(encoding)
            logger.info(f"Successfully decoded ffprobe output using {encoding} encoding")
            return stdout_text
        except UnicodeDecodeError:
            continue
    
    # 如果所有编码都失败，使用错误替换
    stdout_text = stdout_bytes.decode('utf-8', errors='replace')
    logger.warning("Used error replacement for ffprobe output decoding")
    return stdout_text


def _check_range_support(url: str) -> bool:
    """
    检查服务器是否支持断点续传（Range请求）
    
    Args:
        url: 文件URL
    
    Returns:
        bool: True表示支持Range请求，False表示不支持
    """
    try:
        # 发送HEAD请求检查服务器支持
        response = requests.head(
            url, 
            timeout=(DEFAULT_CONNECT_TIMEOUT, DEFAULT_READ_TIMEOUT),
            headers=DOWNLOAD_HEADERS
        )
        response.raise_for_status()
        
        # 检查Accept-Ranges头
        accept_ranges = response.headers.get('Accept-Ranges', '').lower()
        supports_ranges = accept_ranges == 'bytes'
        
        logger.info(f"Range support check for {url}: Accept-Ranges={accept_ranges}, supports={supports_ranges}")
        return supports_ranges
        
    except Exception as e:
        logger.warning(f"Failed to check range support for {url}: {str(e)}, assuming no support")
        return False


def _download_with_resume(url: str, resume_pos: int, timeout: int) -> requests.Response:
    """
    使用断点续传下载文件
    
    Args:
        url: 文件URL
        resume_pos: 断点续传的起始位置（字节）
        timeout: 超时时间
    
    Returns:
        requests.Response: HTTP响应对象
    """
    headers = DOWNLOAD_HEADERS.copy()
    headers['Range'] = f'bytes={resume_pos}-'
    
    response = requests.get(
        url,
        stream=True,
        timeout=(DEFAULT_CONNECT_TIMEOUT, DEFAULT_READ_TIMEOUT),
        headers=headers
    )
    
    # 断点续传应该返回206状态码
    if response.status_code == 206:
        logger.info(f"Resume download successful, status: {response.status_code}")
    elif response.status_code == 200:
        logger.warning("Server returned 200 instead of 206, might not support resume")
    else:
        response.raise_for_status()
    
    return response


def _download_fresh(url: str, timeout: int) -> requests.Response:
    """
    全新下载文件
    
    Args:
        url: 文件URL
        timeout: 超时时间
    
    Returns:
        requests.Response: HTTP响应对象
    """
    response = requests.get(
        url,
        stream=True,
        timeout=(DEFAULT_CONNECT_TIMEOUT, DEFAULT_READ_TIMEOUT),
        headers=DOWNLOAD_HEADERS
    )
    response.raise_for_status()
    return response


def _download_file_with_resume_support(
    response: requests.Response, 
    save_path: str, 
    limit: int, 
    url: str, 
    total_timeout: int,
    existing_size: int = 0,
    is_resume: bool = False
) -> None:
    """
    下载文件并实时检查文件大小，支持断点续传和超时检测
    
    Args:
        response: HTTP响应对象
        save_path: 文件保存路径
        limit: 文件大小限制
        url: 文件URL（用于日志）
        total_timeout: 总超时时间（秒）
        existing_size: 已存在的文件大小（断点续传时使用）
        is_resume: 是否为断点续传
    
    Raises:
        CustomException: 文件大小超限或下载超时时抛出
    """
    downloaded_size = existing_size  # 断点续传时从已下载大小开始
    start_time = time.time()
    last_chunk_time = start_time
    
    # 断点续传时使用追加模式，否则使用覆盖模式
    file_mode = 'ab' if is_resume else 'wb'
    
    with open(save_path, file_mode) as f:
        try:
            for chunk in response.iter_content(chunk_size=CHUNK_SIZE):
                current_time = time.time()
                
                # 检查总体超时
                if current_time - start_time > total_timeout:
                    raise CustomException(
                        CustomError.DOWNLOAD_FILE_TIMEOUT, 
                        detail=f"下载超时，总耗时{current_time - start_time:.1f}秒，超过{total_timeout}秒限制"
                    )
                
                # 检查单个块的读取超时（网络停滞检测）
                if current_time - last_chunk_time > CHUNK_READ_TIMEOUT:
                    raise CustomException(
                        CustomError.DOWNLOAD_FILE_FAILED, 
                        detail=f"网络连接中断，单个数据块读取超时{CHUNK_READ_TIMEOUT}秒"
                    )
                
                if chunk:
                    f.write(chunk)
                    downloaded_size += len(chunk)
                    last_chunk_time = current_time
                    
                    # 检查文件大小是否超过限制
                    if downloaded_size > limit:
                        f.close()
                        os.remove(save_path)
                        
                        limit_mb = limit / 1024 / 1024
                        logger.info(f"Download failed, url: {url}, error: File size exceeds the limit of {limit_mb:.2f}MB")
                        raise CustomException(CustomError.FILE_SIZE_LIMIT_EXCEEDED, detail=f"{limit_mb:.2f} MB")
                    
                    # 每下载10MB记录一次进度（避免日志过多）
                    if downloaded_size % (10 * 1024 * 1024) == 0:
                        logger.info(f"Downloaded {downloaded_size / 1024 / 1024:.1f}MB for {url}")
                        
        except requests.exceptions.ChunkedEncodingError as e:
            raise CustomException(
                CustomError.DOWNLOAD_FILE_FAILED, 
                detail=f"数据传输错误：{str(e)}"
            )
        except Exception as e:
            # 如果是我们自己的异常，直接重新抛出
            if isinstance(e, CustomException):
                raise e
            # 其他异常包装为下载失败
            raise CustomException(
                CustomError.DOWNLOAD_FILE_FAILED, 
                detail=f"下载过程中发生错误：{str(e)}"
            )


def _validate_download_integrity_with_resume(
    response: requests.Response, 
    save_path: str, 
    url: str, 
    is_resume: bool = False
) -> None:
    """
    验证下载文件的完整性（支持断点续传）
    
    Args:
        response: HTTP响应对象
        save_path: 文件保存路径
        url: 文件URL（用于日志）
        is_resume: 是否为断点续传
    
    Raises:
        CustomException: 文件不完整时抛出
    """
    actual_size = os.path.getsize(save_path)
    
    if is_resume:
        # 断点续传时，检查Content-Range头
        content_range = response.headers.get('Content-Range')
        if content_range:
            # Content-Range: bytes 1024-2047/2048
            try:
                range_info = content_range.split('/')[-1]
                if range_info != '*':
                    expected_total_size = int(range_info)
                    if actual_size != expected_total_size:
                        os.remove(save_path)
                        logger.warning(
                            f"Resume download failed, url: {url}, "
                            f"error: File download incomplete: expected {expected_total_size} bytes, "
                            f"actual {actual_size} bytes"
                        )
                        raise CustomException(CustomError.DOWNLOAD_FILE_FAILED)
            except (ValueError, IndexError) as e:
                logger.warning(f"Failed to parse Content-Range header: {content_range}, error: {e}")
    else:
        # 全新下载时，检查Content-Length头
        content_length = response.headers.get('Content-Length')
        if content_length:
            expected_size = int(content_length)
            if actual_size != expected_size:
                os.remove(save_path)
                logger.warning(
                    f"Download failed, url: {url}, "
                    f"error: File download incomplete: expected {expected_size} bytes, "
                    f"actual {actual_size} bytes"
                )
                raise CustomException(CustomError.DOWNLOAD_FILE_FAILED)


def cos_upload_file(file_path: str) -> str:
    """
    上传文件到OSS
    
    Args:
        file_path: 文件路径

    Returns:
        str: 对象URL
    
    Raises:
        CustomException: 上传失败
    """
    cfg = CosConfig(Region=config.COS_REGION, SecretId=config.COS_SECRET_ID, SecretKey=config.COS_SECRET_KEY, Token=None)
    cli = CosS3Client(cfg)
    try:
        # 1. 上传文件
        key = os.path.basename(file_path)
        response = cli.put_object_from_local_file(
            Bucket=config.COS_BUCKET_NAME, 
            LocalFilePath=file_path,
            Key=key       
        )
        logger.info(f"COS upload success, response: {response}")
        # 2. 拼公开下载地址
        public_url = f'http://{config.COS_BUCKET_NAME}.cos.{config.COS_REGION}.myqcloud.com/{key}'
        return public_url
    except Exception as e:
        logger.error(f"COS upload failed: {e}")
        raise CustomException(CustomError.INTERNAL_SERVER_ERROR, "COS upload failed")


def _safe_remove_file(file_path: str) -> None:
    """
    安全删除文件，忽略删除错误
    
    Args:
        file_path: 要删除的文件路径
    """
    try:
        if os.path.exists(file_path):
            os.remove(file_path)
            logger.debug(f"Successfully removed file: {file_path}")
    except Exception as e:
        logger.warning(f"Failed to remove file {file_path}: {e}")


def _assess_network_quality(url: str) -> str:
    """
    评估网络质量
    
    Args:
        url: 测试URL
    
    Returns:
        str: 网络质量 ('good', 'medium', 'poor')
    """
    try:
        import urllib.parse
        parsed_url = urllib.parse.urlparse(url)
        test_url = f"{parsed_url.scheme}://{parsed_url.netloc}"
        
        start_time = time.time()
        response = requests.head(
            test_url,
            timeout=(10, 5),  # 短超时测试
            headers={'User-Agent': DOWNLOAD_HEADERS['User-Agent']}
        )
        response_time = time.time() - start_time
        
        if response_time < 1.0:
            return 'good'
        elif response_time < 3.0:
            return 'medium'
        else:
            return 'poor'
            
    except Exception as e:
        logger.warning(f"Failed to assess network quality: {e}")
        return 'poor'  # 默认为较差的网络环境


def _check_range_support_with_retry(url: str, max_retries: int = 2) -> bool:
    """
    带重试的范围请求支持检测
    
    Args:
        url: 文件URL
        max_retries: 最大重试次数
    
    Returns:
        bool: 是否支持Range请求
    """
    for attempt in range(max_retries + 1):
        try:
            response = requests.head(
                url, 
                timeout=(DEFAULT_CONNECT_TIMEOUT, DEFAULT_READ_TIMEOUT),
                headers=DOWNLOAD_HEADERS
            )
            response.raise_for_status()
            
            accept_ranges = response.headers.get('Accept-Ranges', '').lower()
            supports_ranges = accept_ranges == 'bytes'
            
            logger.info(f"Range support check attempt {attempt + 1}: Accept-Ranges={accept_ranges}, supports={supports_ranges}")
            return supports_ranges
            
        except Exception as e:
            if attempt < max_retries:
                logger.warning(f"Range support check attempt {attempt + 1} failed: {e}, retrying...")
                time.sleep(1)
            else:
                logger.warning(f"Failed to check range support after {max_retries + 1} attempts: {e}")
                return False
    
    return False


def _calculate_adaptive_timeouts(network_quality: str, base_timeout: int) -> dict:
    """
    根据网络质量计算自适应超时参数
    
    Args:
        network_quality: 网络质量 ('good', 'medium', 'poor')
        base_timeout: 基础超时时间
    
    Returns:
        dict: 超时参数字典
    """
    if network_quality == 'good':
        multiplier = 1.0
        chunk_timeout_multiplier = 1.0
    elif network_quality == 'medium':
        multiplier = 1.5
        chunk_timeout_multiplier = 2.0
    else:  # poor
        multiplier = 2.0
        chunk_timeout_multiplier = 3.0
    
    return {
        'connect_timeout': int(DEFAULT_CONNECT_TIMEOUT * multiplier),
        'read_timeout': int(DEFAULT_READ_TIMEOUT * multiplier),
        'total_timeout': int(base_timeout * multiplier),
        'chunk_timeout': int(CHUNK_READ_TIMEOUT * chunk_timeout_multiplier)
    }


def _download_with_resume_enhanced(url: str, resume_pos: int, timeouts: dict) -> requests.Response:
    """
    增强版的断点续传下载
    
    Args:
        url: 文件URL
        resume_pos: 断点续传的起始位置
        timeouts: 超时参数字典
    
    Returns:
        requests.Response: HTTP响应对象
    """
    headers = DOWNLOAD_HEADERS.copy()
    headers['Range'] = f'bytes={resume_pos}-'
    
    # 使用更长的超时时间和重试机制
    session = requests.Session()
    session.headers.update(headers)
    
    for attempt in range(3):  # 内部重试机制
        try:
            response = session.get(
                url,
                stream=True,
                timeout=(timeouts['connect_timeout'], timeouts['read_timeout'])
            )
            
            if response.status_code == 206:
                logger.info(f"Resume download successful, status: {response.status_code}")
                return response
            elif response.status_code == 200:
                logger.warning("Server returned 200 instead of 206, treating as fresh download")
                return response
            else:
                response.raise_for_status()
                
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
            if attempt < 2:
                logger.warning(f"Resume download attempt {attempt + 1} failed: {e}, retrying...")
                time.sleep(CONNECTION_RETRY_DELAY)
            else:
                raise
    
    raise requests.exceptions.RequestException("Failed to establish resume connection after retries")


def _download_fresh_enhanced(url: str, timeouts: dict) -> requests.Response:
    """
    增强版的全新下载
    
    Args:
        url: 文件URL
        timeouts: 超时参数字典
    
    Returns:
        requests.Response: HTTP响应对象
    """
    session = requests.Session()
    session.headers.update(DOWNLOAD_HEADERS)
    
    for attempt in range(3):  # 内部重试机制
        try:
            response = session.get(
                url,
                stream=True,
                timeout=(timeouts['connect_timeout'], timeouts['read_timeout'])
            )
            response.raise_for_status()
            return response
            
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
            if attempt < 2:
                logger.warning(f"Fresh download attempt {attempt + 1} failed: {e}, retrying...")
                time.sleep(CONNECTION_RETRY_DELAY)
            else:
                raise
    
    raise requests.exceptions.RequestException("Failed to establish fresh connection after retries")


def _download_file_with_enhanced_stability(
    response: requests.Response, 
    save_path: str, 
    limit: int, 
    url: str, 
    timeouts: dict,
    existing_size: int = 0,
    is_resume: bool = False
) -> None:
    """
    增强稳定性的文件下载
    
    Args:
        response: HTTP响应对象
        save_path: 文件保存路径
        limit: 文件大小限制
        url: 文件URL
        timeouts: 超时参数字典
        existing_size: 已存在的文件大小
        is_resume: 是否为断点续传
    """
    downloaded_size = existing_size
    start_time = time.time()
    last_chunk_time = start_time
    last_progress_time = start_time
    
    file_mode = 'ab' if is_resume else 'wb'
    
    try:
        with open(save_path, file_mode) as f:
            for chunk in response.iter_content(chunk_size=CHUNK_SIZE):
                current_time = time.time()
                
                # 检查总体超时
                if current_time - start_time > timeouts['total_timeout']:
                    raise CustomException(
                        CustomError.DOWNLOAD_FILE_TIMEOUT, 
                        detail=f"下载超时，总耗时{current_time - start_time:.1f}秒"
                    )
                
                # 检查单个块的读取超时（网络停滞检测）
                if current_time - last_chunk_time > timeouts['chunk_timeout']:
                    raise CustomException(
                        CustomError.DOWNLOAD_FILE_FAILED, 
                        detail=f"网络连接中断，单个数据块读取超时{timeouts['chunk_timeout']}秒"
                    )
                
                if chunk:
                    f.write(chunk)
                    downloaded_size += len(chunk)
                    last_chunk_time = current_time
                    
                    # 检查文件大小是否超过限制
                    if downloaded_size > limit:
                        raise CustomException(
                            CustomError.FILE_SIZE_LIMIT_EXCEEDED, 
                            detail=f"{limit / 1024 / 1024:.2f} MB"
                        )
                    
                    # 更频繁的进度日志（5MB间隔）
                    if current_time - last_progress_time >= 30:  # 每30秒记录一次
                        logger.info(f"Downloaded {downloaded_size / 1024 / 1024:.1f}MB for {url}")
                        last_progress_time = current_time
                        
    except requests.exceptions.ChunkedEncodingError as e:
        raise CustomException(
            CustomError.DOWNLOAD_FILE_FAILED, 
            detail=f"数据传输错误：{str(e)}"
        )
    except Exception as e:
        if isinstance(e, CustomException):
            raise e
        raise CustomException(
            CustomError.DOWNLOAD_FILE_FAILED, 
            detail=f"下载过程中发生错误：{str(e)}"
        )


def _classify_download_error(error: Exception) -> str:
    """
    分类下载错误类型
    
    Args:
        error: 异常对象
    
    Returns:
        str: 错误类型 ('network', 'server', 'fatal', 'unknown')
    """
    if isinstance(error, CustomException):
        if error.err == CustomError.FILE_SIZE_LIMIT_EXCEEDED:
            return 'fatal'
        elif error.err == CustomError.DOWNLOAD_FILE_TIMEOUT:
            return 'network'
        else:
            return 'server'
    
    if isinstance(error, (requests.exceptions.ConnectionError, 
                         requests.exceptions.Timeout,
                         requests.exceptions.ChunkedEncodingError)):
        return 'network'
    
    if isinstance(error, requests.exceptions.HTTPError):
        status_code = getattr(error.response, 'status_code', None)
        if status_code in [500, 502, 503, 504]:  # 服务器错误
            return 'server'
        elif status_code in [404, 403, 401]:  # 客户端错误
            return 'fatal'
        else:
            return 'server'
    
    return 'unknown'


def _should_cleanup_on_error(error_category: str, supports_range: bool, consecutive_failures: int) -> bool:
    """
    决定错误后是否清理文件
    
    Args:
        error_category: 错误类型
        supports_range: 是否支持断点续传
        consecutive_failures: 连续失败次数
    
    Returns:
        bool: 是否应该清理文件
    """
    # 致命错误始终清理
    if error_category == 'fatal':
        return True
    
    # 不支持断点续传时清理
    if not supports_range:
        return True
    
    # 连续失败太多次时清理（可能是文件损坏）
    if consecutive_failures >= 3:
        return True
    
    # 网络和服务器错误保留文件
    return False


def _calculate_retry_delay(attempt: int, error_category: str, consecutive_failures: int) -> int:
    """
    计算重试等待时间
    
    Args:
        attempt: 当前尝试次数
        error_category: 错误类型
        consecutive_failures: 连续失败次数
    
    Returns:
        int: 等待时间（秒）
    """
    # 基础指数退避
    base_delay = min(2 ** attempt, MAX_RETRY_DELAY)
    
    # 根据错误类型调整
    if error_category == 'network':
        # 网络错误需要更长的等待时间
        multiplier = 1.5
    elif error_category == 'server':
        # 服务器错误稍微等待
        multiplier = 1.2
    else:
        multiplier = 1.0
    
    # 连续失败次数调整
    if consecutive_failures >= 3:
        multiplier *= 1.5
    
    final_delay = min(int(base_delay * multiplier), MAX_RETRY_DELAY)
    return max(final_delay, 1)  # 最少等待1秒