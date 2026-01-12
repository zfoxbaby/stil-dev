"""Utility to convert STIL files to VCT format.

This module handles the conversion from STIL format to VCT format,
which supports multiple DUTs with channel mapping.

The VCT format requires:
1. Pin-to-channel mapping (user configured via Option dialog)
2. 256 channels (0-255) for vector data
3. Micro-instructions at the beginning of each vector line
"""

from __future__ import annotations

import os
import sys
from typing import List, Dict, Optional, Callable, Tuple

# 添加父目录到路径
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from TimingData import TimingData
from STILParserUtils import STILParserUtils
from STILEventHandler import STILEventHandler
from htol.TimingFormatter import TimingFormatter
from STILParserTransformer import PatternStreamParserTransformer, format_vct_instruction
import Logger

try:
    from Semi_ATE.STIL.parsers.STILParser import STILParser
except ImportError:
    repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    sys.path.insert(0, repo_root)
    from Semi_ATE.STIL.parsers.STILParser import STILParser


class STILToVCTStream(STILEventHandler):
    """Convert STIL files to VCT format - supports multiple DUTs with channel mapping."""

    def __init__(self, stil_file: str, target_file: str = "", 
                 progress_callback: Optional[Callable[[str], None]] = None, debug: bool = False):
        """初始化VCT转换器"""
        self.stil_file = stil_file
        self.target_file = target_file
        self.file_size = -1
        self.progress_callback = progress_callback
        self.debug = debug
        
        # 解析结果存储
        self.signals: Dict[str, str] = {}  # {信号名: 信号类型}
        self.signal_groups: Dict[str, List[str]] = {}
        # Timing数据
        self.timings: Dict[str, List[TimingData]] = {}
        
        # 用户配置的信号到通道映射
        self.signal_to_channels: Dict[str, List[int]] = {}

        # Vector生成相关
        self.current_wft: str = ""           # 当前波形表名
        self.wft_pending: bool = False       # 波形表是否刚切换
        self.wfc_replacement_map: Dict[Tuple[str, str, str], str] = {}  # WFC替换映射 {(wft, signal, wfc): replacement}
        self.output_file = None              # 输出文件句柄（在 generate_vct_vector_section 时设置）
        
        # 通用解析工具
        self.parser_utils = STILParserUtils(debug=debug)
        
        # Timing格式转换器
        self.timing_formatter = TimingFormatter()
        
        self.pattern_parser0 = PatternStreamParserTransformer(self.stil_file, self, self.debug)

        # 停止标志
        self._stop_requested = False

    def __del__(self):
        """析构时确保关闭文件流"""
        self.close()

    def close(self):
        if self.output_file and not self.output_file.closed:
            self.output_file.close()

    def stop(self) -> None:
        """请求停止转换"""
        self._stop_requested = True
        if self.pattern_parser0:
            self.pattern_parser0.stop()

    def read_stil_signals(self, print_log: bool = True) -> List[str]:
        """读取STIL文件，提取实际使用的信号列表"""
        used_signals = self.pattern_parser0.read_stil_overview(print_log=print_log)
        self.signals = self.pattern_parser0.get_signals()
        self.signal_groups = self.pattern_parser0.get_signal_groups()

        self.timings = self.pattern_parser0.get_timings()
        return used_signals

    def set_channel_mapping(self, mapping: Dict[str, List[int]]) -> None:
        """设置信号到通道的映射关系"""
        self.signal_to_channels = mapping

    def parse_channel_string(self, channel_str: str) -> List[int]:
        """解析通道号字符串"""
        if not channel_str or not channel_str.strip():
            return []
        
        channels = []
        parts = channel_str.split(',')
        
        for part in parts:
            part = part.strip()
            if part:
                try:
                    channel = int(part)
                    if 0 <= channel <= 255:
                        channels.append(channel)
                    else:
                        if self.progress_callback:
                            self.progress_callback(f"警告：通道号 {channel} 超出范围(0-255)，已忽略")
                except ValueError:
                    Logger.warning(f"警告：'{part}' 不是有效的数字，已忽略")
                    if self.progress_callback:
                        self.progress_callback(f"警告：'{part}' 不是有效的数字，已忽略")
        
        return channels

    def get_channel_mapping(self) -> Dict[str, List[int]]:
        """获取当前的通道映射配置"""
        return self.signal_to_channels
    
    def refresh_signals_and_remap(self, old_mapping: Dict[str, List[int]]) -> Dict:
        """重新读取信号并根据旧映射自动重新映射
        
        Args:
            old_mapping: 旧的信号到通道映射
            
        Returns:
            结果字典，包含：
            - success: bool - 是否成功
            - new_signals: List[str] - 新读取的信号列表
            - new_mapping: Dict[str, List[int]] - 新的映射
            - mapped_signals: List[str] - 成功映射的信号
            - unmapped_signals: List[str] - 未映射的新信号
            - removed_signals: List[str] - 已删除的旧信号
            - error: str - 错误信息（如果失败）
        """
        result = {
            'success': False,
            'new_signals': [],
            'new_mapping': {},
            'mapped_signals': [],
            'unmapped_signals': [],
            'removed_signals': [],
            'error': ''
        }
        
        try:
            # 重新读取信号
            new_signals = self.read_stil_signals(print_log=False)
            
            if not new_signals:
                result['error'] = '未能从STIL文件中提取到信号信息'
                return result
            
            result['new_signals'] = new_signals
            
            # 自动重新映射
            new_mapping = {}
            mapped_signals = []
            unmapped_signals = []
            
            for signal in new_signals:
                if signal in old_mapping:
                    # 信号在旧映射中存在，保留映射
                    new_mapping[signal] = old_mapping[signal]
                    mapped_signals.append(signal)
                else:
                    # 新信号，未映射
                    unmapped_signals.append(signal)
            
            # 检查旧映射中哪些信号不再存在
            removed_signals = [sig for sig in old_mapping.keys() if sig not in new_signals]
            
            # 更新转换器的映射
            self.signal_to_channels = new_mapping
            
            # 填充结果
            result['success'] = True
            result['new_mapping'] = new_mapping
            result['mapped_signals'] = mapped_signals
            result['unmapped_signals'] = unmapped_signals
            result['removed_signals'] = removed_signals
            
            return result
            
        except Exception as e:
            Logger.error(f"刷新信号映射失败: {e}", exc_info=True)
            result['error'] = str(e)
            return result

    # ========================== 微指令映射 ==========================
    
    def map_instruction(self, stil_instr: str, param: str = "") -> str:
        """映射并格式化微指令"""
        return format_vct_instruction(stil_instr, param)

    # ========================== VCT文件生成 ==========================
    
    def generate_vct_header(self) -> str:
        """生成VCT文件头部（第一部分）"""
        from datetime import datetime
        
        source_filename = os.path.basename(self.stil_file)
        now = datetime.now()
        date_str = now.strftime("%a %b %d %H:%M:%S %Y")
        
        lines = [
            ";",
            ";  HTOL vector file created by pat_convert.py translator",
            f";  from the source file {source_filename}",
            f";  translated {date_str}",
            ";",
            ""
        ]

        self.headers = self.pattern_parser0.get_headers()
        for header_name, header_content in self.headers.items():
            lines.append(f";  {header_name}: {header_content}")
        
        return "\n".join(lines)
    
    def generate_vct_timing_section(self) -> str:
        """生成VCT文件Timing部分"""
        if not self.timings:
            return ""
        
        lines = [
            ";",
            ";    Timing definitions:",
            ";"
        ]
        
        # 添加原始波形表信息
        for wft_name, timing_list in self.timings.items():
            lines.append(f";  Timing [{wft_name}] ({len(timing_list)} entries)")
            for td in timing_list:
                map_wfc = td.vector_replacement;
                if map_wfc:
                    timing_str = f";    {td.signal}, {td.period}, {td.wfc}{("="+map_wfc) if map_wfc else ''}, {td.t1}, {td.e1}"
                    if td.t2:
                        timing_str += f", {td.t2}, {td.e2}"
                    if td.t3:
                        timing_str += f", {td.t3}, {td.e3}"
                    if td.t4:
                        timing_str += f", {td.t4}, {td.e4}"
                    lines.append(timing_str)
        lines.append(";")
        
        # 添加格式化的 Timing 内容
        self.timing_formatter.set_signal_groups(self.signal_groups)
        self.timing_formatter.set_channel_mapping(self.signal_to_channels)
        
        timing_content = self.timing_formatter.format_all_timings(self.timings)
        
        if timing_content:
            lines.append(";    Converted timing maybe not correct, Please check the timing definitions:")
            lines.append(";    DUD/UDU -> P/N; UD/DU -> 01 DNRZ; D -> 0; U -> 1; P -> Q; Other -> Other")
            lines.append(";")
            timing_lines = timing_content.split("\n")
            prefixed_lines = [";  " + line for line in timing_lines]
            lines.extend(prefixed_lines)
        
        lines.append("")
        
        return "\n".join(lines)
    
    def generate_rex_file(self) -> None:
        """生成 .rex 文件，包含 RRADR/Timing 信息
        
        文件名与 VCT 文件相同，扩展名为 .rex
        """
        if not self.target_file:
            return
        
        # 生成 .rex 文件路径
        rex_file = os.path.splitext(self.target_file)[0] + ".rex"
        
        # 确保 Timing 已格式化（这会填充 wft_to_rradr）
        self.timing_formatter.set_signal_groups(self.signal_groups)
        self.timing_formatter.set_channel_mapping(self.signal_to_channels)
        
        timing_content = self.timing_formatter.format_all_timings(self.timings)
        
        if not timing_content:
            if self.progress_callback:
                self.progress_callback("警告：没有 Timing 信息，跳过 .rex 文件生成")
            return
        
        try:
            with open(rex_file, 'w', encoding='utf-8') as f:
                f.write(timing_content)
                f.write("\n")
            
            if self.progress_callback:
                self.progress_callback(f"REX文件生成完成: {rex_file}")
        except Exception as e:
            Logger.error(f"REX文件生成失败: {e}", exc_info=True)
            if self.progress_callback:
                self.progress_callback(f"REX文件生成失败: {e}")
    
    def generate_vct_warnings(self, warnings: List[str] = None) -> str:
        """生成VCT文件警告部分（第二部分）"""
        if not warnings:
            return ""
        
        lines = []
        for warning in warnings:
            lines.append(f"; WARNING {warning}")
        
        if lines:
            lines.append(";")
            lines.append("")
        
        return "\n".join(lines)
    
    def generate_vct_drvr_section(self) -> str:
        """生成VCT文件DRVR部分（第三部分）"""
        channel_to_signal: Dict[int, str] = {}
        
        for signal, channels in self.signal_to_channels.items():
            for channel in channels:
                if 0 <= channel <= 255:
                    channel_to_signal[channel] = signal
        
        lines = [
            ";",
            ";       driver/receiver pin to DUT signal assignments:",
            ";"
        ]
         
        for channel in range(256):
            channel_str = str(channel).rjust(4)
            
            if channel in channel_to_signal:
                signal_name = channel_to_signal[channel]
                line = f";   DRVR{channel_str}: {signal_name}"
                lines.append(line)
            # 如果最后DRVR没有信号绑定，就不输出到文件里面了
            #else:
                #signal_name = "<none>"
        lines.append(";   DRVR  CS: '. .'")
        lines.append(";")
        
        return "\n".join(lines)
    
    # ========================== Vector部分生成 ==========================
    
    def _build_wfc_replacement_map(self) -> Dict[Tuple[str, str, str], str]:
        """构建 WFC 替换映射表
        
        Returns:
            {(wft, signal, wfc): replacement_char} 映射
            - 如果 TimingData.vector_replacement 不为空，使用它
            - 否则使用原始 wfc
        """
        replacement_map: Dict[Tuple[str, str, str], str] = {}
        
        for wft_name, timing_list in self.timings.items():
            for td in timing_list:
                signalOrgroup = td.signal
                wfc = td.wfc
                
                if not signalOrgroup or not wfc:
                    continue
                # 如果信号名字是信号组，就从信号组中获取所有信号
                if signalOrgroup in self.signal_groups:
                    signals = self.signal_groups[signalOrgroup]
                else:
                    signals = [signalOrgroup]
                
                # 如果有替换字符，使用替换字符；否则使用原始 wfc
                for signal in signals:
                    if td.vector_replacement:
                        replacement_map[(wft_name, signal, wfc)] = td.vector_replacement
                    else:
                        replacement_map[(wft_name, signal, wfc)] = wfc
        
        return replacement_map
    
    def _generate_signal_header_lines(self) -> List[str]:
        """生成信号名头部注释（垂直排列）
        
        Returns:
            信号名头部注释行列表
        """
        # 构建通道到信号名的映射
        channel_to_signal: Dict[int, str] = {}
        for signal, channels in self.signal_to_channels.items():
            for channel in channels:
                channel_to_signal[channel] = signal
        
        # 找出最长信号名长度（决定行数）
        max_name_len = 0
        for signal in channel_to_signal.values():
            if len(signal) > max_name_len:
                max_name_len = len(signal)
        
        if max_name_len == 0:
            return []
        
        # 前缀：51字符宽度
        prefix = ";" + " " * 50
        
        lines = []
        for row in range(max_name_len):
            line_chars = []
            for channel in range(256):
                if channel in channel_to_signal:
                    signal_name = channel_to_signal[channel]
                    if row < len(signal_name):
                        line_chars.append(signal_name[row])
                    else:
                        line_chars.append(" ")
                else:
                    line_chars.append(" ")
            lines.append(prefix + "".join(line_chars))
        
        return lines
    
    def _generate_title_lines(self) -> List[str]:
        """生成标题行和通道号标尺
        
        Returns:
            标题行列表
        """
        # 通道号：百位、十位、个位
        hundreds = ""
        tens = ""
        ones = ""
        for i in range(256):
            hundreds += str(i // 100) if i >= 100 else " "
            tens += str((i // 10) % 10) if i >= 10 else " "
            ones += str(i % 10)
        
        # 前缀51字符宽度
        lines = [
             ";                 MM GTT  C                S  T",
            f";                 RC TEM  S                Y  0    {hundreds}",
            f";                 SM SNE  A  RESERVED      N  E C  {tens}",
            f";                 TP TAM  L                C  N S  {ones}"
        ]
        
        return lines
    
    def _generate_vector_start_line(self, vector_address: int = 0) -> str:
        """生成 Vector 起始行（START: 和 MSSA）
        
        预留方法，以后可能需要优化
        
        Args:
            vector_address: 向量地址
        
        Returns:
            起始行字符串
        """
        # 256通道数据，未映射的用 .，已映射的用 Q
        channel_data = ["."] * 256
        for signal, channels in self.signal_to_channels.items():
            for channel in channels:
                if 0 <= channel <= 255:
                    channel_data[channel] = "."
        channel_str = "".join(channel_data)
        
        mrst_mcmp = "1."       # START 时 MRST=1
        gtst_tena_tmem = "..0"
        reserved = "." * 16
        sync = "..."
        toen = "0"
        cs = "1"
        
        micro_instr = "MSSA".ljust(14)
        
        # 前缀51字符
        line = f"  {micro_instr}% {mrst_mcmp} {gtst_tena_tmem} {reserved} {sync} {toen} {cs}  {channel_str} ; 0x{vector_address:06X}"
        
        return f"START:\n{line}"
    
    
    def _format_vector_line(self, vec_data_list: List[Tuple[str, str, str, str, str, int]], rradr: int) -> str:
        """格式化单行 Vector 数据
        
        Args:
            vec_data_list: [(signal, data, instr, param, label, vector_address), ...] 列表
            rradr: 当前波形表的 RRADR 编号
            
        Returns:
            格式化后的 Vector 行
        """
        # 标志位区（固定值）
        mrst_mcmp = ".."       # MRST + MCMP
        gtst_tena_tmem = "..0" # GTST + TENA + TMEM
        reserved = "." * 16   # RESERVED
        sync = "..."          # SYNC
        toen = str(rradr)     # TOEN/RRADR
        cs = "1"              # CS (固定1)
        
        # 初始化 256 通道数据为 "."
        channel_data = ["."] * 256
        
        label_str = ""
        vector_address = 0
        micro_instr = ""
        instr_str = ""
        
        # 遍历每个 pat_header 项和对应的 WFC
        # 6 元组：(signal, data, instr, param, label, vector_address)
        for pat_key, wfc_str, instr, param, label, vec_addr in vec_data_list:
            # 微指令区（16字符）
            instr_str = instr
            micro_instr = format_vct_instruction(instr, param)
            vector_address = vec_addr
            
            # 获取该 pat_key 对应的信号列表
            if pat_key in self.signal_groups:
                signals = self.signal_groups[pat_key]
            elif pat_key in self.signals:
                signals = [pat_key]
            else:
                continue
            
            if label:
                label_str = label
            
            # 遍历信号和对应的 WFC 字符
            for idx, signal in enumerate(signals):
                if idx >= len(wfc_str):
                    continue
                wfc_char = wfc_str[idx]
                
                # 应用 WFC 替换
                key = (self.current_wft, signal, wfc_char)
                if key in self.wfc_replacement_map:
                    wfc_char = self.wfc_replacement_map[key]
                
                # 找到该信号绑定的所有通道，填入 WFC
                if signal in self.signal_to_channels:
                    for channel in self.signal_to_channels[signal]:
                        if 0 <= channel <= 255:
                            channel_data[channel] = wfc_char
        
        channel_str = "".join(channel_data)
        
        # Loop 起始行，如果没有 Label 就用 vector_address 生成
        if not label_str and "LI" in instr_str:
            label_str = f"0x{vector_address:06X}"
        
        # 组装行（前缀51字符）
        # 格式: "  INSTR         % MR GTE RESERVED         SYN T C  CHANNELS ; 0xADDR"
        line = f"  {micro_instr}% {mrst_mcmp} {gtst_tena_tmem} {reserved} {sync} {toen} {cs}  {channel_str} ; 0x{vector_address:06X}"
        
        return [label_str, instr_str, line]
    
    def _format_micro_only_line(self, instr: str, param: str, rradr: int = 0, vector_address: int = 0) -> str:
        """格式化只有微指令的 Vector 行（无向量数据）
        
        用于 Stop、Goto、Call、Return 等不带 vec_block 的语句
        
        Args:
            instr: 微指令名称
            param: 微指令参数
            rradr: RRADR 值（0-7）
            vector_address: 向量地址
            
        Returns:
            格式化后的 Vector 行（通道数据全为 "."）
        """
        # 微指令区（16字符）
        micro_instr = format_vct_instruction(instr, param)
        
        # 标志位区（固定值）
        mrst_mcmp = ".."       # MRST + MCMP
        gtst_tena_tmem = "..0" # GTST + TENA + TMEM
        reserved = "." * 16   # RESERVED
        sync = "..."          # SYNC
        toen = str(rradr)     # TOEN/RRADR
        cs = "1"              # CS (固定1)
        
        # 通道数据全为 "."
        channel_str = "." * 256
        
        # 组装行
        line = f"  {micro_instr}% {mrst_mcmp} {gtst_tena_tmem} {reserved} {sync} {toen} {cs}  {channel_str} ; 0x{vector_address:06X}"
        
        return line
    
    def _generate_start_lines(self, pattern_burst_name: str) -> List[str]:
        """生成 VCT 起始行（固定内容）
        
        Returns:
            起始行列表
        """
        lines = []
        
        # 标志位区（固定值）
        mrst_mcmp = ".."       # MRST + MCMP
        gtst_tena_tmem = "..0" # GTST + TENA + TMEM
        reserved = "." * 16   # RESERVED
        sync = "..."          # SYNC
        toen = "0"            # TOEN/RRADR
        cs = "1"              # CS
        
        # 通道数据全为 "."
        channel_str = "." * 256
        
        # 固定的起始行内容: (label, instr, param)
        start_entries = [
            ("Start:", "MSSA", ""),
            ("CS_Loop:", "CALL", pattern_burst_name),
            ("", "JNME", "CS_Loop"),
            ("", "JF1", "Start"),
            ("", "ADV", ""),
            ("", "ADV", ""),
            ("", "HALT", ""),
            ("", "ADV", ""),
        ]
        
        for label, instr, param in start_entries:
            if label:
                lines.append(label)
            
            # 格式化微指令（16字符宽度）
            micro_instr = format_vct_instruction(instr, param)
            line = f"  {micro_instr}% {mrst_mcmp} {gtst_tena_tmem} {reserved} {sync} {toen} {cs}  {channel_str}"
            lines.append(line)
        
        return lines
    
    
    # ========================== STILEventHandler 回调实现 ==========================
    
    def on_parse_start(self) -> None:
        """解析开始"""
        pass
    
    def on_header(self, header: Dict[str, str]) -> None:
        """头信息"""
        # 不通过key获取Dict的第一个元素的value
        #value = list(header.values())[0]
        #self.output_file.write(f";  {value}\n")

    def on_vector_start(self, pattern_burst_name: str) -> None:
        """解析开始时调用"""
        # 写入起始行
        for line in self._generate_start_lines(pattern_burst_name):
            self.output_file.write(line + "\n")
        self.output_file.write("\n")
        pass

    def on_waveform_change(self, wft_name: str) -> None:
        """波形表切换"""
        self.current_wft = wft_name
        self.wft_pending = True
    
    def on_annotation(self, annotation: str) -> None:
        """注释时调用
        
        Args:
            annotation: 注释内容
        """
        self.output_file.write(f";{annotation}\n")

    def on_label(self, label_name: str) -> None:
        """遇到标签"""
        self.output_file.write(f"{label_name}:\n")
    
    def on_vector(self, vec_data_list: List[Tuple[str, str, str, str, str, int]], 
                  instr: str = "", param: str = "") -> None:
        """遇到向量数据
        
        Args:
            vec_data_list: [(signal, data, instr, param, label, vector_address), ...] 列表
        """
        rradr = self.timing_formatter.wft_to_rradr.get(self.current_wft, 0)
        label_str, instr_str, line = self._format_vector_line(vec_data_list, rradr)
        if "LI" in instr_str or "MBGN" in instr_str:
            self.output_file.write(line + "\n")
            if label_str:
                self.output_file.write(f"{label_str}:\n")
        else:
            if label_str:
                self.output_file.write(f"{label_str}:\n")
            self.output_file.write(line + "\n")

        self.wft_pending = False

        # 进度更新
        vector_count = self.pattern_parser0.state.vector_count
        read_size = self.pattern_parser0.state.read_size
        update_interval = 2000 if vector_count <= 10000 else 5000
        if self.progress_callback and vector_count % update_interval == 0:
            progress = read_size / self.file_size * 100 if self.file_size > 0 else 100
            self.progress_callback(f"已处理 {vector_count:,} 个向量块, 进度:{progress:.1f}%...")
           
        if vector_count % 10000 == 0:
             self.output_file.flush()
    
    def on_procedure_call(self, proc_name: str, proc_content: str = "", vector_address: int = 0) -> None:
        """Call 指令 - 内容已在解析器中展开"""
        # 如果 proc_content 为空，说明 Procedure 未找到或解析失败
        # 需要生成一个普通的 CALL 微指令
        if not proc_content:
            rradr = self.timing_formatter.wft_to_rradr.get(self.current_wft, 0)
            line = self._format_micro_only_line("Call", proc_name, rradr, vector_address)
            self.output_file.write(line + "\n")
            if self.progress_callback:
                self.progress_callback(f"警告：Procedure '{proc_name}' 未找到，生成 CALL 指令")
    
    def on_micro_instruction(self, label: str, instr: str, param: str = "", vector_address: int = 0) -> None:
        """其他微指令（Stop, Goto, IddqTestPoint 等）"""
        rradr = self.timing_formatter.wft_to_rradr.get(self.current_wft, 0)
        line = self._format_micro_only_line(instr, param, rradr, vector_address)
        self.wft_pending = False
        if "LI" in instr or "MBGN" in instr:
            self.output_file.write(line + "\n")
            if label:
                self.output_file.write(f"{label}:\n")
        else:
            if label:
                self.output_file.write(f"{label}:\n")
            self.output_file.write(line + "\n")
        self.output_file.flush()

    def on_parse_complete(self, vector_count: int) -> None:
        """解析完成"""
        if self.progress_callback:
            self.progress_callback(f"Pattern 解析完成，共 {vector_count} 个向量，进度100%")
    
    def on_log(self, log: str) -> None:
        """解析完成"""
        if self.progress_callback:
            self.progress_callback(log)

    def on_parse_error(self, error_msg: str, statement: str = "") -> None:
        """解析错误"""
        if self.progress_callback:
            if statement:
                self.progress_callback(f"VEC:{self.pattern_parser0.state.vector_count}解析错误: {error_msg}\n语句: {statement[:100]}...")
            else:
                self.progress_callback(f"VEC:{self.pattern_parser0.state.vector_count}解析错误: {error_msg}")
        Logger.error(error_msg, statement)
    
    def generate_vct_vector_section(self, output_file) -> int:
        """生成VCT文件Vector部分（第四部分）- 流式写入
        
        Args:
            output_file: 输出文件句柄
            
        Returns:
            生成的向量行数
        """
        # 保存输出文件句柄（供回调使用）
        self.output_file = output_file
        
        # 初始化
        self.current_wft = ""
        self.wft_pending = False
        
        # 构建 WFC 替换映射
        self.wfc_replacement_map = self._build_wfc_replacement_map()
        
        # 写入 #VECTOR 头
        output_file.write("#VECTOR\n")
        
        # 写入信号名头部
        for line in self._generate_signal_header_lines():
            output_file.write(line + "\n")
        
        # 写入标题行
        for line in self._generate_title_lines():
            output_file.write(line + "\n")

        # 初始化 Pattern 解析器并开始解析
        if self.progress_callback:
            self.progress_callback("开始解析 Pattern 数据...")
        
        # 解析 Pattern（通过回调写入）
        vector_count = self.pattern_parser0.parse_patterns()
        
        # 写入结束部分
        output_file.write("#VECTOREND\n")
        
        return vector_count
    
    def convert(self) -> int:
        """执行VCT转换
        
        Returns:
            0: 成功, -1: 失败或被停止
        """
        if self.progress_callback:
            self.progress_callback("开始生成VCT文件...")
                # 获取文件大小
        self.file_size = os.path.getsize(self.stil_file) if os.path.exists(self.stil_file) else 0
        size_mb = self.file_size / (1024 * 1024)
        
        try:
            with open(self.target_file, 'w', encoding='utf-8') as f:
                if self._stop_requested:
                    return -1
                    
                if self.progress_callback:
                    self.progress_callback("生成文件头...")
                f.write(self.generate_vct_header())
                
                if self._stop_requested:
                    return -1
                    
                if self.progress_callback:
                    self.progress_callback("生成Timing定义...")
                f.write(self.generate_vct_timing_section())
                
                # 生成 .rex 文件
                self.generate_rex_file()
                
                if self._stop_requested:
                    return -1
                    
                if self.progress_callback:
                    self.progress_callback("生成DRVR定义...")
                f.write(self.generate_vct_drvr_section())
                f.write("\n")
                
                if self._stop_requested:
                    return -1
                    
                if self.progress_callback:
                    self.progress_callback("生成Vector数据...")
                vector_count = self.generate_vct_vector_section(f)
                
                # 检查是否被停止
                if self._stop_requested:
                    if self.progress_callback:
                        self.progress_callback(f"转换已停止，已处理 {vector_count} 个向量块")
                    return -1
                
                if self.progress_callback:
                    self.progress_callback(f"Vector数据生成完成，共 {vector_count} 个向量块")
            
            if self.progress_callback:
                self.progress_callback(f"VCT文件生成完成: {self.target_file}")
            
            return 0
            
        except Exception as e:
            if self.progress_callback:
                # 堆栈信息也打印到日志里面
                Logger.error(f"VCT文件生成失败: {e}", exc_info=True)
                self.progress_callback(f"VCT文件生成失败: {e}")
            return -1

