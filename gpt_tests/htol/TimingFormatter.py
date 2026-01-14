"""Timing格式转换器

将STIL的Timing信息转换成VCT自定义格式。

目标格式示例:
RRADR 0
REP_RATE 100

CLOCK0 <0,1,2> 0
STROBE0 <3,4> 25,75
"""

import os
import sys
from typing import Dict, List, Optional, Set, Tuple

# 添加父目录到路径
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from TimingData import TimingData
from htol.TimeUnitConverter import TimeUnitConverter


class TimingFormatter:
    """Timing格式转换器"""
    
    def __init__(self, 
                 signal_groups: Dict[str, List[str]] = None,
                 signal_to_channels: Dict[str, List[int]] = None):
        """初始化转换器"""
        self.signal_groups = signal_groups or {}
        self.signal_to_channels = signal_to_channels or {}
        self.time_converter = TimeUnitConverter(default_output_unit="ns")
        
        # 波形表编号映射
        self.wft_to_rradr: Dict[str, int] = {}
        self.next_rradr = 0
    
    def set_signal_groups(self, signal_groups: Dict[str, List[str]]) -> None:
        """设置信号组映射"""
        self.signal_groups = signal_groups
    
    def set_channel_mapping(self, signal_to_channels: Dict[str, List[int]]) -> None:
        """设置信号到通道映射"""
        self.signal_to_channels = signal_to_channels
    
    def get_rradr_number(self, wft_name: str) -> int:
        """获取波形表对应的RRADR编号 (0-7)"""
        if wft_name not in self.wft_to_rradr:
            if self.next_rradr >= 8:
                raise ValueError(f"RRADR编号超过最大值7，无法为 {wft_name} 分配编号")
            self.wft_to_rradr[wft_name] = self.next_rradr
            self.next_rradr += 1
        return self.wft_to_rradr[wft_name]
    
    def get_channels_for_signal(self, signal_name: str) -> List[int]:
        """获取信号对应的所有通道号"""
        channels: List[int] = []
        
        if signal_name in self.signal_groups:
            for sig in self.signal_groups[signal_name]:
                if sig in self.signal_to_channels:
                    channels.extend(self.signal_to_channels[sig])
        elif signal_name in self.signal_to_channels:
            channels.extend(self.signal_to_channels[signal_name])
        
        return sorted(set(channels))
    
    def extract_middle_edges(self, timing_data: TimingData) -> Tuple[Optional[int], Optional[int]]:
        """从TimingData中提取中间两个沿的时间值（转换为ns整数）
        
        注意：只有时间和沿内容都存在时才算有效的沿
        """
        edges = []
        
        # 只有当时间和沿内容都存在时才算有效的沿
        if timing_data.t1 and timing_data.e1:
            edges.append(timing_data.t1)
        if timing_data.t2 and timing_data.e2:
            edges.append(timing_data.t2)
        if timing_data.t3 and timing_data.e3:
            edges.append(timing_data.t3)
        if timing_data.t4 and timing_data.e4:
            edges.append(timing_data.t4)
        
        if len(edges) == 0:
            return (None, None)
        elif len(edges) == 1:
            ns_val = self.time_converter.convert_string_to_int(edges[0])
            return (ns_val, None)
        elif len(edges) == 2:
            ns_val1 = self.time_converter.convert_string_to_int(edges[0])
            ns_val2 = self.time_converter.convert_string_to_int(edges[1])
            return (ns_val1, ns_val2)
        else:
            ns_val1 = self.time_converter.convert_string_to_int(edges[1])
            ns_val2 = self.time_converter.convert_string_to_int(edges[2])
            return (ns_val1, ns_val2)
    
    def format_channels(self, channels: List[int]) -> str:
        """格式化通道号列表
        
        连续的数字使用"-"连接，如 3,4,5,6,7 -> 3-7
        非连续的数字用逗号分隔
        """
        if not channels:
            return "<>"
        
        # 排序并去重
        sorted_channels = sorted(set(channels))
        
        if len(sorted_channels) == 1:
            return f"<{sorted_channels[0]}>"
        
        # 找出连续区间
        ranges = []
        start = sorted_channels[0]
        end = sorted_channels[0]
        
        for i in range(1, len(sorted_channels)):
            if sorted_channels[i] == end + 1:
                # 连续，扩展区间
                end = sorted_channels[i]
            else:
                # 不连续，保存当前区间，开始新区间
                ranges.append((start, end))
                start = sorted_channels[i]
                end = sorted_channels[i]
        
        # 保存最后一个区间
        ranges.append((start, end))
        
        # 格式化输出
        parts = []
        for start, end in ranges:
            if start == end:
                # 单个数字
                parts.append(str(start))
            elif end - start == 1:
                # 两个连续数字，不用"-"
                parts.append(f"{start},{end}")
            else:
                # 3个或以上连续数字，用"-"
                parts.append(f"{start}-{end}")
        
        return "<" + ",".join(parts) + ">"
    
    def format_edges(self, edge1: Optional[int], edge2: Optional[int]) -> str:
        """格式化沿值"""
        if edge1 is None:
            return "0"
        elif edge2 is None:
            return str(edge1)
        else:
            return f"{edge1},{edge2}"
    
    def format_timing_group(self, wft_name: str, timing_list: List[TimingData]) -> str:
        """格式化一个波形表的Timing定义"""
        lines = []
        
        rradr = self.get_rradr_number(wft_name)
        lines.append(f"RRADR {rradr}")
        
        if timing_list and timing_list[0].period:
            period_ns = self.time_converter.convert_string_to_int(timing_list[0].period)
            lines.append(f"REP_RATE {period_ns}")
        
        lines.append("")
        
        processed_signals_clock: Set[str] = set()
        processed_signals_strobe: Set[str] = set()
        
        clock_lines: List[str] = []
        strobe_lines: List[str] = []
        
        for td in timing_list:
            
            signal = td.signal
            if not signal:
                continue
            
            channels = self.get_channels_for_signal(signal)
            if not channels:
                continue
            
            edge1, edge2 = self.extract_middle_edges(td)
            
            # 如果td.is_strobe == 2，则认为既是strobe又是clock
            if td.is_strobe == 2:
                if signal not in processed_signals_clock and td.edge_format:
                    processed_signals_clock.add(signal)
                    channel_str = self.format_channels(channels)
                    edge_str = self.format_edges(edge1, edge2)
                    clock_lines.append(f"CLOCK{rradr} {channel_str} {edge_str}")
                    clock_lines.append(f"FORMAT {channel_str} {td.edge_format}")
                if signal not in processed_signals_strobe:
                    processed_signals_strobe.add(signal)
                    channel_str = self.format_channels(channels)
                    edge_str = self.format_edges(edge1, edge2)
                    strobe_lines.append(f"STROBE{rradr} {channel_str} {edge_str}")
            # 使用 TimingData 的属性判断
            elif td.is_strobe == 0:
                if signal not in processed_signals_strobe:
                    processed_signals_strobe.add(signal)
                    channel_str = self.format_channels(channels)
                    edge_str = self.format_edges(edge1, edge2)
                    strobe_lines.append(f"STROBE{rradr} {channel_str} {edge_str}")
            elif td.is_strobe == 1:
                if signal not in processed_signals_clock:
                    processed_signals_clock.add(signal)
                    channel_str = self.format_channels(channels)
                    edge_str = self.format_edges(edge1, edge2)
                    clock_lines.append(f"CLOCK{rradr} {channel_str} {edge_str}")
                    if td.edge_format:
                        clock_lines.append(f"FORMAT {channel_str} {td.edge_format}")

        
        lines.extend(clock_lines)
        lines.extend(strobe_lines)
        
        return "\n".join(lines)
    
    def format_all_timings(self, timings: Dict[str, List[TimingData]]) -> str:
        """格式化所有Timing定义"""
        self.wft_to_rradr.clear()
        self.next_rradr = 0
        
        result_parts = []
        
        for wft_name, timing_list in timings.items():
            formatted = self.format_timing_group(wft_name, timing_list)
            result_parts.append(formatted)
        
        return "\n\n".join(result_parts)
    
    def get_wft_mapping(self) -> Dict[str, int]:
        """获取波形表到RRADR编号的映射"""
        return self.wft_to_rradr.copy()
    
    # ========================== Vector字符替换相关 ==========================
    # 
    # 注意：Vector 替换逻辑现在基于 TimingData 的属性：
    # - td.is_strobe: 是否是比较沿
    # - td.edge_format: 边沿格式 (NRZ/DNRZ/RZ/RO)
    # - td.vector_replacement: 替换字符 (P/N/空)
    # - td.wfc: 波形字符
    #
    # 在生成 Vector 时，根据当前波形表找到对应的 TimingData，
    # 然后使用 td.vector_replacement 来决定是否替换。

