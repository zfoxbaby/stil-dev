from __future__ import annotations

from ast import Tuple
import os
import sys
from typing import List, Dict

class STILEventHandler:
    """Pattern 解析事件处理接口
    
    所有格式生成器（如 STILToVCTStream、STILToGascStream）都应继承此类
    并实现相应的回调方法。
    """
    
    def on_parse_start(self) -> None:
        """解析开始时调用"""
        pass
    
    def on_header(self, header: Dict[str, str]) -> None:
        """header 信息，包含标题、日期、源码、注释历史"""
        pass

    def on_waveform_change(self, wft_name: str) -> None:
        """波形表切换时调用（W 语句）
        
        Args:
            wft_name: 波形表名称
        """
        pass
    
    def on_vector_start(self, pattern_burst_name: str) -> None:
        """解析开始时调用"""
        pass

    def on_annotation(self, annotation: str) -> None:
        """注释时调用
        
        Args:
            annotation: 注释内容
        """
        pass

    def on_label(self, label_name: str) -> None:
        """遇到标签时调用
        
        Args:
            label_name: 标签名称（已去除引号和冒号）
        """
        pass
    
    def on_vector(self, vec_data_list: List[Tuple[str, str]], 
                  instr: str = "", param: str = "") -> None:
        """遇到向量数据时调用
        
        Args:
            vec_data_list: [(signal_or_group, wfc_string), ...] 列表
            instr: 微指令名称（如 "", "Call", "Stop"）
            param: 微指令参数
        """
        pass
    
    def on_procedure_call(self, proc_name: str, proc_content: str = "", vector_address: int = 0) -> None:
        """Call 指令时调用
        
        Args:
            proc_name: Procedure 名称
            proc_content: Procedure 内容（如果找到）
            vector_address: 向量地址
        """
        pass
    
    def on_micro_instruction(self, label: str, instr: str, param: str = "", vector_address: int = 0) -> None:
        """其他微指令时调用（Stop, Goto, IddqTestPoint 等）
        
        Args:
            instr: 微指令名称
            param: 微指令参数
            vector_address: 向量地址
        """
        pass
    
    def on_parse_complete(self, vector_count: int) -> None:
        """解析完成时调用
        
        Args:
            vector_count: 解析的向量总数
        """
        pass

    def on_log(self, log: str) -> None:
        """解析日志"""
        pass

    def on_parse_error(self, error_msg: str, statement: str = "") -> None:
        """解析错误时调用
        
        Args:
            error_msg: 错误信息
            statement: 导致错误的语句
        """
        pass