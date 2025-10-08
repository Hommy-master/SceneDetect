import os
import requests
import mimetypes
import datetime
import uuid
from typing import Dict, Any, Optional
from logger import logger
from exceptions import CustomException, CustomError
import subprocess
import json


def download(url, save_dir, limit=100*1024*1024, timeout=180) -> str:
    """
    下载文件并根据Content-Type判断文件类型
    
    Args:
        url: 文件的URL地址
        save_dir: 文件保存目录
        filename: 文件名
        limit: 文件大小限制（字节），默认512MB
        timeout: 整体下载超时时间（秒），默认3分钟
    
    Returns:
        完整的文件路径

    Raises:
        CustomException: 自定义异常
    """
    # 1. 生成文件名
    save_path = os.path.join(save_dir, gen_unique_id())

    try:
        # 1. 发送GET请求下载文件
        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.114 Safari/537.36',
            'Accept': '*/*',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8'
        }
        response = requests.get(url, stream=True, timeout=timeout, headers=headers)
        response.raise_for_status()
        
        # 2. 获取Content-Type，判断文件类型
        content_type = response.headers.get('Content-Type', '').split(';')[0].strip()
        
        # 如果没有扩展名，则根据Content-Type猜测扩展名
        extension = mimetypes.guess_extension(content_type)
        if extension:
            save_path += extension

        # 3. 下载文件并实时检查大小
        downloaded_size = 0
        with open(save_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
                    downloaded_size += len(chunk)
                    
                    # 检查文件大小是否超过限制
                    if downloaded_size > limit:
                        # 删除部分下载的文件
                        f.close()
                        os.remove(save_path)
                        
                        logger.info(f"Download failed, url: {url}, error: File size exceeds the limit of {limit/1024/1024:.2f}MB")
                        raise CustomException(CustomError.FILE_SIZE_LIMIT_EXCEEDED, detail=f"{limit/1024/1024:.2f} MB")
        
        # 4. 验证下载完整性（如果服务器提供了Content-Length）
        content_length = response.headers.get('Content-Length')
        if content_length and os.path.getsize(save_path) != int(content_length):
            os.remove(save_path)
            logger.warning(f"Download failed, url: {url}, error: File download incomplete: expected {content_length} bytes, actual {os.path.getsize(save_path)} bytes")
            raise CustomException(CustomError.DOWNLOAD_FILE_FAILED)
        
        logger.info(f"Download success, url: {url}, save_path: {save_path}")
        return save_path
    except Exception as e:
        # 清理可能已部分下载的文件
        if os.path.exists(save_path):
            os.remove(save_path)
        logger.warning(f"Download failed, url: {url}, error: {str(e)}")
        raise CustomException(CustomError.DOWNLOAD_FILE_FAILED)

def gen_unique_id() -> str:
    """
    生成唯一ID
    """
    timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
    unique_id = uuid.uuid4().hex[:8]

    return f"{timestamp}{unique_id}"

def get_user_points(api_key: str) -> float:
    """
    根据API Key获取用户积分
    
    Args:
        api_key: 用户的API Key
    
    Returns:
        用户当前积分（float类型）
    
    Raises:
        CustomException: 当获取积分失败时
    """
    try:
        # 调用获取积分API
        params = {'apiKey': api_key}
        result = _call_user_api('GET', '/points', params=params)
        
        # 提取积分数据，仅当code为0时，data字段才有值
        code = result.get('code')
        if code == 0:
            # 确保返回float类型
            try:
                points = result.get('data', {}).get('points', 0.0)
                points_float = float(points)
                logger.info(f"Successfully retrieved user points: {points_float} for API key: {api_key[:8]}...")
                return points_float
            except (ValueError, TypeError):
                logger.error(f"Invalid points format in API response, result: {result}")
                raise CustomException(CustomError.INTERNAL_SERVER_ERROR, detail="积分格式错误")
        elif code == 21002 or code == 400: # API Key无效
            logger.error(f"Failed to get user points: {result}, code: {code}")
            raise CustomException(CustomError.INVALID_APIKEY, detail=f"{api_key}")
        else:
            logger.error(f"Failed to get user points: {result}, code: {code}")
            raise CustomException(CustomError.UNKNOWN_ERROR, detail=f"获取用户积分时发生未知错误: {result}, code: {code}")
    except CustomException:
        # 重新抛出自定义异常
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
        True表示扣减成功
    
    Raises:
        CustomException: 当扣减积分失败时
    """
    try:
        # 调用扣减积分API
        json_data = {
            'apiKey': api_key,
            'points': float(points),
            'desc': desc.strip()
        }
        
        result = _call_user_api('POST', '/points/deduct', json_data=json_data)
        code = result.get('code')
        if code == 0:
            logger.info(f"Successfully deducted {points} points for API key {api_key}..., reason: {desc}")
            return True
        elif code == 21002:
            logger.error(f"Failed to deduct points: {result}, code: {code}")
            raise CustomException(CustomError.INVALID_APIKEY, detail=f"API Key无效: {api_key}...")
        else:
            logger.error(f"Failed to deduct points: {result}, code: {code}")
            return False
    except CustomException as e:
        logger.warning(f"Deduct points failed, API key: {api_key}..., error: {str(e)}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error deducting points for API key {api_key}...: {str(e)}")
        return False

def _call_user_api(method: str, endpoint: str, params: Optional[dict] = None, json_data: Optional[dict] = None, timeout: int = 30) -> Dict[str, Any]:
    """
    调用用户积分相关API的通用方法
    
    Args:
        method: HTTP方法 ('GET' 或 'POST')
        endpoint: API端点路径
        params: 查询参数（用于GET请求）
        json_data: JSON数据（用于POST请求）
        timeout: 请求超时时间（秒）
    
    Returns:
        API响应的JSON数据
    
    Raises:
        CustomException: 当API调用失败或返回错误时
    """
    base_url = "https://user.jcaigc.cn/openapi/user/v1"
    url = f"{base_url}{endpoint}"
    
    headers = {
        'User-Agent': 'SceneDetect/1.0',
        'Accept': 'application/json',
        'Content-Type': 'application/json'
    }
    
    try:
        logger.info(f"Calling user API: {method} {url}")
        
        if method.upper() == 'GET':
            response = requests.get(url, params=params, headers=headers, timeout=timeout)
        elif method.upper() == 'POST':
            response = requests.post(url, json=json_data, headers=headers, timeout=timeout)
        else:
            raise ValueError(f"Unsupported HTTP method: {method}")
        
        response.raise_for_status()
        
        # 解析JSON响应
        try:
            result = response.json()
            return result
        except ValueError as e:
            logger.error(f"Failed to parse API response as JSON: {response.text}")
            raise CustomException(CustomError.INTERNAL_SERVER_ERROR, detail="API响应格式错误")
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
        # 重新抛出自定义异常
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
        duration: 音/视频时长，单位：秒
    
    Raises:
        CustomException: 音/视频分析失败
    """
    logger.info(f"Using ffprobe to analyze file: {file_path}")
    
    try:
        # 构建ffprobe命令 - 根据记忆中的配置
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
            timeout=30,
            check=True
        )
        
        logger.info("FFprobe analysis completed successfully")
        
        # 调试信息：检查result的内容
        logger.info(f"FFprobe result.stdout type: {type(result.stdout)}, value: {repr(result.stdout[:100] if result.stdout else 'None')}")
        logger.info(f"FFprobe result.stderr type: {type(result.stderr)}, value: {repr(result.stderr[:100] if result.stderr else 'None')}")
        
        # 检查stdout是否为None或为空（编码问题可能导致这个情况）
        if result.stdout is None or not result.stdout.strip():
            logger.warning("FFprobe stdout is None or empty, likely due to encoding issues, trying binary mode")
            return _analyze_audio_with_ffprobe_binary(file_path)
        
        # 解析ffprobe输出
        ffprobe_data = _parse_ffprobe_output(result.stdout)
        
        # 提取时长信息
        duration_seconds = _extract_duration_from_ffprobe_data(ffprobe_data)
        
        # 验证并转换时长
        return int(duration_seconds)
        
    except UnicodeDecodeError as e:
        logger.warning(f"FFprobe output encoding issue: {e}, trying binary mode")
        # 如果编码问题仍然存在，尝试使用二进制模式
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
        duration: 音频时长，单位：微秒
    
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
            timeout=30,
            check=True
        )
        
        # 手动解码，先尝试UTF-8，再尝试GBK
        stdout_text = None
        for encoding in ['utf-8', 'gbk', 'latin1']:
            try:
                stdout_text = result.stdout.decode(encoding)
                logger.info(f"Successfully decoded ffprobe output using {encoding} encoding")
                break
            except UnicodeDecodeError:
                continue
        
        if stdout_text is None:
            # 如果所有编码都失败，使用错误替换
            stdout_text = result.stdout.decode('utf-8', errors='replace')
            logger.warning("Used error replacement for ffprobe output decoding")
        
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