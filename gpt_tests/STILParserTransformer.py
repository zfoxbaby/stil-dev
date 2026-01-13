"""STIL Pattern 流式解析器模块 - Transformer 实现

使用 Lark Transformer 提供更声明式的解析方式。
相比手动遍历解析树，Transformer 更易维护和扩展。

核心类：
- PatternEventHandler: 事件处理接口（复用）
- PatternTransformer: Transformer 实现
- PatternStreamParserTransformer: Pattern 流式解析器（Transformer版本）
"""

from __future__ import annotations

import os
import re
import sys
from typing import List, Dict, Tuple, Optional, Any
from lark import Lark, Tree, Token, Transformer, LarkError, v_args
from typing import Callable
from STILParserUtils import STILParserUtils
import Logger

# 复用原有的 PatternEventHandler
from STILEventHandler import STILEventHandler
from TimingData import TimingData

# STIL 到 VCT 微指令映射表
INSTRUCTION_MAPPING: Dict[str, str] = {
    "Stop": "HALT",
    "Goto": "JUMP",
    "Loop": "LI",       # 如果Loop里面只有一个V那么就替换成RPT
    "MatchLoop": "MBGN",
    "Call": "CALL",
    "Return": "RET",
    "IddqTestPoint": "IDDQ",
    "IDDQTestPoint": "IDDQ",
    "BreakPoint" : "BreakPoint",
    # 补充
    "Repeat": "RPT",
    "LoopEnd": "JNI",
    "MBGN": "MBGN",
    "IMATCH": "IMATCH",
    "MEND": "MEND",
}

#=========================通用函数，以后放到配置文件============================
# 禁用的指令列表（遇到这些指令会跳过解析并提示用户）
DISABLED_INSTRUCTIONS: List[str] = [
    # "ScanChain",      # 示例：禁用 ScanChain 指令
    # "Shift",          # 示例：禁用 Shift 指令
    # MatchLoop",
]

# 无指令时的缺省值
DEFAULT_INSTRUCTION = "ADV"


def map_instruction(stil_instr: str, supplment_instr: str = "") -> str:
    """映射 STIL 指令到 VCT 指令
    
    Args:
        stil_instr: STIL 中的指令名
        
    Returns:
        映射后的 VCT 指令名
    """
    if not stil_instr or stil_instr.strip() == "":
        return DEFAULT_INSTRUCTION + supplment_instr
    
    return INSTRUCTION_MAPPING.get(stil_instr, stil_instr) + supplment_instr


def is_disabled(stil_instr: str) -> bool:
    """检查指令是否被禁用
    
    Args:
        stil_instr: STIL 中的指令名
        
    Returns:
        True 如果指令被禁用
    """
    return stil_instr in DISABLED_INSTRUCTIONS


def format_vct_instruction(stil_instr: str, param: str = "") -> str:
    """格式化为 VCT 指令字符串（固定14字符宽度）
    
    Args:
        stil_instr: STIL 中的指令名
        param: 指令参数
        
    Returns:
        格式化后的 VCT 指令字符串（14字符宽度）
    """
    vct_instr = map_instruction(stil_instr)
    
    if param:
        instr_str = f"{vct_instr} {param}"
    else:
        instr_str = vct_instr
    
    return instr_str.ljust(14)
#=======================================================================

class ParserState:
    """解析器共享状态
    
    用于在 Transformer 和主解析器之间共享状态
    """
    
    def __init__(self):
        self.multi_parser: Optional[Lark] = None
        # 所有行数
        self.vector_count = 0
        self.read_size = 0
        # 当前地址行，每行加1
        self.vector_address = 0  # 向量地址（用于生成自动 Label 和输出）
        # loop嵌套层数计数器
        self.loop_deep = 0
        # 左括号个数，出现右括号时减一，为了判断是否有{}嵌套并且是否获取了完整的{}对数
        self.left_square_count = 0
        # 当出现loop、matchloop、breakpoint时需要缓存部分V块
        self.vec_data_list = []
        self.pending_vector: Optional[List] = None
        # 当前的wft+label+instruction+param，出现新的会替换
        self.current_wft = ""
        self.curr_label = ""
        self.curr_instr = ""
        self.curr_param = ""
        # [procedure name, procedure content]
        self.procedures: Dict[str, str] = {}
        # [macrodef name, macrodef content]
        self.macrodefs: Dict[str, str] = {}
        # 如果出现Call、Macro会出现替换功能，Key是信号/信号组，Value是Vector
        self.replace_vector_list : Dict[str, str] = {}
        self.replace_vector_on = False
        # [header name, header content]
        self.headers: Dict[str, str] = {}
        # [signal name, signal type]
        self.signal_dict : Dict[str, str] = {}
        # 多个信号组块，记录当前块名字
        self.signal_group_domain = "default"
        # 每次出现新的SignalGroup名字时替换，为了后面的Group能找到key
        self.signal_group_name = ""
        # [more, [signal group name, signal list]]
        self.signal_group_dict : Dict[str, Dict[str, List[str]]] = {}
        # [signal group name, signal list]
        self.signal_group: Dict[str, List[str]] = {}
        # [timing domain name, {waveform table name, [TimingData列表]}]
        self.timing_dict : Dict[Dict[str, List[TimingData]]] = {}
        self.timing_domain_name = ""
        # [burst name, {SignalGroups: signal group name, PatList: pattern list}]
        self.pattern_burst_dict : Dict[str, Dict[str, Any]] = {}
        # 每次出现新的pattern_burst_name名字时替换，为了后面的能找到key，最后设置为当前选择的Burst name
        # 从这里能找到当前选择的signal group name和patList
        self.pattern_burst_name = ""

    def reset(self) -> None:
        self.loop_deep = 0
        self.vec_data_list = []
        self.curr_label = ""
        self.curr_instr = ""
        self.curr_param = ""

    def handle_curr(self) -> List[str]:
        instr = self.curr_instr
        self.curr_instr = ""
        param = self.curr_param
        self.curr_param = ""
        label = self.curr_label
        self.curr_label = ""
        return [instr, param, label]
    
    def flush_pending_vector(self, handler: STILEventHandler) -> None:
        """写出 pending_vector（如果存在）"""
        if self.pending_vector is not None:
            handler.on_vector(self.pending_vector, "", "")
            self.vector_count += 1
            self.pending_vector = None
    
    def attach_instr_to_pending(self, handler: STILEventHandler, 
                                 instr: str, param: str, label: str = "") -> bool:
        """把微指令附加到 pending_vector 上并写出
        
        Args:
            handler: 事件处理器
            instr: 指令名
            param: 指令参数
            label: 标签（用于 Loop 的 LI 指令）
            
        Returns:
            True 如果成功附加到 pending_vector
            False 如果没有 pending_vector 或 pending_vector 已有指令
        """
        if self.pending_vector is not None and len(self.pending_vector) > 0:
            # 检查 pending_vector 是否已有微指令
            first_item = self.pending_vector[0]
            existing_instr = first_item[2] if len(first_item) > 2 else ""
            
            if not existing_instr or existing_instr.strip() == "" or existing_instr == DEFAULT_INSTRUCTION:
                # 可以附加：更新 pending_vector 中每个元素的 instr 和 param
                new_pending = []
                for item in self.pending_vector:
                    # 6 元组：(signal, data, instr, param, label, vector_address)
                    new_item = (item[0], item[1], instr, param, 
                                label if label else item[4], item[5])
                    new_pending.append(new_item)
                self.pending_vector = new_pending
                # 写出
                handler.on_vector(self.pending_vector, instr, param)
                self.vector_count += 1
                self.pending_vector = None
                return True
            else:
                # 如果不能成功替换，说明已经有指令了，直接返回False，然后把pending_vector清空
                handler.on_vector(self.pending_vector, instr, param)
                self.pending_vector = None
                return False
        
        return False

class STILParserTransformer(Transformer):
    """Pattern 语句转换器
    
    使用 Lark Transformer 自动遍历和处理解析树。
    每个方法对应一个语法规则。
    """
    
    def __init__(self, parser: PatternStreamParserTransformer,
          handler: STILEventHandler,
          text_original: str,
          start_index: int,
          parser_state:ParserState):
        """初始化 Transformer
        
        Args:
            handler: 事件处理器
            parser_state: 解析器状态（共享状态对象）
        """
        super().__init__()
        self.parser = parser
        self.handler = handler
        self.state = parser_state
        self.text_original = text_original
        self.start_index = start_index

        self._REPEAT_PATTERN = re.compile(r'\\r(\d+)\s+([^\s\\]+)')
        self._WHITESPACE_PATTERN = re.compile(r'\s+')

    # ========================== Header 处理 ==========================
    def b_header__TITLE_STRING(self, token: Token) -> None:
        """处理标题文本"""
        self.handler.on_header({"Title": token.value})
        self.state.headers["Title"] = token.value

    def b_header__HEADER_DATE_STRING(self, token: Token) -> None:
        """处理日期文本"""
        self.handler.on_header({"Date": token.value})
        self.state.headers["Date"] = token.value

    def b_header__SOURCE_STRING(self, token: Token) -> None:
        """处理源文本"""
        self.handler.on_header({"Source": token.value})
        self.state.headers["Source"] = token.value

    def b_header__ANN_TEXT(self, token: Token) -> Dict[str, Any]:
        """处理注释文本"""
        return {"type": "history", "History": token.value}

    def b_header__annotation_hist(self, children: List) -> Dict[str, Any]:
        """处理注释历史块"""
        values = [child.get("History") for child in children if isinstance(child, dict)]
        self.state.headers["History"] = "".join(values)
        self.handler.on_header({"History": self.state.headers["History"]})
        return {"type": "annotation_hist", "value": values}

    def b_header__history(self, children: List) -> Dict[str, Any]:
        """处理历史块"""
        valuess = [child.get("value") for child in children if isinstance(child, dict)]
        return {"type": "history", "value": valuess}

    # ========================== Signal 处理 ==========================
    def b_signals__signals_list(self, children: List) -> None:
        """处理 Signal 列表"""
        self.state.signal_dict[children[0]] = children[1]
    def b_signals__SIGNAL_NAME(self, token: Token) -> str:
        """处理 Signal 名称"""
        return token.value.strip('"').strip("'")
    def b_signals__SIGNAL_TYPE(self, token: Token) -> str:
        """处理 Signal 类型"""
        return token.value

    # ========================== SignalGroup 处理 ==================================
    def signal_groups_block(self, children: List) -> Dict[str, Any]:
        self.state.signal_group = self.state.signal_group_dict["default"]
    def b_signal_groups__SIGNAL_GROUPS_DOMAIN_NAME(self, token: Token) -> None:
        """处理 SignalGroups 域名"""
        self.state.signal_group_domain = token.value
    def b_signal_groups__open_signal_groups_block(self, children: List) -> Dict[str, Any]:
        """处理 SignalGroups 开始块"""
        self.state.signal_group_dict[self.state.signal_group_domain] = {}
        return {}
    def b_signal_groups__SIGNAL_GROUP_NAME(self, token: Token) -> None:
        self.state.signal_group_name = token.value
        self.state.signal_group_dict[self.state.signal_group_domain][token.value] = []
        pass
    def b_signal_groups__SIGREF_NAME(self, token: Token) -> str:
        signal_groups = self.state.signal_group_dict[self.state.signal_group_domain]
        signal_groups[self.state.signal_group_name].append(token.value.strip('"').strip("'"))
        return token.value
    def b_signal_groups__sigref_expr(self, children: List) -> None:
        if children[0] == "-":
            signal_groups = self.state.signal_group_dict[self.state.signal_group_domain]
            signal_groups[self.state.signal_group_name].remove(children[1].value.strip('"').strip("'"))
    def b_signal_groups__SIG_SUB(self, token: Token) -> str:
        return token.value

    # ========================== Timing处理 ==================================
    def timing_block(self, children: List) -> None:
        # 使用通用解析工具
        parser_utils = STILParserUtils(debug=False)
        self.timings = parser_utils.extract_timings(children, self.state.signal_dict,
                self.state.signal_group, self.handler)
        self.state.timing_dict[self.state.timing_domain_name] = self.timings
        pass

    def b_timing__TIMING_DOMAIN_NAME(self, token: Token) -> None:
        self.state.timing_dict[token.value] = {}
        self.state.timing_domain_name = token.value
        # 这里Signal Group已经解析完了，先使用默认的，如果用户定义了Timing SignalGroups就会被替换
        self.state.signal_group = self.state.signal_group_dict["default"]

    def b_timing__SIGNAL_GROUPS_DOMAIN(self, token: Token) -> None:
        self.state.signal_group = self.state.signal_group_dict[token.value]

    # ========================== PatternBurst处理 ==================================
    def pattern_burst_block(self, children: List) -> None:
        pass
    def b_pattern_burst__PATTERN_BURST_BLOCK_NAME(self, token: Token) -> str:
        self.state.pattern_burst_dict[token.value] = {}
        self.state.pattern_burst_dict[token.value]["PatList"] = []
        self.state.pattern_burst_name = token.value
    def b_pattern_burst__SIGNAL_GROUPS_DOMAIN(self, token: Token) -> Dict[str, str]:
        self.state.pattern_burst_dict[self.state.pattern_burst_name]["SignalGroups"] = token.value
        return {token.value: token.value}
    def b_pattern_burst__PATT_OR_BURST_NAME(self, token: Token) -> Dict[str, str]:
        self.state.pattern_burst_dict[self.state.pattern_burst_name]["PatList"].append(token.value)
        return {token.value: token.value}

    # ========================== PatternExec处理 ==================================
    def b_pattern_exec__pes_timing(self, children: List) -> None:
        pass
    def b_pattern_exec__TIMING_DOMAIN(self, token: Token) -> None:
        self.state.timing_domain_name = token.value
        pass
    def b_pattern_exec__PATTERN_BURST_NAME(self, token: Token) -> None:
        pattern_burst = self.state.pattern_burst_dict[token.value]
        if "SignalGroups" in pattern_burst:
            used_signalgroups = pattern_burst["SignalGroups"]
            self.state.signal_group = self.state.signal_group_dict[used_signalgroups]
        self.state.pattern_burst_name = token.value

    # ========================== Label 处理 ==================================
    def LABEL(self, token: Token) -> Dict[str, Any]:
        """处理 LABEL token"""
        label_name = token.value.strip('"').strip("'").rstrip(':')
        self.state.curr_label = label_name
        #self.handler.on_label(label_name)
        return {"type": "label", "value": label_name}
    
    # ========================== W 语句（波形表切换）======================
    def w_stmt(self, children: List) -> Dict[str, Any]:
        """处理 W 语句（波形表切换）"""
        # 在切换 WFT 之前，先写出 pending_vector（用旧的 WFT）
        self.state.flush_pending_vector(self.handler)
        
        # children 包含所有 token
        tokens = [c for c in children if isinstance(c, Token)]
        if len(tokens) >= 2:
            wft_name = tokens[1].value
            self.state.current_wft = wft_name
            self.handler.on_waveform_change(wft_name)
            return {"type": "waveform", "value": wft_name}
        return {"type": "waveform", "value": ""}
    
    # ========================== V 语句（向量数据）==========================
    def vec_data_block(self, children: List) -> Dict[str, Any]:
        """处理向量数据块"""
        tokens = [c.value for c in children if isinstance(c, Token)]
        if tokens:
            signal = tokens[0].strip()
            data = self._expand_vec_data(tokens[-1].strip())
            return {"type": "vector", "signal": signal, "data": data}
        return {"type": "vector", "signal": "", "data": ""}
    
    def vec_block(self, children: List) -> List[Dict[str, Any]]:
        """处理 vec_block（收集所有 vec_data_block）
        """
        # 定义一个集合来存储向量数据
        vector:List[Dict[str, Any]] = []
        for child in children:
            # 如果child是dict就放到vector里面
            if isinstance(child, dict) and child.get("type") == "vector":
                vector.append(child)
        return vector
    
    def v_stmt(self, children: List) -> Dict[str, Any]:
        """处理 V 语句
        
        使用 Dict 结构存入 vec_data_list：{"type": "vector", "data": [...]}
        微指令放在前一个 V 上，所以需要延迟写入
        """
        if len(children) == 0 and len(self.state.vec_data_list) == 0:
            # 解析结束时调用，写出最后一个 pending_vector
            self.state.flush_pending_vector(self.handler)
            return {}
        
        # 检查禁用指令
        if self.state.curr_instr and is_disabled(self.state.curr_instr):
            self.parser.stop()
            self.handler.on_parse_complete(self.state.vector_count)
            self.handler.on_parse_error(
                f"机型不支持 '{self.state.curr_instr}' 指令，转换中止！！！", 
                f"不支持的指令列表: {DISABLED_INSTRUCTIONS}"
            )
            return {}
        
        # 收集当前 V 的向量数据
        vec_data = []
        for child in children:
            if not isinstance(child, List):
                continue
            for item in child:
                # 如果存在需要替换的 Vectors，则替换（Call/Macro 指令的参数中）
                replace_signal_vectors = self.state.replace_vector_list.get(item.get("signal"), "")
                vectors = item.get("data")
                if self.state.replace_vector_on and replace_signal_vectors:
                    vectors = replace_signal_vectors
                # 6 元组：(signal, data, instr, param, label, vector_address)
                vec_data.append((item.get("signal"), vectors, 
                    "", "",  # instr 和 param 先为空
                    self.state.curr_label, self.state.vector_address))
        
        if len(vec_data) > 0:
            # 使用 Dict 结构
            self.state.vec_data_list.append({"type": "vector", "data": vec_data})
            self.state.vector_address += 1
        
        self.state.curr_label = ""
        
        # 如果在循环/块中，缓存起来等块结束处理
        if self.state.loop_deep > 0 or self.state.left_square_count > 0:
            return {}
        
        # 不在循环中，处理写出逻辑
        self._flush_vec_data_list()
        
        return {}
    
    def _flush_vec_data_list(self) -> None:
        """写出 vec_data_list 中的所有数据，配合 pending_vector 延迟写入"""
        for item in self.state.vec_data_list:
            if item["type"] == "vector":
                # 先写出之前的 pending_vector
                self.state.flush_pending_vector(self.handler)
                # self.handler.on_vector(item["data"], "", "")
                # self.state.vector_count += 1
                # 把当前 V 存入 pending_vector（延迟写入）
                self.state.pending_vector = item["data"]
            elif item["type"] == "instruction":
                # 到这里的 instruction 已经在 close_loop_block/close_matchloop_block 中
                # 判断过不能附加到前一个 V，所以直接单独写出
                # 先写出 pending_vector
                self.state.flush_pending_vector(self.handler)
                instr = item.get("instr", "")
                param = item.get("param", "")
                label = item.get("label", "")
                # 用 Q 占位单独写一行
                self.state.pending_vector = None
                self.handler.on_micro_instruction(label, instr, param, self.state.vector_address)
                
                self.state.vector_address += 1
                self.state.vector_count += 1
            elif item["type"] == "label":
                self.handler.on_label(item["label"])
        self.state.vec_data_list = []
        
        # 如果不在循环/块中，立即写出最后的 pending_vector
        # if self.state.loop_deep == 0 and self.state.left_square_count == 0:
        #     self.state.flush_pending_vector(self.handler)
    
    def _expand_vec_data(self, data: str) -> str:
        """展开向量数据中的重复指令"""
        #f \r2 f\w0000 0101
        # 使用 _REPEAT_PATTERN代替pattern
        pattern = self._REPEAT_PATTERN
        
        def replace_repeat(match):
            repeat_count = int(match.group(1))
            repeat_content = match.group(2)
            return repeat_content * repeat_count
        
        result = data
        while '\\r' in result:
            # 使用 _REPEAT_PATTERN.sub(replace_repeat, result)代替re.sub(pattern, replace_repeat, result)
            new_result = self._REPEAT_PATTERN.sub(replace_repeat, result)
            if new_result == result:
                break
            result = new_result
        
        result = self._WHITESPACE_PATTERN.sub('', result)
        return result
    
    # ========================== Loop 语句 ==========================
    def KEYWORD_LOOP(self, token: Token) -> Dict[str, Any]:
        """处理 Loop 关键字"""
        self.state.curr_instr = token.value.strip('"').strip("'").rstrip(':')
        return {"type": "KEYWORD_LOOP", "value": self.state.curr_instr}

    def LOOP_COUNT(self, token: Token) -> Dict[str, Any]:
        """处理 Loop 计数"""
        self.state.curr_param = token.value.strip('"').strip("'").rstrip(':')
        # 减一
        self.state.curr_param = int(self.state.curr_param) - 1
        return {"type": "LOOP_COUNT", "value": self.state.curr_param}
    
    def open_loop_block(self, children: List) -> Dict[str, Any]:
        """处理 Loop 开始块
        
        压入 Loop 指令标记，等 close_loop_block 时根据 V 数量决定如何处理
        """
        loop_instr = f"{map_instruction('Loop')}{self.state.loop_deep}"
        loop_label = self.state.curr_label if self.state.curr_label else f"0x{self.state.vector_address:06X}"
        
        # 压入 Loop 指令标记
        self.state.vec_data_list.append({
            "type": "loop",
            "instr": loop_instr,
            "param": self.state.curr_param,
            "label": loop_label,
            "loop_deep": self.state.loop_deep
        })
        
        self.state.curr_instr = ""
        self.state.curr_param = ""
        self.state.curr_label = ""
        self.state.loop_deep += 1
        
        return {"is_loop_end": False}

    def close_loop_block(self, children: List) -> Dict[str, Any]:
        """处理 Loop 结束块
        
        从 vec_data_list 末尾往前找对应的 loop 标记，统计 V 数量：
        - 1 个 V：LI 改成 RPT，放在这个 V 上
        - 多个 V：LI 放在 loop 前面的 V 上，JNI 放在最后一个 V 上
        - 如果 loop 前面不是 V 或 V 已有指令：LI 单独用 Q 占位
        """
        self.state.loop_deep -= 1
        
        if len(self.state.vec_data_list) == 0:
            return {}
        
        # 从末尾收集直到找到对应的 loop 标记
        loop_content = []  # Loop 内的所有元素
        loop_info = None
        
        #找到最近的一个loop instruction
        while len(self.state.vec_data_list) > 0:
            item = self.state.vec_data_list.pop()
            if item.get("type") == "loop" and item.get("loop_deep") == self.state.loop_deep:
                loop_info = item
                break
            loop_content.insert(0, item)  # 保持顺序
        
        if loop_info is None:
            # 没找到对应的 loop 标记，异常
            return {}
        
        # 统计 Loop 内的 V 数量
        v_items = [x for x in loop_content if x.get("type") == "vector"]
        v_count = len(v_items)
        
        loop_instr = loop_info["instr"]     # LI0, LI1, ...
        loop_param = loop_info["param"]     # 循环次数
        loop_label = loop_info["label"]     # 标签
        
        if v_count == 0:
            # Loop 内没有 V，异常
            return {}
        elif v_count == 1:
            # 情况 1/3：只有 1 个 V，LI 改成 RPT，放在这个 V 上
            # 先写出 pending_vector，保证顺序正确
            for item in loop_content:
                if item.get("type") == "vector":
                    # 给 V 附加 RPT
                    new_data = []
                    for vec in item["data"]:
                        # 减+
                        new_data.append((vec[0], vec[1],
                         map_instruction("Repeat"), int(loop_param) + 1, loop_label, vec[5]))
                    self.state.vec_data_list.append({"type": "vector", "data": new_data})
                    # 因为RPT减去了一行，这里加一行
                    # self.state.vec_data_list.append({"type": "vector", "data": item["data"]});
                else:
                    # 其他指令保持原样
                    self.state.vec_data_list.append(item)
        else:
            # 情况 2/4：多个 V，LI 放在 loop 前面的 V 上，JNI 放在最后一个 V 上
            # 先检查 loop 前面是否有 V（嵌套循环再 vec_data_list 中 否则再pending_vector 中）
            prev_is_vector_in_list = (len(self.state.vec_data_list) > 0 and 
                                      self.state.vec_data_list[-1].get("type") == "vector")
            prev_is_vector_in_pending = (self.state.pending_vector is not None and 
                                         len(self.state.pending_vector) > 0)
            prev_is_vector = prev_is_vector_in_list or prev_is_vector_in_pending
            
            if prev_is_vector:
                # 情况 2：LI 放在前一个 V 上
                # 前一个 V 可能在 vec_data_list 或 pending_vector 中
                if prev_is_vector_in_list:
                    prev_item = self.state.vec_data_list.pop()
                    prev_data = prev_item["data"]
                else:
                    # 在 pending_vector 中
                    prev_data = self.state.pending_vector
                    self.state.pending_vector = None
                
                # 检查前一个 V 是否已有指令
                has_instr = any(vec[2] and vec[2].strip() != "" for vec in prev_data)
                if has_instr:
                    # 如果上一个指令是RPT，就把它的指令的参数减一，然后拿出一行，放LI
                    if prev_data and prev_data[0][2] == map_instruction("Repeat") and int(prev_data[0][3]) > 1:
                        old_rpt_data = []
                        new_v_data = []
                        for vec in prev_data:
                            old_rpt_data.append((vec[0], vec[1], vec[2], int(vec[3]) - 1, vec[4], vec[5]))
                            new_v_data.append((vec[0], vec[1], loop_instr, loop_param, loop_label, vec[5]))
                        self.state.vec_data_list.append({"type": "vector", "data": old_rpt_data})
                        self.state.vec_data_list.append({"type": "vector", "data": new_v_data})
                    else:
                        # 已有指令，先把原 V 放回，LI 单独成一行
                        self.state.vec_data_list.append({"type": "vector", "data": prev_data})
                        self.state.vec_data_list.append({
                            "type": "instruction",
                            "instr": loop_instr,
                            "param": loop_param,
                            "label": loop_label
                        })
                else:
                    # 没有指令，附加 LI
                    new_data = []
                    needAdd = False
                    for vec in prev_data:
                        if vec[4] and not needAdd:
                            self.state.vec_data_list.append({"type": "label", "label": vec[4]})
                            needAdd = True
                        new_data.append((vec[0], vec[1], loop_instr, loop_param,
                                         loop_label, vec[5]))
                    self.state.vec_data_list.append({"type": "vector", "data": new_data})
            else:
                # 情况 4：前面不是 V，LI 单独成一行
                self.state.vec_data_list.append({
                    "type": "instruction",
                    "instr": loop_instr,
                    "param": loop_param,
                    "label": loop_label
                })
            
            # 把 Loop 内的元素加回去，最后一个 V 附加 JNI
            jni_instr = f"{map_instruction('LoopEnd')}{self.state.loop_deep}"
            v_index = 0
            for item in loop_content:
                if item.get("type") == "vector":
                    v_index += 1
                    if v_index == v_count:
                        # 最后一个 V，附加 JNI
                        new_data = []
                        for vec in item["data"]:
                            new_data.append((vec[0], vec[1], jni_instr, loop_label, vec[4], vec[5]))
                        self.state.vec_data_list.append({"type": "vector", "data": new_data})
                    else:
                        self.state.vec_data_list.append(item)
                else:
                    self.state.vec_data_list.append(item)
        
        # 如果回到最外层，写出
        if self.state.loop_deep == 0 and self.state.left_square_count == 0:
            self._flush_vec_data_list()
            # 只有多 V 情况（有 LI+JNI）才置空 pending_vector
            # 单 V 情况变成 RPT，此时后面是Loop就需要拆出一个V，所以在pending_vector中保留
            if v_count > 1:
                self.state.flush_pending_vector(self.handler)
        
        return {"is_loop_end": True}
    
    # ========================== MatchLoop 语句 ==========================
    def KEYWORD_MATCH_LOOP(self, token: Token) -> None:
        """处理 MatchLoop 关键字"""
        self.state.curr_instr = token.value.strip('"').strip("'").rstrip(':')
    
    def MATCHLOOP_COUNT(self, token: Token) -> None:
        """处理 MatchLoop 计数"""
        self.state.curr_param = token.value.strip('"').strip("'").rstrip(':')
    
    def MATCHLOOP_INF(self, token: Token) -> None:
        """处理 MatchLoop 无限循环"""
        self.state.curr_param = "0xFFFFFF"

    def open_matchloop_block(self, children: List) -> Dict[str, Any]:
        """处理 MatchLoop 开始块
        
        压入 MatchLoop 指令标记
        """
        match_instr = map_instruction("MatchLoop")  # MBGN
        # 与 Loop 一致：如果没有 label 就自动生成
        # match_label = self.state.curr_label if self.state.curr_label else f"0x{self.state.vector_address:06X}"
        match_label = self.state.curr_label if self.state.curr_label else ""
        self.state.vec_data_list.append({
            "type": "matchloop",
            "instr": match_instr,
            "param": self.state.curr_param,
            "label": match_label,
            "loop_deep": self.state.loop_deep
        })
        
        self.state.curr_instr = ""
        self.state.curr_param = ""
        self.state.curr_label = ""
        self.state.loop_deep += 1
        
        return {"is_matchloop_end": False}
    
    def close_matchloop_block(self, children: List) -> Dict[str, Any]:
        """处理 MatchLoop 结束块
        
        与 Loop 类似：
        - 1 个 V：MBGN 改成 IMATCH，放在这个 V 上
        - 多个 V：MBGN 放在前一个 V 上，MEND 放在最后一个 V 上
        """
        if self.state.loop_deep == 0:
            return {}
        self.state.loop_deep -= 1
        
        if len(self.state.vec_data_list) == 0:
            return {}
        
        # 从末尾收集直到找到对应的 matchloop 标记
        match_content = []
        match_info = None
        
        while len(self.state.vec_data_list) > 0:
            item = self.state.vec_data_list.pop()
            if item.get("type") == "matchloop" and item.get("loop_deep") == self.state.loop_deep:
                match_info = item
                break
            match_content.insert(0, item)
        
        if match_info is None:
            return {}
        
        # 统计 MatchLoop 内的 V 数量
        v_items = [x for x in match_content if x.get("type") == "vector"]
        v_count = len(v_items)
        
        match_instr = match_info["instr"]   # MBGN
        match_param = match_info["param"]   # 循环次数
        match_label = match_info["label"]
        
        if v_count == 0:
            return {}
        elif v_count == 1:
            # 只有 1 个 V：MBGN 改成 IMATCH
            for item in match_content:
                if item.get("type") == "vector":
                    new_data = []
                    for vec in item["data"]:
                        new_data.append((vec[0], vec[1], map_instruction("IMATCH"), match_param, vec[4], vec[5]))
                    self.state.vec_data_list.append({"type": "vector", "data": new_data})
                else:
                    self.state.vec_data_list.append(item)
        else:
            # 多个 V：MBGN 放在前一个 V 上，MEND 放在最后一个 V 上
            # 先检查前一个 V（可能在 vec_data_list 或 pending_vector 中）
            prev_is_vector_in_list = (len(self.state.vec_data_list) > 0 and 
                                      self.state.vec_data_list[-1].get("type") == "vector")
            prev_is_vector_in_pending = (self.state.pending_vector is not None and 
                                         len(self.state.pending_vector) > 0)
            prev_is_vector = prev_is_vector_in_list or prev_is_vector_in_pending
            
            if prev_is_vector:
                # 前一个 V 可能在 vec_data_list 或 pending_vector 中
                if prev_is_vector_in_list:
                    prev_item = self.state.vec_data_list.pop()
                    prev_data = prev_item["data"]
                else:
                    # 在 pending_vector 中
                    prev_data = self.state.pending_vector
                    self.state.pending_vector = None
                
                has_instr = any(vec[2] and vec[2].strip() != "" for vec in prev_data)
                if has_instr:
                    # 如果上一个指令是RPT，就把它的指令的参数减一，然后拿出一行，放LI
                    if prev_data and prev_data[0][2] == map_instruction("Repeat") and int(prev_data[0][3]) > 1:
                        old_rpt_data = []
                        new_v_data = []
                        for vec in prev_data:
                            old_rpt_data.append((vec[0], vec[1], vec[2], int(vec[3]) - 1, vec[4], vec[5]))
                            new_v_data.append((vec[0], vec[1], match_instr, match_param, match_label, vec[5]))
                        self.state.vec_data_list.append({"type": "vector", "data": old_rpt_data})
                        self.state.vec_data_list.append({"type": "vector", "data": new_v_data})
                    else:
                        # 已有指令，先把原 V 放回，MBGN 单独成一行
                        
                        self.state.vec_data_list.append({"type": "vector", "data": prev_data})
                        self.state.vec_data_list.append({
                            "type": "instruction",
                            "instr": match_instr,
                            "param": match_param,
                            "label": match_label
                        })
                else:
                    new_data = []
                    needAdd = False
                    for vec in prev_data:
                        if vec[4] and not needAdd:
                            self.state.vec_data_list.append({"type": "label", "label": vec[4]})
                            needAdd = True
                        new_data.append((vec[0], vec[1], match_instr, match_param, 
                                         match_label, vec[5]))
                    self.state.vec_data_list.append({"type": "vector", "data": new_data})
            else:
                self.state.vec_data_list.append({
                    "type": "instruction",
                    "instr": match_instr,
                    "param": match_param,
                    "label": match_label
                })
            
            # 把 MatchLoop 内的元素加回去，最后一个 V 附加 MEND
            mend_instr = map_instruction("MEND")
            v_index = 0
            for item in match_content:
                if item.get("type") == "vector":
                    v_index += 1
                    if v_index == v_count:
                        new_data = []
                        for vec in item["data"]:
                            new_data.append((vec[0], vec[1], mend_instr, "", vec[4], vec[5]))
                        self.state.vec_data_list.append({"type": "vector", "data": new_data})
                    else:
                        self.state.vec_data_list.append(item)
                else:
                    self.state.vec_data_list.append(item)
        
        # 如果回到最外层，写出
        if self.state.loop_deep == 0 and self.state.left_square_count == 0:
            self._flush_vec_data_list()
            
            self.state.flush_pending_vector(self.handler)
        
        return {"is_matchloop_end": True}

    def open_breakpoit(self, children: List) -> Dict[str, Any]:
        self.state.curr_instr = "BreakPoint"
        self.state.curr_param = "S"
        self.state.left_square_count += 1
        pass

    # TODO
    def close_breakpoit(self, children: List) -> None:
        if len(self.state.vec_data_list) == 0: return {}
        vec_data_list = self.state.vec_data_list.pop()
        self.state.left_square_count -= 1
        new_list = []
        for vec_data in vec_data_list:
            if map_instruction("BreakPoint") in vec_data[2]:
                new_list.append((vec_data[0], vec_data[1],
                map_instruction("BreakPoint"), "", vec_data[4], vec_data[5]))
            elif vec_data[2].strip() != "":
                # 包含微指令错误
                self.handler.on_parse_error("BreakPoint 块中间包含微指令", "")
            else:
                new_list.append((vec_data[0], vec_data[1],
                    map_instruction("BreakPoint"), "E", vec_data[4], vec_data[5]))

        self.state.vec_data_list.append(new_list)
        if self.state.left_square_count == 0:
            if (len(self.state.vec_data_list) > 0):
                for vec_data in self.state.vec_data_list:
                    self.handler.on_vector(vec_data,
                        self.state.curr_instr,
                        self.state.curr_param)
                    self.state.vector_count += 1
                self.state.reset()

    def b_stmt(self, children: List) -> Dict[str, Any]:
        """处理 BreakPoint 语句"""
        self.close_matchloop_block(children)
        self._handle_micro_instruction("BreakPoint", "")
        return {}
    
    # ========================== Call/Macro 语句 ==========================

    @v_args(meta=True)
    def b_procedures__procedure_def(self, meta, children: List) -> Dict[str, Any]:
        """根据索引获取到原始文本，然后当遇到Call的时候会获取文本并处理 Procedure 内容"""
        start = meta.start_pos + self.start_index;
        stop = meta.end_pos + self.start_index;
        proc_name = children[0].value;
        proc_content = (self.text_original[start:stop].strip()
            .strip(proc_name).strip().strip('{').strip('}'));
        self.state.procedures[proc_name] = proc_content;
        return {}

    @v_args(meta=True)
    def b_macrodefs__macrodefs_def(self, meta, children: List) -> Dict[str, Any]:
        """根据索引获取到原始文本，然后当遇到Call的时候会获取文本并处理 Procedure 内容"""
        start = meta.start_pos + self.start_index;
        stop = meta.end_pos + self.start_index;
        macrodef_name = children[0].value;
        macrodef_content = (self.text_original[start:stop].strip()
            .strip(macrodef_name).strip().strip('{').strip('}'));
        self.state.macrodefs[macrodef_name] = macrodef_content;
        return {}

    def call_vec_data_block(self, children: List) -> Dict[str, Any]:
        """处理向量数据块"""
        return self.vec_data_block(children)
    
    def call_vec_block(self, children: List) -> List[Dict[str, Any]]:
        """处理 vec_block（收集所有 vec_data_block） """
        return self.vec_block(children)

    def macro_vec_data_block(self, children: List) -> Dict[str, Any]:
        return self.vec_data_block(children)

    def macro_vec_block(self, children: List) -> List[Dict[str, Any]]:
        return self.vec_block(children)

    def call_stmt(self, children: List) -> Dict[str, Any]:
        """处理 Call 语句"""
        # 通常只有一个
        for child in children:
            if isinstance(child, List):
                for vec_data in child:
                    self.state.replace_vector_list[vec_data.get("signal")] = vec_data.get("data")
            else:
                continue

        tokens = [c.value for c in children if isinstance(c, Token)]
        proc_name = tokens[1] if len(tokens) > 1 else ""
        
        # pre_data = self.state.pending_vector
        # if pre_data:
        #     has_instr = any(vec[2] and vec[2].strip() != "" for vec in pre_data)
        #     if has_instr:
        #         self.state.vec_data_list.append({"type": "vector", "data": pre_data})
        #         self.state.vec_data_list.append({
        #             "type": "instruction",
        #             "instr": "CALL",
        #             "param": proc_name,
        #             "label": self.state.curr_label
        #         })

        #     else:
        #         new_data_list = []
        #         for vec_data in self.state.pending_vector:
        #             new_data_list.append((vec_data[0], vec_data[1], "CALL", proc_name, vec_data[4], vec_data[5]))
        #         self.state.vec_data_list.append({"type": "vector", "data": new_data_list})
        #     self.state.pending_vector = None
        # else:
        #     self.state.vec_data_list.append({
        #             "type": "instruction",
        #             "instr": "CALL",
        #             "param": proc_name,
        #             "label": self.state.curr_label
        #         })
        # self.state.handle_curr()
        # self._flush_vec_data_list()

        # 记录当前的WFT的名字
        self.state.replace_vector_on = True
        current_wft = self.state.current_wft
        self._handle_children_pattern(proc_name, self.state.procedures)

        # 在切换 WFT 之前，先写出 pending_vector（用旧的 WFT）
        self.state.flush_pending_vector(self.handler)
        
        # call结束后，恢复替换
        self.state.replace_vector_on = False
        self.state.replace_vector_list = {}

        # 处理完Call指令以后，要还原成原来的WFT
        self.state.current_wft = current_wft
        self.handler.on_waveform_change(current_wft)

        return {}
    
    def macro_stmt(self, children: List) -> Dict[str, Any]:
        """处理 Macro 语句"""
         # 通常只有一个
        for child in children:
            if isinstance(child, List):
                for vec_data in child:
                    self.state.replace_vector_list[vec_data.get("signal")] = vec_data.get("data")
            else:
                continue
        
        tokens = [c.value for c in children if isinstance(c, Token)]
        macrodef_name = tokens[1] if len(tokens) > 1 else ""
        self.state.replace_vector_on = True
        self._handle_children_pattern(macrodef_name, self.state.macrodefs)
        # macro结束后，恢复替换
        self.state.replace_vector_on = False
        self.state.replace_vector_list = {}
        return {}

    def _handle_children_pattern(self, key: str, contents: Dict[str, str] = {}) -> None:
        """处理 Call 指令"""
        
        # 检查 Procedure 是否存在
        if key in contents:
            content = contents[key]
            try:
                # 解析 Procedure 内容
                proc_tree = self.state.multi_parser.parse(content)
                # 触发回调
                self.handler.on_procedure_call(key, content, self.state.vector_address)
                # 递归处理（使用新的 Transformer 实例）
                transformer = STILParserTransformer(self, self.handler, "", 0, self.state)
                transformer.transform(proc_tree)
                transformer.state.vector_count
                # self.state.vector_count += 
            except LarkError as e:
                Logger.error(f"Procedure '{key}' 解析失败: {e}", exc_info=True)
                self.handler.on_parse_error(f"Procedure '{key}' 解析失败: {e}", "")
                self.handler.on_procedure_call(key, "", self.state.vector_address)
                self.state.vector_address += 1
        else:
            self.handler.on_procedure_call(key, "", self.state.vector_address)
            self.state.vector_address += 1
            self.handler.on_parse_error(f"警告：Procedure '{key}' 未找到", "")

    # ========================== 其他微指令 ==========================
       
    def s_stmt(self, children: List) -> Dict[str, Any]:
        """处理 Stop 语句"""
        tokens = [c.value for c in children if isinstance(c, Token)]
        self._handle_micro_instruction("Stop", tokens[1] if len(tokens) > 1 else "")
        return {}
    
    def g_stmt(self, children: List) -> Dict[str, Any]:
        """处理 Goto 语句"""
        tokens = [c.value for c in children if isinstance(c, Token)]
        self._handle_micro_instruction("Goto", tokens[1] if len(tokens) > 1 else "")
        return {}
    
    def i_stmt(self, children: List) -> Dict[str, Any]:
        """处理 IddqTestPoint 语句"""
        self._handle_micro_instruction("IddqTestPoint", "")
        return {}
    
    def uk_stmt(self, children: List) -> Dict[str, Any]:
        """处理 Unknown 语句"""
        instr = ""
        param = ""
        if len(children) == 1 and isinstance(children[0], Token):
            instr = children[0].value.strip()
        elif len(children) == 2 and isinstance(children[0], Token) and isinstance(children[1], Token):
            instr = children[0].value.strip()
            param = children[1].value.strip()
        self.handler.on_parse_error("Unknown 语句", children[0].value.strip())
        self._handle_micro_instruction(instr, param)
        return {}

    def _handle_micro_instruction(self, instr: str, param: str = "") -> bool:
        """处理微指令的通用方法
        
        如果在循环/块中，存入 vec_data_list；否则尝试附加到 pending_vector
        
        Args:
            instr: 指令名称
            param: 指令参数
            
        Returns:
            True 如果指令被处理，False 如果指令被禁用
        """
        # 检查禁用指令
        if is_disabled(instr):
            self.handler.on_parse_error(
                f"指令 '{instr}' 已被禁用，跳过解析",
                f"禁用列表: {DISABLED_INSTRUCTIONS}"
            )
            return False
        
        mapped_instr = map_instruction(instr)
        label = self.state.curr_label
        
        # 如果在循环/块中，存入 vec_data_list
        if self.state.loop_deep > 0 or self.state.left_square_count > 0:
            self.state.vec_data_list.append({
                "type": "instruction",
                "instr": mapped_instr,
                "param": param,
                "label": label
            })
        else:
            # 不在循环中，尝试附加到 pending_vector
            attached = self.state.attach_instr_to_pending(
                self.handler, mapped_instr, param, label)
            
            if not attached:
                # 没有 pending_vector 或已有指令，用 Q 占位单独写一行
                self.handler.on_micro_instruction(label, mapped_instr, param, self.state.vector_address)
                self.state.vector_address += 1
                self.state.vector_count += 1
            
        self.state.curr_label = ""
        self.state.curr_instr = ""
        self.state.curr_param = ""
        return True
    # ========================== 跳过的节点 ==========================
    def annotation(self, children: List) -> None:
        """跳过注释"""
        # TODO
        self.state.flush_pending_vector(self.handler)

        ann = "";
        for child in children:
            if isinstance(child, Token) and child.type == "ANN_TEXT":
                ann += child.value + " "
        self.handler.on_annotation(ann)

        return None
    
    def open_pattern_block(self, children: List) -> None:
        """跳过 Pattern 开始块"""
        return None
    
    def close_pattern_block(self, children: List) -> None:
        """跳过 Pattern 结束块"""
        return None

class PatternStreamParserTransformer:
    """STIL Pattern 流式解析器 - Transformer 版本
    
    使用 Lark Transformer 处理解析树，提供更声明式的编程方式。
    """
    
    def __init__(self, stil_file: str, event_handler: STILEventHandler, 
                 debug: bool = False):
        """初始化解析器
        
        Args:
            stil_file: STIL 文件路径
            event_handler: 事件处理器实例
            debug: 是否开启调试模式
        """
        self.stil_file = stil_file
        self.handler = event_handler
        self.debug = debug

        # 解析结果存储
        self.used_signals: List[str] = []
        #self.pat_header: List[str] = []
        self.timings: Dict[str, List[TimingData]] = {}

        # 共享状态
        self.state = ParserState()
        
        # 解析器初始化
        self.multi_parser: Optional[Lark] = None
        self._init_parser()
        self.state.multi_parser = self.multi_parser
        
        # 停止标志
        self._stop_requested = False
    
    def _init_parser(self) -> None:
        """初始化 Pattern 语句解析器"""
        if getattr(sys, 'frozen', False):
            base_path = sys._MEIPASS
        else:
            base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        
        grammar_base = os.path.join(base_path, "Semi_ATE", "STIL", "parsers", "grammars")
        pattern_statements_file = os.path.join(grammar_base, "pattern_statements.lark")
        
        try:
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
            
            self.multi_parser = Lark(
                multi_grammar,
                start="start",
                parser="lalr",
                import_paths=[grammar_base],
                propagate_positions=True
            )
            self.handler.on_log("Pattern 语句解析器初始化成功 (1.0 版本)")
        except Exception as e:
            Logger.error(f"Pattern 语句解析器初始化失败: {e}", exc_info=True)
            self.handler.on_log(f"Pattern 语句解析器初始化失败: {e}")
            raise
    
    def stop(self) -> None:
        """请求停止解析"""
        self._stop_requested = True
    
    def _extract_first_vector_signals(self, tree) -> List[str]:
            """从第一个V块提取使用的信号/信号组名"""
            pat_header: List[str] = []
            
            for node in tree.iter_subtrees():
                if isinstance(node, Tree) and node.data.endswith("vec_data_block"):
                    vec_tokens = [t.value for t in node.scan_values(lambda c: isinstance(c, Token))]
                    if vec_tokens:
                        pat_header.append(vec_tokens[0].strip())
            
            return pat_header

    def read_stil_overview(self, print_log: bool = True) -> List[str]:
        """读取STIL文件，提取实际使用的信号列表"""

        # 先读取文件第一行，看是否包含 STIL space+ Double space+;字样(STIL 1.0;)
        # 如果不包含，说明不是STIL文件， 提示用户后返回
        with open(self.stil_file, 'r', encoding='utf-8') as f:
            first_line = f.readline().strip()
            if not first_line.startswith('STIL 1.0;'):
                self.handler.on_parse_error("选择的文件并非STIL文件，无法解析...")
                return 0
                
        self.handler.on_log("开始读取STIL文件...")

        if not os.path.exists(self.stil_file):
            self.handler.on_parse_error("文件不存在 - {self.stil_file}")
            return []
        
        header_buffer = ""
        buffer_lines = []
        is_pattern, first_v_found = False, False
        
        try:
            with open(self.stil_file, 'r', encoding='utf-8') as f:
                self.handler.on_log("正在解析文件头部（Signals/SignalGroups）...")
                
                for index, line in enumerate(f):
                    if index == 0 and not line.strip().startswith('STIL'):
                        self.handler.on_log("选择的文件并非STIL文件，无法解析...")
                        return []
                    
                    if self._stop_requested:
                        return []
                    
                    if line.strip().startswith('Pattern ') and '{' in line:
                        is_pattern = True
                        from Semi_ATE.STIL.parsers.STILParser import STILParser
                        parser = STILParser(self.stil_file, propagate_positions=True, debug=self.debug)
                        tree = parser.parse_content(header_buffer)
                        transformer = STILParserTransformer(self, self.handler, header_buffer, 0, self.state)
                        transformer.transform(tree) 
                        
                        if print_log:
                            signal_count = len(self.state.signal_dict)
                            self.handler.on_log(f"找到 {signal_count    } 个信号定义")
                            signal_group_count = len(self.state.signal_group)
                            self.handler.on_log(f"找到 {signal_group_count} 个信号组")
                            timing_count = len(self.get_timings())
                            self.handler.on_log(f"找到 {timing_count} 个波形表定义")
                            for wft_name, timing_list in self.get_timings().items():
                                self.handler.on_log(f"  波形表 [{wft_name}] 包含 {len(timing_list)} 条Timing定义:")
                                for td in timing_list:
                                    map_wfc = td.vector_replacement;
                                    timing_str = f"    {td.signal}, {td.period}, {td.wfc}{("="+map_wfc) if map_wfc else ''},"
                                    timing_str += f" {td.t1}, {td.e1}, {td.t2}, {td.e2}, {td.t3}, {td.e3}, {td.t4}, {td.e4}"
                                    self.handler.on_log(timing_str)
                        continue
                    
                    if not is_pattern:
                        header_buffer += line
                        continue

                    if is_pattern and not first_v_found:
                        try:
                            if line.strip().startswith('//'):
                                continue
                            
                            buffer_lines.append(line)
                            statement_buffer = "".join(buffer_lines).strip()
                            
                            if ('{' in statement_buffer and '}' in statement_buffer
                                and statement_buffer.count('{') == statement_buffer.count('}')):
                                # 初始化临时解析器（用于提取第一个 V 的信号）
                                tree = self.multi_parser.parse(statement_buffer)
                                self.pat_header = self._extract_first_vector_signals(tree)
                                # pat_header 去重但保持顺序（V 块中信号/信号组的顺序很重要）
                                seen = set()
                                unique_pat_header = []
                                for item in self.pat_header:
                                    if item not in seen:
                                        seen.add(item)
                                        unique_pat_header.append(item)
                                self.pat_header = unique_pat_header
                                if self.pat_header:
                                    first_v_found = True
                                    break
                                
                                buffer_lines.clear()
                        except Exception as e:
                            Logger.error(f"读取文件失败: {e}", exc_info=True)
                            self.handler.on_parse_error(f"读取文件失败: {e}")
            
            self.used_signals = []
            for key in self.pat_header:
                if key in self.state.signal_group:
                    self.used_signals.extend(self.state.signal_group[key])
                elif key in self.state.signal_dict:
                    self.used_signals.append(key)
            
            if print_log:
                self.handler.on_log(f"STIL中使用了 {len(self.used_signals)} 个信号:")
                for i, sig in enumerate(self.used_signals):
                    self.handler.on_log(f"  {i+1}. {sig}")
            
            return self.used_signals
        
        except LarkError as e:
            # 触发错误回调
            Logger.error(f"读取文件失败(LarkError): {e}", exc_info=True)
            self.handler.on_parse_error(f"读取文件失败: {e}")
        except Exception as e:
            Logger.error(f"读取文件失败: {e}", exc_info=True)
            self.handler.on_parse_error(f"读取文件失败: {e}")
            return []

            

    def parse_patterns(self) -> int:
        """流式解析 Pattern 块
        
        Returns:
            解析的向量总数
        """
        
        # 2. 初始化状态
        self.state.vector_count = 0
        self.state.current_wft = ""
        
        # 3. 触发解析开始回调
        self.handler.on_parse_start()
        
        # 4. 流式解析 Pattern 并触发回调
        buffer_lines = []
        is_pattern = False
        transformer = STILParserTransformer(self, self.handler, "", 0, self.state)
        pattern_parser_list = []
        try:
            with open(self.stil_file, 'r', encoding='utf-8', buffering=1024*1024) as f:
                for line in f:
                    self.state.read_size += len(line.encode('utf-8'))
                    if self._stop_requested:
                        break                

                    # 检测 Pattern 块开始
                    if line.strip().startswith('Pattern '):
                        buffer_lines.clear()
                        pattern_burst_name = line.strip().split(' ')[1]
                        if pattern_burst_name in pattern_parser_list:
                            self.handler.on_parse_error(f"Pattern 块 {pattern_burst_name} 重复定义")
                            return
                        if (pattern_burst_name in
                         self.state.pattern_burst_dict[self.state.pattern_burst_name]["PatList"]):
                            is_pattern = True
                            if len(pattern_parser_list) == 0:
                                self.handler.on_vector_start(pattern_burst_name)
                                pattern_parser_list.append(pattern_burst_name)
                            self.handler.on_label(pattern_burst_name)
                            continue
                        else:
                            is_pattern = False
                            continue
                    
                    if not is_pattern:
                        continue
                    
                    # 跳过注释
                    if line.strip().startswith('//'):
                        continue
                    
                    buffer_lines.append(line)
                    statement_buffer = "".join(buffer_lines).strip()
                    
                    # 完整语句检测
                    if (statement_buffer.endswith(';') and '{' not in statement_buffer and '}' not in statement_buffer
                        or ('{' in statement_buffer and '}' in statement_buffer
                        and statement_buffer.count('{') == statement_buffer.count('}'))):
                        try:
                            # 解析并转换
                            tree = self.multi_parser.parse(statement_buffer)
                            transformer.transform(tree)
                        except LarkError as e:
                            # 触发错误回调
                            Logger.warning(f"解析失败(LarkError): {e}")
                            self.handler.on_parse_error(str(e), statement_buffer)
                           
                        except Exception as e:
                            Logger.error(f"解析异常: {e}", exc_info=True)
                            self.handler.on_parse_error(str(e), "")
                        
                        buffer_lines.clear()
               
            # 解析并转换
            transformer.v_stmt([])
        except Exception as e:
            Logger.error(f"文件读取错误: {e}", exc_info=True)
            self.handler.on_parse_error(str(e), "")
        
        # 5. 触发解析完成回调
        self.handler.on_parse_complete(self.state.vector_count)
        
        return self.state.vector_count

    def get_signals(self) -> Dict[str, str]:
        return self.state.signal_dict

    def get_signal_groups(self) -> Dict[str, List[str]]:
        return self.state.signal_group

    def get_used_signals(self) -> List[str]:
        return self.used_signals
    
    def get_pat_header(self) -> List[str]:
        return self.pat_header

    def get_timings(self) -> Dict[str, List[TimingData]]:
        return self.state.timing_dict[self.state.timing_domain_name]

    def get_headers(self) -> Dict[str, str]:
        return self.state.headers

