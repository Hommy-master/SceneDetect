import os
import requests
import mimetypes
import datetime
import uuid
import subprocess
import json
from typing import Dict, Any, Optional

from logger import logger
from exceptions import CustomException, CustomError

# 常量配置
DEFAULT_FILE_SIZE_LIMIT = 100 * 1024 * 1024  # 100MB
DEFAULT_DOWNLOAD_TIMEOUT = 180  # 3分钟
DEFAULT_API_TIMEOUT = 30  # 30秒
DEFAULT_FFPROBE_TIMEOUT = 30  # 30秒
DEFAULT_RETRY_COUNT = 2  # 默认重试次数
CHUNK_SIZE = 8192  # 8KB
USER_API_BASE_URL = "https://user.jcaigc.cn/openapi/user/v1"

# HTTP请求头
DOWNLOAD_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.114 Safari/537.36',
    'Accept': '*/*',
    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8'
}

API_HEADERS = {
    'User-Agent': 'SceneDetect/1.0',
    'Accept': 'application/json',
    'Content-Type': 'application/json'
}


def download(url: str, save_dir: str, limit: int = DEFAULT_FILE_SIZE_LIMIT, timeout: int = DEFAULT_DOWNLOAD_TIMEOUT, retry: int = DEFAULT_RETRY_COUNT) -> str:
    """
    下载文件并根据Content-Type判断文件类型，支持重试机制
    
    Args:
        url: 文件的URL地址
        save_dir: 文件保存目录
        limit: 文件大小限制（字节），默认100MB
        timeout: 整体下载超时时间（秒），默认3分钟
        retry: 下载失败时的重试次数，默认3次
    
    Returns:
        str: 完整的文件路径

    Raises:
        CustomException: 下载失败时抛出异常
    """
    last_exception = None
    
    for attempt in range(retry + 1):  # 总共尝试 retry + 1 次（包括第一次）
        # 每次尝试都生成新的文件名，避免冲突
        save_path = os.path.join(save_dir, gen_unique_id())
        
        try:
            logger.info(f"Downloading file, attempt {attempt + 1}/{retry + 1}, url: {url}")
            
            # 发送GET请求下载文件
            response = requests.get(url, stream=True, timeout=timeout, headers=DOWNLOAD_HEADERS)
            response.raise_for_status()
            
            # 获取并处理文件类型
            save_path = _determine_file_path_with_extension(response, save_path)
            
            # 下载文件并检查大小
            _download_file_with_size_check(response, save_path, limit, url)
            
            # 验证下载完整性
            _validate_download_integrity(response, save_path, url)
            
            logger.info(f"Download success on attempt {attempt + 1}, url: {url}, save_path: {save_path}")
            return save_path
            
        except Exception as e:
            # 清理可能已部分下载的文件
            if os.path.exists(save_path):
                try:
                    os.remove(save_path)
                    logger.debug(f"Cleaned up partial download file: {save_path}")
                except Exception as cleanup_error:
                    logger.warning(f"Failed to cleanup partial download file {save_path}: {cleanup_error}")
            
            last_exception = e
            
            # 如果是文件大小超限错误，不需要重试
            if isinstance(e, CustomException) and e.err == CustomError.FILE_SIZE_LIMIT_EXCEEDED:
                logger.error(f"File size limit exceeded, no retry needed, url: {url}")
                raise e
            
            # 如果不是最后一次尝试，记录警告并等待
            if attempt < retry:
                logger.warning(f"Download attempt {attempt + 1} failed, url: {url}, error: {str(e)}")
            else:
                logger.error(f"Download failed after {retry + 1} attempts, url: {url}, final error: {str(e)}")
    
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


def _download_file_with_size_check(response: requests.Response, save_path: str, limit: int, url: str) -> None:
    """
    下载文件并实时检查文件大小
    
    Args:
        response: HTTP响应对象
        save_path: 文件保存路径
        limit: 文件大小限制
        url: 文件URL（用于日志）
    
    Raises:
        CustomException: 文件大小超限时抛出
    """
    downloaded_size = 0
    
    with open(save_path, 'wb') as f:
        for chunk in response.iter_content(chunk_size=CHUNK_SIZE):
            if chunk:
                f.write(chunk)
                downloaded_size += len(chunk)
                
                # 检查文件大小是否超过限制
                if downloaded_size > limit:
                    f.close()
                    os.remove(save_path)
                    
                    limit_mb = limit / 1024 / 1024
                    logger.info(f"Download failed, url: {url}, error: File size exceeds the limit of {limit_mb:.2f}MB")
                    raise CustomException(CustomError.FILE_SIZE_LIMIT_EXCEEDED, detail=f"{limit_mb:.2f} MB")


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


def _cleanup_temp_file(temp_file_path: Optional[str]) -> None:
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
