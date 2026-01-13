"""STIL 转换器日志模块

提供统一的日志记录功能，支持：
- 控制台输出
- 文件输出（自动轮转，超过 5MB 创建新文件）
- 不同日志级别
- 与 GUI progress_callback 集成
- 全局异常捕获
"""

import logging
import logging.handlers
import os
import sys
import traceback
import threading
from datetime import datetime
from typing import Optional, Callable


class STILLogger:
    """STIL 转换器日志类
    
    单例模式，全局共享一个日志实例
    """
    
    _instance: Optional['STILLogger'] = None
    _initialized: bool = False
    
    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self, 
                 name: str = "STIL",
                 log_file: Optional[str] = None,
                 level: int = logging.DEBUG,
                 console_output: bool = True,
                 file_output: bool = True):
        """初始化日志器
        
        Args:
            name: 日志器名称
            log_file: 日志文件路径（None 则自动生成）
            level: 日志级别
            console_output: 是否输出到控制台
            file_output: 是否输出到文件
        """
        if STILLogger._initialized:
            return
        
        self.name = name
        self.level = level
        self.console_output = console_output
        self.file_output = file_output
        self.progress_callback: Optional[Callable[[str], None]] = None
        
        # 创建 logger
        self.logger = logging.getLogger(name)
        self.logger.setLevel(level)
        self.logger.handlers.clear()  # 清除已有的 handlers
        
        # 日志格式
        formatter = logging.Formatter(
            '%(asctime)s [%(levelname)s] %(name)s: %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        
        # 简化格式（用于 GUI）
        self.simple_formatter = logging.Formatter('%(message)s')
        
        # 控制台 Handler
        if console_output:
            console_handler = logging.StreamHandler(sys.stdout)
            console_handler.setLevel(level)
            console_handler.setFormatter(formatter)
            self.logger.addHandler(console_handler)
        
        # 文件 Handler（使用 RotatingFileHandler 实现日志轮转）
        # 日志文件超过 5MB 时自动创建新文件，最多保留 5 个备份
        if file_output:
            if log_file is None:
                # 自动生成日志文件名
                log_dir = os.path.dirname(os.path.abspath(__file__))
                log_file = os.path.join(log_dir, f"stil_convert_{datetime.now().strftime('%Y%m%d')}.log")
            
            try:
                # RotatingFileHandler: 最大 5MB，保留 5 个备份文件
                # 文件命名: xxx.log, xxx.log.1, xxx.log.2, ..., xxx.log.5
                file_handler = logging.handlers.RotatingFileHandler(
                    log_file, 
                    maxBytes=5 * 1024 * 1024,  # 5MB
                    backupCount=5,             # 保留 5 个备份
                    encoding='utf-8'
                )
                file_handler.setLevel(level)
                file_handler.setFormatter(formatter)
                self.logger.addHandler(file_handler)
                self.log_file = log_file
            except Exception as e:
                print(f"无法创建日志文件 {log_file}: {e}")
                self.log_file = None
        else:
            self.log_file = None
        
        STILLogger._initialized = True
    
    def set_progress_callback(self, callback: Optional[Callable[[str], None]]) -> None:
        """设置 GUI 进度回调
        
        Args:
            callback: 进度回调函数
        """
        self.progress_callback = callback
    
    def set_level(self, level: int) -> None:
        """设置日志级别
        
        Args:
            level: 日志级别（logging.DEBUG, logging.INFO 等）
        """
        self.level = level
        self.logger.setLevel(level)
        for handler in self.logger.handlers:
            handler.setLevel(level)
    
    def _notify_gui(self, message: str, level: str = "INFO") -> None:
        """通知 GUI（通过 progress_callback）
        
        Args:
            message: 消息内容
            level: 日志级别
        """
        if self.progress_callback:
            if level in ("WARNING", "ERROR"):
                self.progress_callback(f"[{level}] {message}")
            else:
                self.progress_callback(message)
    
    def debug(self, message: str, notify_gui: bool = False) -> None:
        """DEBUG 级别日志"""
        self.logger.debug(message)
        if notify_gui:
            self._notify_gui(message, "DEBUG")
    
    def info(self, message: str, notify_gui: bool = True) -> None:
        """INFO 级别日志"""
        self.logger.info(message)
        if notify_gui:
            self._notify_gui(message, "INFO")
    
    def warning(self, message: str, notify_gui: bool = True) -> None:
        """WARNING 级别日志"""
        self.logger.warning(message)
        if notify_gui:
            self._notify_gui(message, "WARNING")
    
    def error(self, message: str, notify_gui: bool = True, exc_info: bool = False) -> None:
        """ERROR 级别日志
        
        Args:
            message: 错误消息
            notify_gui: 是否通知 GUI
            exc_info: 是否包含异常堆栈信息
        """
        self.logger.error(message, exc_info=exc_info)
        if notify_gui:
            self._notify_gui(message, "ERROR")
    
    def exception(self, message: str, notify_gui: bool = True) -> None:
        """记录异常信息（自动包含堆栈）"""
        self.logger.exception(message)
        if notify_gui:
            self._notify_gui(message, "ERROR")
    
    def install_global_exception_handler(self) -> None:
        """安装全局异常处理器
        
        捕获所有未处理的异常，包括：
        - 主线程异常
        - 子线程异常
        """
        # 保存原始的异常处理器
        self._original_excepthook = sys.excepthook
        self._original_threading_excepthook = getattr(threading, 'excepthook', None)
        
        def global_exception_handler(exc_type, exc_value, exc_tb):
            """全局异常处理器"""
            if issubclass(exc_type, KeyboardInterrupt):
                # 键盘中断不记录
                sys.__excepthook__(exc_type, exc_value, exc_tb)
                return
            
            # 格式化异常信息
            tb_lines = traceback.format_exception(exc_type, exc_value, exc_tb)
            tb_text = ''.join(tb_lines)
            
            # 记录到日志
            error_msg = f"未捕获的异常: {exc_type.__name__}: {exc_value}"
            self.logger.error(error_msg)
            self.logger.error(f"堆栈信息:\n{tb_text}")
            
            # 通知 GUI
            if self.progress_callback:
                self.progress_callback(f"[ERROR] {error_msg}")
                # 只显示最后几行堆栈
                tb_short = tb_lines[-3:] if len(tb_lines) > 3 else tb_lines
                self.progress_callback(f"Stack: {''.join(tb_short)}")
        
        def threading_exception_handler(args):
            """线程异常处理器"""
            exc_type = args.exc_type
            exc_value = args.exc_value
            exc_tb = args.exc_traceback
            thread = args.thread
            
            if issubclass(exc_type, KeyboardInterrupt):
                return
            
            # 格式化异常信息
            tb_lines = traceback.format_exception(exc_type, exc_value, exc_tb)
            tb_text = ''.join(tb_lines)
            
            thread_name = thread.name if thread else "Unknown"
            error_msg = f"线程 '{thread_name}' 未捕获的异常: {exc_type.__name__}: {exc_value}"
            self.logger.error(error_msg)
            self.logger.error(f"堆栈信息:\n{tb_text}")
            
            # 通知 GUI
            if self.progress_callback:
                self.progress_callback(f"[ERROR] {error_msg}")
        
        # 安装处理器
        sys.excepthook = global_exception_handler
        threading.excepthook = threading_exception_handler
        
        self.logger.info("全局异常处理器已安装")
    
    def uninstall_global_exception_handler(self) -> None:
        """卸载全局异常处理器"""
        if hasattr(self, '_original_excepthook') and self._original_excepthook:
            sys.excepthook = self._original_excepthook
        if hasattr(self, '_original_threading_excepthook') and self._original_threading_excepthook:
            threading.excepthook = self._original_threading_excepthook
    
    @classmethod
    def reset(cls) -> None:
        """重置日志器（主要用于测试）"""
        if cls._instance:
            cls._instance.uninstall_global_exception_handler()
            if cls._instance.logger:
                cls._instance.logger.handlers.clear()
        cls._instance = None
        cls._initialized = False


# 全局日志实例
_logger: Optional[STILLogger] = None


def get_logger(name: str = "STIL", **kwargs) -> STILLogger:
    """获取日志器实例
    
    Args:
        name: 日志器名称
        **kwargs: 传递给 STILLogger 的参数
        
    Returns:
        STILLogger 实例
    """
    global _logger
    if _logger is None:
        _logger = STILLogger(name=name, **kwargs)
    return _logger


def debug(message: str, notify_gui: bool = False) -> None:
    """DEBUG 级别日志"""
    get_logger().debug(message, notify_gui)


def info(message: str, notify_gui: bool = True) -> None:
    """INFO 级别日志"""
    get_logger().info(message, notify_gui)


def warning(message: str, notify_gui: bool = True) -> None:
    """WARNING 级别日志"""
    get_logger().warning(message, notify_gui)


def error(message: str, notify_gui: bool = True, exc_info: bool = False) -> None:
    """ERROR 级别日志"""
    get_logger().error(message, notify_gui, exc_info)


def exception(message: str, notify_gui: bool = True) -> None:
    """记录异常信息"""
    get_logger().exception(message, notify_gui)


def set_progress_callback(callback: Optional[Callable[[str], None]]) -> None:
    """设置 GUI 进度回调"""
    get_logger().set_progress_callback(callback)


def set_level(level: int) -> None:
    """设置日志级别"""
    get_logger().set_level(level)


def install_global_exception_handler() -> None:
    """安装全局异常处理器"""
    get_logger().install_global_exception_handler()


def uninstall_global_exception_handler() -> None:
    """卸载全局异常处理器"""
    get_logger().uninstall_global_exception_handler()

