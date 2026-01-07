"""STIL解析通用工具模块

提供STIL文件解析的通用功能，包括：
- 信号提取
- 信号组提取
- Timing解析

供 STILToGascStream 和 STILToVCTStream 共用。
"""

from __future__ import annotations

from ast import Tuple
import os
import sys
from typing import List, Dict
from lark import Tree, Token
from typing import Optional, Callable
from TimingData import TimingData
from STILEventHandler import STILEventHandler

try:
    from Semi_ATE.STIL.parsers.STILParser import STILParser
except ImportError:
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, repo_root)
    from Semi_ATE.STIL.parsers.STILParser import STILParser

class STILParserUtils:
    """STIL解析通用工具类"""
    
    def __init__(self, debug: bool = False):
        """初始化
        
        Args:
            debug: 是否开启调试模式
        """
        self.debug = debug
    
    # ========================== 信号提取 ==========================
    
    def extract_signals(self, tree: Tree) -> Dict[str, str]:
        """从Signals块提取信号名称和类型
        
        Args:
            tree: 解析树
            
        Returns:
            {信号名: 信号类型} 映射，信号类型: In/Out/InOut/Supply/Pseudo
        """
        signals: Dict[str, str] = {}
        for node in tree.find_data("b_signals__signals_list"):
            signal_name = ""
            signal_type = ""
            
            # 提取信号名和类型
            for child in node.children:
                if isinstance(child, Token):
                    if child.type == "b_signals__SIGNAL_NAME":
                        signal_name = child.value.strip("\"")
                    elif child.type == "b_signals__SIGNAL_TYPE":
                        signal_type = child.value
            
            if signal_name:
                signals[signal_name] = signal_type
        
        return signals
    
    def extract_signal_groups(self, tree: Tree) -> Dict[str, List[str]]:
        """从SignalGroups块提取信号组映射关系
        
        Args:
            tree: 解析树
            
        Returns:
            {组名: [信号列表]} 映射
        """
        groups: Dict[str, List[str]] = {}
        
        for node in tree.find_data("signal_groups_block"):
            if isinstance(node.children[1], Token):
                name_ref = node.children[1].value
            else:
                name_ref = ""
            
            for sub_node in node.find_data("b_signal_groups__signal_groups_list"):
                tokens = [c for c in sub_node.children if isinstance(c, Token)]
                if len(tokens) < 2:
                    continue
                name = tokens[0].value
                sigs: List[str] = [tokens[1].value.strip("\"")]
                
                for vb in sub_node.find_data("b_signal_groups__sigref_expr"):
                    for n in vb.children:
                        if isinstance(n, Token) and n.type == "b_signal_groups__SIGREF_NAME":
                            sigs.append(n.value.strip("\""))
                
                if name_ref != "":
                    groups[name_ref + "." + name] = sigs
                else:
                    groups[name] = sigs
        return groups
    
    # ========================== Timing解析 ==========================
    
    def extract_timings(self, tree: Tree, signal_types: Dict[str, str] = None,
     signal_groups: Dict[str, List[str]] = None,
     handler: STILEventHandler = None) -> Dict[str, List[TimingData]]:
        """从Timing块提取Timing信息
        
        Args:
            tree: 解析树
            signal_types: 信号类型映射 {信号名: 信号类型}
            
        Returns:
            {波形表名: [TimingData列表]} 映射
        """
        if signal_types is None:
            signal_types = {}
        
        timings: Dict[str, List[TimingData]] = {}
        
        for node in tree.find_data("timing_block"):
            for wft_node in node.find_data("b_timing__waveform_table"):
                wft = ""
                period = ""
                for child in wft_node.children:
                    if isinstance(child, Token) and child.type == "b_timing__WFT_NAME":
                        wft = child.value
                    if (isinstance(child, Tree)
                        and child.data == "b_timing__period"
                        and len(child.children) == 2):
                        if isinstance(child.children[1], Token):
                            period = child.children[1].value.replace("'", "")
                
                timings.setdefault(wft, [])
                
                for child in wft_node.find_data("b_timing__waveforms_list"):
                    time_values: List[str] = []
                    edge_values: List[str] = []
                    timing_data = TimingData()
                    timing_data.wft = wft
                    timing_data.period = period
                    
                    for subchild in child.children:
                        if isinstance(subchild, Token) and subchild.type == "b_timing__WF_SIGREF_EXPR":
                            timing_data.signal = subchild.value
                        if isinstance(subchild, Token) and subchild.type == "b_timing__WFC_LIST":
                            timing_data.wfc = subchild.value
                        if (isinstance(subchild, Tree)
                            and subchild.data == "b_timing__time_offset"
                            and len(subchild.children) == 2):
                            self._process_single_time_offset(subchild, timing_data, time_values, edge_values)
                        if isinstance(subchild, Tree) and subchild.data == "b_timing__close_wfcs_block":
                            self._assign_timing_data(timing_data, time_values, edge_values)
                            timing_list = self._split_timing_data(timing_data, signal_types,
                             signal_groups, handler)
                            timings[wft].extend(timing_list)
                            time_values.clear()
                            edge_values.clear()
                            parent_signal_name = timing_data.signal
                            timing_data = TimingData()
                            timing_data.wft = wft
                            timing_data.signal = parent_signal_name
                            timing_data.period = period
        return timings
    
    def _split_timing_data(self, timing_data: TimingData,
     signal_types: Dict[str, str] = None,
     signal_groups: Dict[str, List[str]] = None, 
     handler: STILEventHandler = None) -> List[TimingData]:
        """拆分包含多个wfc字符的TimingData
        
        Args:
            timing_data: 原始TimingData
            signal_types: 信号类型映射 {信号名: 信号类型}
            
        Returns:
            拆分后的TimingData列表
        """
        if signal_types is None:
            signal_types = {}
        
        timing_data_list: List[TimingData] = []
        
        if len(timing_data.wfc) > 1:
            edge1 = timing_data.e1 if len(timing_data.e1) == len(timing_data.wfc) else timing_data.e1 * len(timing_data.wfc)
            if edge1.strip():
                for i in range(len(timing_data.wfc)):
                    timing_data_child = TimingData()
                    timing_data_child.parent = timing_data
                    timing_data_child.wft = timing_data.wft
                    timing_data_child.period = timing_data.period
                    timing_data_child.signal = timing_data.signal
                    timing_data_child.wfc = timing_data.wfc[i:i+1]
                    timing_data_child.t1 = timing_data.t1
                    timing_data_child.e1 = edge1[i:i+1]
                    timing_data_list.append(timing_data_child)
                    timing_data.twas.append(timing_data_child)
            
            edge2 = timing_data.e2 if len(timing_data.e2) == len(timing_data.wfc) else timing_data.e2 * len(timing_data.wfc)
            if edge2.strip() and timing_data_list:
                for i in range(len(timing_data_list)):
                    timing_data_list[i].t2 = timing_data.t2
                    timing_data_list[i].e2 = edge2[i:i+1]
            
            edge3 = timing_data.e3 if len(timing_data.e3) == len(timing_data.wfc) else timing_data.e3 * len(timing_data.wfc)
            if edge3.strip() and timing_data_list:
                for i in range(len(timing_data_list)):
                    timing_data_list[i].t3 = timing_data.t3
                    timing_data_list[i].e3 = edge3[i:i+1]
            
            edge4 = timing_data.e4 if len(timing_data.e4) == len(timing_data.wfc) else timing_data.e4 * len(timing_data.wfc)
            if edge4.strip() and timing_data_list:
                for i in range(len(timing_data_list)):
                    timing_data_list[i].t4 = timing_data.t4
                    timing_data_list[i].e4 = edge4[i:i+1]
        else:
            timing_data_list.append(timing_data)
        
        # 为每个 TimingData 计算属性（is_strobe, edge_format, vector_replacement）
        # 根据信号类型判断是否是 STROBE
        signal_name = timing_data.signal
        if timing_data.signal in signal_groups:
            signal_names = signal_groups.get(timing_data.signal, "")
            signal_name = signal_names[0];
        signal_type = signal_types.get(signal_name, "")
        timing_data.compute_timing_properties(signal_type=signal_type, handler=handler)
        for td in timing_data_list:
            td.compute_timing_properties(signal_type=signal_type, handler=handler)
        
        return timing_data_list
    
    def _process_single_time_offset(self, time_offset_node: Tree,
            timing_data: TimingData, time_values: List[str], edge_values: List[str]) -> None:
        """处理单个time_offset节点，提取所有time/edge对
        
        Args:
            time_offset_node: time_offset节点
            timing_data: TimingData对象
            time_values: 时间值列表（输出）
            edge_values: 边沿值列表（输出）
        """
        for child in time_offset_node.children:
            if isinstance(child, Token) and child.type == "b_timing__TIME_EXPR":
                time_values.append(child.value)
            if isinstance(child, Token) and child.type == "b_timing__EVENT":
                edge_values.append(child.value)
            if isinstance(child, Tree) and child.data == "b_timing__events":
                edges = ""
                for subchild in child.children:
                    if isinstance(subchild, Token) and subchild.type == "b_timing__EVENT":
                        edges += subchild.value
                edge_values.append(edges)
    
    def _assign_timing_data(self, timing_data: TimingData, times: List[str], edges: List[str]) -> None:
        """将时间和边沿数据分配到TimingData对象的相应字段
        
        Args:
            timing_data: TimingData对象
            times: 时间值列表
            edges: 边沿值列表
        """
        max_pairs = min(4, len(times), len(edges))
        for i in range(max_pairs):
            time_attr = f"t{i+1}"
            edge_attr = f"e{i+1}"
            if hasattr(timing_data, time_attr) and hasattr(timing_data, edge_attr):
                setattr(timing_data, time_attr, times[i].replace("'", ""))
                setattr(timing_data, edge_attr, edges[i])


# 全局默认实例
_default_utils: STILParserUtils = None


def get_default_utils() -> STILParserUtils:
    """获取全局默认工具实例"""
    global _default_utils
    if _default_utils is None:
        _default_utils = STILParserUtils()
    return _default_utils


# 便捷函数
def extract_signals(tree: Tree) -> Dict[str, str]:
    """提取信号和类型"""
    return get_default_utils().extract_signals(tree)


def extract_signal_groups(tree: Tree) -> Dict[str, List[str]]:
    """提取信号组"""
    return get_default_utils().extract_signal_groups(tree)