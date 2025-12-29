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

from MicroInstructionMapper import MicroInstructionMapper
from TimingData import TimingData
from STILParserUtils import STILParserUtils
from htol.TimingFormatter import TimingFormatter
from PatternParser import PatternEventHandler, PatternStreamParser

try:
    from Semi_ATE.STIL.parsers.STILParser import STILParser
except ImportError:
    repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    sys.path.insert(0, repo_root)
    from Semi_ATE.STIL.parsers.STILParser import STILParser


class STILToVCTStream(PatternEventHandler):
    """Convert STIL files to VCT format - supports multiple DUTs with channel mapping."""

    def __init__(self, stil_file: str, target_file: str = "", 
                 progress_callback: Optional[Callable[[str], None]] = None, debug: bool = False):
        """初始化VCT转换器"""
        self.stil_file = stil_file
        self.target_file = target_file
        self.progress_callback = progress_callback
        self.debug = debug
        
        # 解析结果存储
        self.signals: List[str] = []
        self.signal_groups: Dict[str, List[str]] = {}
        self.used_signals: List[str] = []
        self.pat_header: List[str] = []
        
        # 用户配置的信号到通道映射
        self.signal_to_channels: Dict[str, List[int]] = {}
        
        # Timing数据
        self.timings: Dict[str, List[TimingData]] = {}
        
        # Vector生成相关
        self.current_wft: str = ""           # 当前波形表名
        self.wft_pending: bool = False       # 波形表是否刚切换
        self.vector_address: int = 0         # Vector行地址（递增）
        self.wfc_replacement_map: Dict[Tuple[str, str, str], str] = {}  # WFC替换映射 {(wft, signal, wfc): replacement}
        self.output_file = None              # 输出文件句柄（在 generate_vct_vector_section 时设置）
        
        # 通用解析工具
        self.parser_utils = STILParserUtils(debug=debug)
        
        # 微指令映射器
        self.instruction_mapper = MicroInstructionMapper()
        
        # Timing格式转换器
        self.timing_formatter = TimingFormatter()
        
        # Pattern 解析器（延迟初始化）
        self.pattern_parser: Optional[PatternStreamParser] = None
        
        # 停止标志
        self._stop_requested = False


    def stop(self) -> None:
        """请求停止转换"""
        self._stop_requested = True

    def _extract_first_vector_signals(self, tree) -> List[str]:
        """从第一个V块提取使用的信号/信号组名"""
        from lark import Tree, Token
        pat_header: List[str] = []
        
        for node in tree.iter_subtrees():
            if isinstance(node, Tree) and node.data.endswith("vec_data_block"):
                vec_tokens = [t.value for t in node.scan_values(lambda c: isinstance(c, Token))]
                if vec_tokens:
                    pat_header.append(vec_tokens[0].strip())
        
        return pat_header

    def read_stil_signals(self, print_log: bool = True) -> List[str]:
        """读取STIL文件，提取实际使用的信号列表"""
        if self.progress_callback:
            self.progress_callback("开始读取STIL文件...")
        
        if not os.path.exists(self.stil_file):
            if self.progress_callback:
                self.progress_callback(f"错误：文件不存在 - {self.stil_file}")
            return []
        
        header_buffer = ""
        buffer_lines = []
        is_pattern = False
        first_v_found = False
        
        # 初始化临时解析器（用于提取第一个 V 的信号）
        temp_parser = None
        try:
            from lark import Lark
            if getattr(sys, 'frozen', False):
                base_path = sys._MEIPASS
            else:
                base_path = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            
            grammar_base = os.path.join(base_path, "Semi_ATE", "STIL", "parsers", "grammars")
            pattern_statements_file = os.path.join(grammar_base, "pattern_statements.lark")
            
            with open(pattern_statements_file, 'r') as f:
                pattern_grammar = f.read()
            
            ignore_whitespace = """
            %import common.WS
            %ignore WS
            %import common.CPP_COMMENT  
            %ignore CPP_COMMENT
            %import common.NEWLINE
            %ignore NEWLINE
            """
            multi_grammar = """
            start: pattern_statement+
            """ + pattern_grammar + ignore_whitespace
            
            temp_parser = Lark(
                multi_grammar,
                start="start",
                parser="lalr",
                import_paths=[grammar_base]
            )
        except Exception as e:
            if self.debug:
                print(f"临时解析器初始化失败: {e}")
        
        try:
            with open(self.stil_file, 'r', encoding='utf-8') as f:
                if self.progress_callback:
                    self.progress_callback("正在解析文件头部（Signals/SignalGroups）...")
                
                for line in f:
                    if self._stop_requested:
                        return []
                    
                    if line.strip().startswith('Pattern ') and '{' in line:
                        is_pattern = True
                        
                        parser = STILParser(self.stil_file, propagate_positions=True, debug=self.debug)
                        tree = parser.parse_content(header_buffer)
                        
                        # 使用通用解析工具
                        self.signals = self.parser_utils.extract_signals(tree)
                        self.signal_groups = self.parser_utils.extract_signal_groups(tree)
                        self.timings = self.parser_utils.extract_timings(tree)
                        
                        if self.progress_callback and print_log:
                            self.progress_callback(f"找到 {len(self.signals)} 个信号定义")
                            self.progress_callback(f"找到 {len(self.signal_groups)} 个信号组")
                            self.progress_callback(f"找到 {len(self.timings)} 个波形表定义")
                            for wft_name, timing_list in self.timings.items():
                                self.progress_callback(f"  波形表 [{wft_name}] 包含 {len(timing_list)} 条Timing定义:")
                                for td in timing_list:
                                    timing_str = f"    {td.signal}, {td.period}, {td.wfc}, {td.t1}, {td.e1}"
                                    if td.t2:
                                        timing_str += f", {td.t2}, {td.e2}"
                                    if td.t3:
                                        timing_str += f", {td.t3}, {td.e3}"
                                    if td.t4:
                                        timing_str += f", {td.t4}, {td.e4}"
                                    self.progress_callback(timing_str)
                        continue
                    
                    if not is_pattern:
                        header_buffer += line
                        continue
                    
                    if is_pattern and not first_v_found and temp_parser:
                        try:
                            if line.strip().startswith('//'):
                                continue
                            
                            buffer_lines.append(line)
                            statement_buffer = "".join(buffer_lines).strip()
                            
                            if ('{' in statement_buffer and '}' in statement_buffer
                                and statement_buffer.count('{') == statement_buffer.count('}')):
                                
                                tree = temp_parser.parse(statement_buffer)
                                self.pat_header = self._extract_first_vector_signals(tree)
                                
                                if self.pat_header:
                                    first_v_found = True
                                    break
                                
                                buffer_lines.clear()
                        except Exception as e:
                            if self.debug:
                                print(f"解析错误: {e}")
            
            self.used_signals = []
            for key in self.pat_header:
                if key in self.signal_groups:
                    self.used_signals.extend(self.signal_groups[key])
                elif key in self.signals:
                    self.used_signals.append(key)
            
            if self.progress_callback and print_log:
                self.progress_callback(f"STIL中使用了 {len(self.used_signals)} 个信号:")
                for i, sig in enumerate(self.used_signals):
                    self.progress_callback(f"  {i+1}. {sig}")
            
            return self.used_signals
            
        except Exception as e:
            if self.progress_callback:
                self.progress_callback(f"读取文件失败: {e}")
            return []

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
                    if self.progress_callback:
                        self.progress_callback(f"警告：'{part}' 不是有效的数字，已忽略")
        
        return channels

    def get_used_signals(self) -> List[str]:
        """获取已解析的使用信号列表"""
        return self.used_signals

    def get_channel_mapping(self) -> Dict[str, List[int]]:
        """获取当前的通道映射配置"""
        return self.signal_to_channels

    def get_timings(self) -> Dict[str, List[TimingData]]:
        """获取已解析的Timing数据"""
        return self.timings
    
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
            result['error'] = str(e)
            return result

    # ========================== 微指令映射 ==========================
    
    def map_instruction(self, stil_instr: str, param: str = "") -> str:
        """映射并格式化微指令"""
        return self.instruction_mapper.format_vct_instruction(stil_instr, param)

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
        
        return "\n".join(lines)
    
    def generate_vct_timing_section(self) -> str:
        """生成VCT文件Timing部分"""
        if not self.timings:
            return ""
        
        lines = [
            ";",
            ";       Timing definitions:",
            ";"
        ]
        
        # 添加原始波形表信息
        for wft_name, timing_list in self.timings.items():
            lines.append(f";  Timing [{wft_name}] ({len(timing_list)} entries):")
            for td in timing_list:
                timing_str = f";    {td.signal}, {td.period}, {td.wfc}, {td.t1}, {td.e1}"
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
            lines.append(";       Converted timing maybe not correct, Please check the timing definitions:")
            lines.append(";       If UDU and DUD in Timing+Group/Signal  DUD/UDU -> P/N")
            lines.append(";       If UUU and UDU and not DDD and not DUD in Timing+Group/Signal UUU/UDU -> RO")
            lines.append(";       If DDD and DUD and not UUU and not UDU in Timing+Group/Signal DDD/DUD -> RZ")
            lines.append(";       If DU/UD in Timing+Group/Signal  DU/UD -> DNRZ")
            lines.append(";")
            timing_lines = timing_content.split("\n")
            prefixed_lines = [";  " + line for line in timing_lines]
            lines.extend(prefixed_lines)
        
        lines.append("")
        
        return "\n".join(lines)
    
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
            else:
                signal_name = "<none>"
            
            line = f";   DRVR{channel_str}: {signal_name}"
            lines.append(line)
        
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
    
    def _generate_vector_start_line(self) -> str:
        """生成 Vector 起始行（START: 和 MSSA）
        
        预留方法，以后可能需要优化
        
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
        line = f"  {micro_instr}% {mrst_mcmp} {gtst_tena_tmem} {reserved} {sync} {toen} {cs}  {channel_str} ; 0x{self.vector_address:06X}"
        self.vector_address += 1
        
        return f"START:\n{line}"
    
    
    def _format_vector_line(self, instr: str, param: str, 
                            vec_data_list: List[Tuple[str, str]], rradr: int) -> str:
        """格式化单行 Vector 数据
        
        Args:
            instr: STIL 指令
            param: 指令参数
            vec_data_list: [(pat_header_key, wfc_string), ...] 列表
            rradr: 当前波形表的 RRADR 编号
            
        Returns:
            格式化后的 Vector 行
        """
        # 微指令区（16字符）
        micro_instr = self.instruction_mapper.format_vct_instruction(instr, param)
        
        # 标志位区（固定值）
        mrst_mcmp = ".."       # MRST + MCMP
        gtst_tena_tmem = "..0" # GTST + TENA + TMEM
        reserved = "." * 16   # RESERVED
        sync = "..."          # SYNC
        toen = str(rradr)     # TOEN/RRADR
        cs = "1"              # CS (固定1)
        
        # 初始化 256 通道数据为 "."
        channel_data = ["."] * 256
        
        # 遍历每个 pat_header 项和对应的 WFC
        for pat_key, wfc_str in vec_data_list:
            # 获取该 pat_key 对应的信号列表
            if pat_key in self.signal_groups:
                signals = self.signal_groups[pat_key]
            elif pat_key in self.signals:
                signals = [pat_key]
            else:
                continue
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
        
        # 组装行（前缀51字符）
        # 格式: "  INSTR         % MR GTE RESERVED         SYN T C  CHANNELS ; 0xADDR"
        line = f"  {micro_instr}% {mrst_mcmp} {gtst_tena_tmem} {reserved} {sync} {toen} {cs}  {channel_str} ; 0x{self.vector_address:06X}"
        
        self.vector_address += 1
        
        return line
    
    def _format_micro_only_line(self, instr: str, param: str, rradr: int = 0) -> str:
        """格式化只有微指令的 Vector 行（无向量数据）
        
        用于 Stop、Goto、Call、Return 等不带 vec_block 的语句
        
        Args:
            instr: 微指令名称
            param: 微指令参数
            rradr: RRADR 值（0-7）
            
        Returns:
            格式化后的 Vector 行（通道数据全为 "."）
        """
        # 微指令区（16字符）
        micro_instr = self.instruction_mapper.format_vct_instruction(instr, param)
        
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
        line = f"  {micro_instr}% {mrst_mcmp} {gtst_tena_tmem} {reserved} {sync} {toen} {cs}  {channel_str} ; 0x{self.vector_address:06X}"
        
        self.vector_address += 1
        
        return line
    
    
    # ========================== PatternEventHandler 回调实现 ==========================
    
    def on_parse_start(self) -> None:
        """解析开始"""
        pass
    
    def on_waveform_change(self, wft_name: str) -> None:
        """波形表切换"""
        self.current_wft = wft_name
        self.wft_pending = True
    
    def on_label(self, label_name: str) -> None:
        """遇到标签"""
        self.output_file.write(f"{label_name}:\n")
    
    def on_vector(self, vec_data_list: List[Tuple[str, str]], 
                  instr: str = "", param: str = "") -> None:
        """遇到向量数据"""
        rradr = self.timing_formatter.wft_to_rradr.get(self.current_wft, 0)
        line = self._format_vector_line(instr, param, vec_data_list, rradr)
        self.output_file.write(line + "\n")
        self.wft_pending = False
        
        # 进度更新
        if self.progress_callback and self.vector_address % 1000 == 0:
            self.progress_callback(f"已生成 {self.vector_address:,} 个向量...")
    
    def on_loop_start(self, loop_count: str, label: str = "") -> None:
        """Loop 开始"""
        # 记录 loop 信息，用于后续处理
        self._current_loop_count = loop_count
        self._current_loop_label = label
        self._loop_vectors: List[Tuple[str, List[Tuple[str, str]]]] = []
    
    def on_loop_vector(self, vec_data_list: List[Tuple[str, str]], 
                       index: int, total: int, vec_label: str = "") -> None:
        """Loop 内的向量"""
        # 收集 Loop 内的所有向量
        self._loop_vectors.append((vec_label, vec_data_list))
    
    def on_loop_end(self, loop_count: str) -> None:
        """Loop 结束 - 生成 RPT 或 LI/JNI 指令"""
        if len(self._loop_vectors) == 0:
            return
        
        rradr = self.timing_formatter.wft_to_rradr.get(self.current_wft, 0)
        
        # 如果只有一个 V，使用 RPT 微指令
        if len(self._loop_vectors) == 1:
            vec_label, vec_data_list = self._loop_vectors[0]
            
            # 输出 Label（优先使用 Loop 的 label，然后是 V 的 label）
            label_to_output = self._current_loop_label if self._current_loop_label else vec_label
            if label_to_output:
                self.output_file.write(f"{label_to_output}:\n")
            
            # 使用 RPT 微指令
            instr = "RPT"
            param = loop_count
            line = self._format_vector_line(instr, param, vec_data_list, rradr)
            self.output_file.write(line + "\n")
        else:
            # 多个 V，使用 LI/JNI 微指令
            # 确定 Loop 起始 Label
            if self._current_loop_label:
                loop_label = self._current_loop_label
            else:
                # 用当前 vector_address 作为自动生成的 Label
                loop_label = f"0x{self.vector_address:06X}"
            
            # 输出 Loop 起始 Label
            self.output_file.write(f"{loop_label}:\n")
            
            # 输出 Vector 行（m 作为局部变量，每个 Loop 块从 0 开始）
            m = 0
            for i, (vec_label, vec_data_list) in enumerate(self._loop_vectors):
                # 如果 V 有自己的 label（非第一个 V），先输出 label
                if i > 0 and vec_label:
                    self.output_file.write(f"{vec_label}:\n")
                
                if i == 0:
                    # 第一个 V，使用 LIm {loop_count}
                    instr = f"LI{m}"
                    param = loop_count
                elif i == len(self._loop_vectors) - 1:
                    # 最后一个 V，使用 JNIm {loop_label}
                    instr = f"JNI{m}"
                    param = loop_label
                else:
                    # 中间的 V，使用 ADV
                    instr = ""
                    param = ""
                
                # 生成并写入 Vector 行
                line = self._format_vector_line(instr, param, vec_data_list, rradr)
                self.output_file.write(line + "\n")
        
        self.wft_pending = False
        # 清空临时数据
        self._loop_vectors = []
    
    def on_procedure_call(self, proc_name: str, proc_content: str = "") -> None:
        """Call 指令 - 内容已在解析器中展开"""
        # 如果 proc_content 为空，说明 Procedure 未找到或解析失败
        # 需要生成一个普通的 CALL 微指令
        if not proc_content:
            rradr = self.timing_formatter.wft_to_rradr.get(self.current_wft, 0)
            line = self._format_micro_only_line("Call", proc_name, rradr)
            self.output_file.write(line + "\n")
            if self.progress_callback:
                self.progress_callback(f"警告：Procedure '{proc_name}' 未找到，生成 CALL 指令")
    
    def on_micro_instruction(self, instr: str, param: str = "") -> None:
        """其他微指令（Stop, Goto, IddqTestPoint 等）"""
        rradr = self.timing_formatter.wft_to_rradr.get(self.current_wft, 0)
        line = self._format_micro_only_line(instr, param, rradr)
        self.output_file.write(line + "\n")
        self.wft_pending = False
    
    def on_parse_complete(self, vector_count: int) -> None:
        """解析完成"""
        if self.progress_callback:
            self.progress_callback(f"Pattern 解析完成，共 {vector_count} 个向量")
    
    def on_parse_error(self, error_msg: str, statement: str = "") -> None:
        """解析错误"""
        if self.progress_callback:
            if statement:
                self.progress_callback(f"解析错误: {error_msg}\n语句: {statement[:100]}...")
            else:
                self.progress_callback(f"解析错误: {error_msg}")
    
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
        self.vector_address = 0
        self.current_wft = ""
        self.wft_pending = False
        
        # 构建 WFC 替换映射
        self.wfc_replacement_map = self._build_wfc_replacement_map()
        
        # 写入 #VECTOR 头
        output_file.write("#VECTOR\n")
        output_file.write("  ORG 0\n")
        
        # 写入信号名头部
        for line in self._generate_signal_header_lines():
            output_file.write(line + "\n")
        
        # 写入标题行
        for line in self._generate_title_lines():
            output_file.write(line + "\n")
        
        # 写入起始行
        output_file.write("VECTOR:\n")
        
        # 初始化 Pattern 解析器并开始解析
        self.pattern_parser = PatternStreamParser(self.stil_file, self, self.debug)
        
        if self.progress_callback:
            self.progress_callback("开始解析 Pattern 数据...")
        
        # 解析 Pattern（通过回调写入）
        vector_count = self.pattern_parser.parse_patterns()
        
        # 更新 vector_address（解析器维护自己的计数）
        self.vector_address = vector_count
        
        # 写入结束部分
        output_file.write("#VECTOREND\n")
        
        return vector_count
    
    def convert(self) -> int:
        """执行VCT转换"""
        if self.progress_callback:
            self.progress_callback("开始生成VCT文件...")
        
        try:
            with open(self.target_file, 'w', encoding='utf-8') as f:
                if self.progress_callback:
                    self.progress_callback("生成文件头...")
                f.write(self.generate_vct_header())
                
                if self.progress_callback:
                    self.progress_callback("生成Timing定义...")
                f.write(self.generate_vct_timing_section())
                
                if self.progress_callback:
                    self.progress_callback("生成DRVR定义...")
                f.write(self.generate_vct_drvr_section())
                f.write("\n")
                
                if self.progress_callback:
                    self.progress_callback("生成Vector数据...")
                vector_count = self.generate_vct_vector_section(f)
                
                if self.progress_callback:
                    self.progress_callback(f"Vector数据生成完成，共 {vector_count} 行")
            
            if self.progress_callback:
                self.progress_callback(f"VCT文件生成完成: {self.target_file}")
            
            return 0
            
        except Exception as e:
            if self.progress_callback:
                self.progress_callback(f"VCT文件生成失败: {e}")
            return -1

