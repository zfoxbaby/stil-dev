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
        self.vector_count = 0
        self.vector_address = 0  # 向量地址（用于生成自动 Label 和输出）
        self.loop_deep = 0
        self.left_square_count = 0
        self.vec_data_list = []
        self.current_wft = ""
        self.curr_label = ""
        self.curr_instr = ""
        self.curr_param = ""
        self.procedures: Dict[str, str] = {}
        self.macrodefs: Dict[str, str] = {}
        self.multi_parser: Optional[Lark] = None
        self.headers: Dict[str, str] = {}
        # 如果出现Call、Macro会出现替换功能，Key是信号/信号组，Value是Vector
        self.replace_vector_list : Dict[str, str] = {}
        self.debug = False

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

class STILParserTransformer(Transformer):
    """Pattern 语句转换器
    
    使用 Lark Transformer 自动遍历和处理解析树。
    每个方法对应一个语法规则。
    """
    
    def __init__(self, parser: PatternStreamParserTransformer,
          handler: STILEventHandler,
          text_original: str,
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
        self.text_original = text_original;

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
 
    # ========================== Label 处理 ==========================
    def LABEL(self, token: Token) -> Dict[str, Any]:
        """处理 LABEL token"""
        label_name = token.value.strip('"').strip("'").rstrip(':')
        self.state.curr_label = label_name
        self.handler.on_label(label_name)
        return {"type": "label", "value": label_name}
    
    # ========================== W 语句（波形表切换）==========================
    
    def w_stmt(self, children: List) -> Dict[str, Any]:
        """处理 W 语句（波形表切换）"""
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
        """处理 V 语句, 如果包含微指令就不是v_stmt
        """
        if (len(children) == 0 and len(self.state.vec_data_list) == 0):
            return {}
        
        # 检查禁用指令
        if self.state.curr_instr and is_disabled(self.state.curr_instr):
            self.parser.stop()
            # 结束解析，因为存在不支持的指令，解析出来也不准确
            self.handler.on_parse_complete(self.state.vector_count)
            self.handler.on_parse_error(
                f"机型不支持 '{self.state.curr_instr}' 指令，转换中止！！！", 
                f"不支持的指令列表: {DISABLED_INSTRUCTIONS}"
            )
            return {}
        
        vec_data_list = []
        for child in children:
            # 收集向量数据（vec_block 返回的列表）
            if not isinstance(child, List):
                continue
            for item in child:
                # 映射指令
                if self.state.curr_instr == "Loop":
                    self.state.curr_instr = map_instruction("Loop", str(self.state.loop_deep - 1))
                elif self.state.curr_instr:
                    # 其他指令通过映射表转换
                    self.state.curr_instr = map_instruction(self.state.curr_instr)
                # 如果存在需要替换的Vectors，则替换，一般出现再Call和Macro指令的参数中
                replace_signal_vectors = self.state.replace_vector_list.get(item.get("signal"), "")
                vectors = item.get("data")
                if replace_signal_vectors:
                    vectors = replace_signal_vectors
                # 6 元组：(signal, data, instr, param, label, vector_address)
                vec_data_list.append((item.get("signal"), vectors, 
                    self.state.curr_instr, self.state.curr_param, 
                    self.state.curr_label, self.state.vector_address))
        if (len(vec_data_list) > 0):
            self.state.vec_data_list.append(vec_data_list)
            self.state.vector_address += 1  # 每个向量地址递增
        self.state.handle_curr()
        # 如果在循环中，就先不写入，等循环结束时，处理好循环语句再写入
        if self.state.loop_deep > 0 or self.state.left_square_count > 0:
            return {}
        if (len(self.state.vec_data_list) > 0):
            for vec_data in self.state.vec_data_list:
                self.handler.on_vector(vec_data,
                    self.state.curr_instr,
                    self.state.curr_param)
                self.state.vector_count += 1
            self.state.reset()
            return {"v-data": self.state.vec_data_list}
        return {}
    
    def _expand_vec_data(self, data: str) -> str:
        """展开向量数据中的重复指令"""
        #f \r2 f\w0000 0101
        pattern = r'\\r(\d+)\s+([^\s\\]+)'
        
        def replace_repeat(match):
            repeat_count = int(match.group(1))
            repeat_content = match.group(2)
            return repeat_content * repeat_count
        
        result = data
        while '\\r' in result:
            new_result = re.sub(pattern, replace_repeat, result)
            if new_result == result:
                break
            result = new_result
        
        result = re.sub(r'\s+', '', result)
        return result
    
    # ========================== Loop 语句 ==========================
    def KEYWORD_LOOP(self, token: Token) -> Dict[str, Any]:
        """处理 LABEL token"""
        self.state.curr_instr = token.value.strip('"').strip("'").rstrip(':')
        return {"type": "KEYWORD_LOOP", "value": self.state.curr_instr}

    def LOOP_COUNT(self, token: Token) -> Dict[str, Any]:
        """处理 LABEL token"""
        self.state.curr_param = token.value.strip('"').strip("'").rstrip(':')
        return {"type": "LOOP_COUNT", "value": self.state.curr_param}
    
    def open_loop_block(self, children: List) -> Dict[str, Any]:
        """处理 Loop 开始块"""
        self.state.loop_deep += 1;
        return {
            "is_loop_end": False
        }

    def close_loop_block(self, children: List) -> Dict[str, Any]:
        """处理 Loop 结束块"""
        self.state.loop_deep -= 1
        # 移除最后一个 vec_data_list
        if len(self.state.vec_data_list) == 0: return {}
        vec_data_list = self.state.vec_data_list.pop()
        # 从self.state.vec_data_list中找到 LI{m} 对应的vec_data_list
        loop_label = ""
        for vec_data in self.state.vec_data_list:
            # vec_data中拿到第一个List，从中找到 Label
            for vec_data_item in vec_data:
                if f"{map_instruction("Loop")}{self.state.loop_deep}" in vec_data_item[2]:
                    if vec_data_item[4]:
                        loop_label = vec_data_item[4]
                        break
                    else:
                        loop_label = f"0x{vec_data_item[5]:06X}"
                        break
            if loop_label:
                break
        # - 如果只有一个 V 且是 LI，改成 RPT
        # - 否则最后一个改成 JNI{m}，跳转到 loop_label
        new_list = []
        for vec_data in vec_data_list:
            if map_instruction("Loop") in vec_data[2]:
                # 上一个如果是LI，说明这个LOOP只有一个V块, LI -> RPT
                new_list.append((vec_data[0], vec_data[1],
                 map_instruction("Repeat"), vec_data[3], vec_data[4], vec_data[5]))
            elif vec_data[2].strip() != "":
                # Loop块中间要么是1个V，要么前后各有一个V，否则指令没有地方放
                self.handler.on_parse_error("Loop块中间要么是1个V，要么前后各有一个V，否则指令没有地方放", "")
            else:
                new_list.append((vec_data[0], vec_data[1],
                     f"{map_instruction("LoopEnd")}{self.state.loop_deep}",
                     loop_label, vec_data[4], vec_data[5]))

        self.state.vec_data_list.append(new_list)
        
        if self.state.loop_deep == 0:
            if (len(self.state.vec_data_list) > 0):
                for vec_data in self.state.vec_data_list:
                    self.handler.on_vector(vec_data,
                        self.state.curr_instr,
                        self.state.curr_param)
                    self.state.vector_count += 1
                self.state.reset()
        return {
            "is_loop_end": True
        }
    
    # ========================== MatchLoop 语句 ==========================
    def KEYWORD_MATCH_LOOP(self, token: Token) -> None:
        """处理 MatchLoop 语句"""
        self.state.curr_instr = token.value.strip('"').strip("'").rstrip(':')
    
    def MATCHLOOP_COUNT(self, token: Token) -> None:
        """处理 MatchLoop 语句"""
        self.state.curr_param = token.value.strip('"').strip("'").rstrip(':')
    
    def MATCHLOOP_INF(self, token: Token) -> None:
        """处理 MatchLoop 语句"""
        self.state.curr_param = "0xFFFFFF"

    def open_matchloop_block(self, children: List) -> Dict[str, Any]:
        """处理 MatchLoop 开始块"""
        self.state.loop_deep += 1;
        return {
            "is_matchloop_end": False
        }
    
    def close_matchloop_block(self, children: List) -> Dict[str, Any]:
        """处理 MatchLoop 结束块"""
        if (self.state.loop_deep == 0) :
            return {}
        self.state.loop_deep -= 1;
        # 拿到最后一个V块，添加微指令为 MEND
        if len(self.state.vec_data_list) == 0: return {}
        vec_data_list = self.state.vec_data_list.pop()
        new_list = []
        for vec_data in vec_data_list:
            if map_instruction("MBGN") in vec_data[2]:
                # 此时是单行Match IMATCH
                # 上一个如果是LI，说明这个LOOP只有一个V块, LI -> RPT
                new_list.append((vec_data[0], vec_data[1],
                 map_instruction("IMATCH"),
                 vec_data[3], vec_data[4], vec_data[5]))
            elif vec_data[2].strip() != "":
                # 包含微指令错误
                self.handler.on_parse_error("MatchLoop 块中间包含微指令", "")
            else:
                new_list.append((vec_data[0], vec_data[1],
                    map_instruction("MEND"), "", vec_data[4], vec_data[5]))

        self.state.vec_data_list.append(new_list)
        
        if self.state.loop_deep == 0:
            if (len(self.state.vec_data_list) > 0):
                for vec_data in self.state.vec_data_list:
                    self.handler.on_vector(vec_data,
                        self.state.curr_instr,
                        self.state.curr_param)
                    self.state.vector_count += 1
                self.state.reset()
        return {
            "is_matchloop_end": True
        }

    def open_breakpoit(self, children: List) -> Dict[str, Any]:
        self.state.curr_instr = "BreakPoint"
        self.state.curr_param = "S"
        self.state.left_square_count += 1
        pass

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
        # self._handle_micro_instruction("BreakPoint", "")
        return {}
    
    # ========================== Call/Macro 语句 ==========================

    @v_args(meta=True)
    def b_procedures__procedure_def(self, meta, children: List) -> Dict[str, Any]:
        """根据索引获取到原始文本，然后当遇到Call的时候会获取文本并处理 Procedure 内容"""
        start = meta.start_pos;
        stop = meta.end_pos;
        proc_name = children[0].value;
        proc_content = (self.text_original[start:stop].strip()
            .strip(proc_name).strip().strip('{').strip('}'));
        self.state.procedures[proc_name] = proc_content;
        return {}

    @v_args(meta=True)
    def b_macrodefs__macrodefs_def(self, meta, children: List) -> Dict[str, Any]:
        """根据索引获取到原始文本，然后当遇到Call的时候会获取文本并处理 Procedure 内容"""
        start = meta.start_pos;
        stop = meta.end_pos;
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
        # 记录当前的WFT的名字
        current_wft = self.state.current_wft
        self._handle_children_pattern(proc_name, self.state.procedures)
        # 处理完Call指令以后，要还原成原来的WFT
        self.state.current_wft = current_wft
        self.handler.on_waveform_change(current_wft)

        # call结束后，恢复替换
        self.state.replace_vector_list = {}
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
        self._handle_children_pattern(macrodef_name, self.state.macrodefs)
        # macro结束后，恢复替换
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
                transformer = STILParserTransformer(self, self.handler, "", self.state)
                transformer.transform(proc_tree)
                transformer.state.vector_count
                # self.state.vector_count += 
            except LarkError as e:
                self.handler.on_parse_error(f"Procedure '{key}' 解析失败: {e}", "")
                self.handler.on_procedure_call(key, "", self.state.vector_address)
                self.state.vector_address += 1
                if self.state.debug:
                    print(f"警告：Procedure '{key}' 解析失败: {e}")
        else:
            self.handler.on_procedure_call(key, "", self.state.vector_address)
            self.state.vector_address += 1
            if self.state.debug:
                print(f"警告：Procedure '{key}' 未找到")

    # ========================== 其他微指令 ==========================
    def _handle_micro_instruction(self, instr: str, param: str = "") -> bool:
        """处理微指令的通用方法
        
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
        
        # 映射并触发回调
        mapped_instr = map_instruction(instr)
        self.handler.on_micro_instruction(self.state.curr_label,
         mapped_instr, param, self.state.vector_address)
        self.state.vector_address += 1
        self.state.vector_count += 1
        self.state.curr_label = ""
        self.state.curr_instr = ""
        self.state.curr_param = ""
        return True
    
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
    # ========================== 跳过的节点 ==========================
    def annotation(self, children: List) -> None:
        """跳过注释"""
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
        
        self.signals: Dict[str, str] = {}  # {信号名: 信号类型}
        self.signal_groups: Dict[str, List[str]] = {}
        self.used_signals: List[str] = []
        self.pat_header: List[str] = []
        self.timings: Dict[str, List[TimingData]] = {}

        # 共享状态
        self.state = ParserState()
        self.state.debug = debug
        
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
            if self.debug:
                print("Pattern 语句解析器初始化成功 (Transformer 版本)")
        except Exception as e:
            if self.debug:
                print(f"Pattern 语句解析器初始化失败: {e}")
            raise
    
    def _extract_procedures_or_macrodefs(self, key: str) -> None:
        """提取 STIL 文件中的 Procedures 或 MacroDefs 块"""

        is_procedures = False
        buffer_lines = []
        statement_buffer = ""

        try:
            with open(self.stil_file, 'r', encoding='utf-8') as f:
                for line in f:
                    l = line.strip()
                    if l.startswith('Pattern '):
                        f.close()
                        break
                    if l.startswith(key):
                        is_procedures = True
                    if is_procedures:
                        buffer_lines.append(line)
                        statement_buffer = "".join(buffer_lines).strip()
                        if statement_buffer.count('{') == statement_buffer.count('}'):
                            # 结束文件读取，关闭文件流
                            f.close()
                            break
                    else:
                        buffer_lines.append(line)
            # 解析 Procedure 内容
            from Semi_ATE.STIL.parsers.STILParser import STILParser
            parser = STILParser(self.stil_file, propagate_positions=True, debug=self.debug)
            if (statement_buffer == ""): return
            proc_tree = parser.parse_content(statement_buffer)
            # proc_tree = self.state.multi_parser.parse(statement_buffer)
            # 使用新的 Transformer 实例
            transformer = STILParserTransformer(self, self.handler, statement_buffer, self.state)
            transformer.transform(proc_tree)
                
        except Exception as e:
            self.handler.on_parse_error(str(e), "提取 Procedures 失败")
            if self.debug:
                print(f"提取 Procedures 失败: {e}")
    
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
        is_pattern = False
        first_v_found = False
        
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
                        transformer = STILParserTransformer(self, self.handler, "", self.state)
                        transformer.transform(tree) 
                        # 使用通用解析工具
                        from STILParserUtils import STILParserUtils
                        parser_utils = STILParserUtils(debug=self.debug)
                        self.signals = parser_utils.extract_signals(tree)
                        self.signal_groups = parser_utils.extract_signal_groups(tree)
                        self.timings = parser_utils.extract_timings(tree, self.signals,
                             self.signal_groups, self.handler)
                        
                        if print_log:
                            self.handler.on_log(f"找到 {len(self.signals)} 个信号定义")
                            self.handler.on_log(f"找到 {len(self.signal_groups)} 个信号组")
                            self.handler.on_log(f"找到 {len(self.timings)} 个波形表定义")
                            for wft_name, timing_list in self.timings.items():
                                self.handler.on_log(f"  波形表 [{wft_name}] 包含 {len(timing_list)} 条Timing定义:")
                                for td in timing_list:
                                    map_wfc = td.vector_replacement;
                                    timing_str = f"    {td.signal}, {td.period}, {td.wfc}{("="+map_wfc) if map_wfc else ''}, {td.t1}, {td.e1}"
                                    if td.t2:
                                        timing_str += f", {td.t2}, {td.e2}"
                                    if td.t3:
                                        timing_str += f", {td.t3}, {td.e3}"
                                    if td.t4:
                                        timing_str += f", {td.t4}, {td.e4}"
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
                            self.handler.on_parse_error(f"读取文件失败: {e}")
            
            self.used_signals = []
            for key in self.pat_header:
                if key in self.signal_groups:
                    self.used_signals.extend(self.signal_groups[key])
                elif key in self.signals:
                    self.used_signals.append(key)
            
            if print_log:
                self.handler.on_log(f"STIL中使用了 {len(self.used_signals)} 个信号:")
                for i, sig in enumerate(self.used_signals):
                    self.handler.on_log(f"  {i+1}. {sig}")
            
            return self.used_signals
        
        except LarkError as e:
            # 触发错误回调
            self.handler.on_parse_error(f"读取文件失败: {e}")
        except Exception as e:
            self.handler.on_parse_error(f"读取文件失败: {e}")
            return []

            

    def parse_patterns(self) -> int:
        """流式解析 Pattern 块
        
        Returns:
            解析的向量总数
        """
        # 1. 提取 Procedures
        self._extract_procedures_or_macrodefs("Procedures")
        self._extract_procedures_or_macrodefs("MacroDefs")
        
        # 2. 初始化状态
        self.state.vector_count = 0
        self.state.current_wft = ""
        
        # 3. 触发解析开始回调
        self.handler.on_parse_start()
        
        # 4. 流式解析 Pattern 并触发回调
        buffer_lines = []
        is_pattern = False
        transformer = STILParserTransformer(self, self.handler, "", self.state)
        try:
            with open(self.stil_file, 'r', encoding='utf-8') as f:
                for line in f:
                    if self._stop_requested:
                        break                

                    # 检测 Pattern 块开始
                    if line.strip().startswith('Pattern '):
                        is_pattern = True
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
                            self.handler.on_parse_error(str(e), statement_buffer)
                            if self.debug:
                                print(f"解析失败: {statement_buffer[:50]}...")
                        except Exception as e:
                            self.handler.on_parse_error(str(e), "")
                            if self.debug:
                                print(f"其他错误: {e}")
                        
                        buffer_lines.clear()
            # 解析并转换
            transformer.v_stmt([])
        except Exception as e:
            self.handler.on_parse_error(str(e), "")
            if self.debug:
                print(f"文件读取错误: {e}")
        
        # 5. 触发解析完成回调
        self.handler.on_parse_complete(self.state.vector_count)
        
        return self.state.vector_count

    def get_signals(self) -> Dict[str, str]:
        return self.signals

    def get_signal_groups(self) -> Dict[str, List[str]]:
        return self.signal_groups

    def get_used_signals(self) -> List[str]:
        return self.used_signals
    
    def get_pat_header(self) -> List[str]:
        return self.pat_header

    def get_timings(self) -> Dict[str, List[TimingData]]:
        return self.timings

