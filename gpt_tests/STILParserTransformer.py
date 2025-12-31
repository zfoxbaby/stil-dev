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

# 复用原有的 PatternEventHandler
from STILParserUtils import PatternEventHandler

class STILParserTransformer(Transformer):
    """Pattern 语句转换器
    
    使用 Lark Transformer 自动遍历和处理解析树。
    每个方法对应一个语法规则。
    """
    
    def __init__(self, handler: PatternEventHandler,
          text_original: str,
          parser_state:ParserState):
        """初始化 Transformer
        
        Args:
            handler: 事件处理器
            parser_state: 解析器状态（共享状态对象）
        """
        super().__init__()
        self.handler = handler
        self.state = parser_state
        self.text_original = text_original;

    # ========================== Token 处理 ==========================
    def LABEL(self, token: Token) -> Dict[str, Any]:
        """处理 LABEL token"""
        label_name = token.value.strip('"').strip("'").rstrip(':')
        self.state.curr_label = label_name
        # self.handler.on_label(label_name)
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
        vec_data_list = []
        for child in children:
            # 收集向量数据（vec_block 返回的列表）
            if not isinstance(child, List):
                continue
            for item in child:
                if (self.state.curr_instr == "Loop"):
                    self.state.curr_instr = f"LI{self.state.loop_deep - 1}"
                # 6 元组：(signal, data, instr, param, label, vector_address)
                vec_data_list.append((item.get("signal"), item.get("data"), 
                    self.state.curr_instr, self.state.curr_param, 
                    self.state.curr_label, self.state.vector_address))
        if (len(vec_data_list) > 0):
            self.state.vec_data_list.append(vec_data_list)
            self.state.vector_address += 1  # 每个向量地址递增
        self.state.handle_curr_instr()
        self.state.handle_curr_param()
        self.state.handle_curr_label()
        # 如果在循环中，就先不写入，等循环结束时，处理好循环语句再写入
        if self.state.loop_deep > 0:
            return {}
        if (len(self.state.vec_data_list) > 0):
            for vec_data in self.state.vec_data_list:
                self.handler.on_vector(vec_data,
                    self.state.handle_curr_instr(),
                    self.state.handle_curr_param())
                self.state.vector_count += 1
        self.state.reset()
        return {}
    
    def _expand_vec_data(self, data: str) -> str:
        """展开向量数据中的重复指令"""
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
        self.state.supplment_loop_instr[self.state.loop_deep] = self.state.curr_param
        return {
            "is_loop_end": False
        }

    def close_loop_block(self, children: List) -> Dict[str, Any]:
        """处理 Loop 结束块"""
        loop_instr_param = self.state.supplment_loop_instr.pop(self.state.loop_deep)
        self.state.loop_deep -= 1
        # 移除最后一个 vec_data_list
        vec_data_list = self.state.vec_data_list.pop()
        # 从self.state.vec_data_list中找到 LI{m} 对应的vec_data_list
        loop_label = ""
        for vec_data in self.state.vec_data_list:
            # vec_data中拿到第一个List，从中找到 Label
            for vec_data_item in vec_data:
                if f"LI{self.state.loop_deep}" in vec_data_item[2]:
                    if vec_data_item[4]:
                        loop_label = vec_data_item[4]
                        break
                    else:
                        loop_label = f"0x{vec_data_item[5]:06X}"
                        break
            if loop_label:
                break
        # 生成新的元素：
        # - 如果只有一个 V 且是 LI，改成 RPT
        # - 否则最后一个改成 JNI{m}，跳转到 loop_label
        needRepair = False
        supplment_LI_vector_datas = []
        last_LI_index = -1

        new_list = []
        for vec_data in vec_data_list:
            if "LI" in vec_data[2]:
                # 上一个如果是LI，说明这个LOOP只有一个V块, LI -> RPT
                new_list.append((vec_data[0], vec_data[1], "RPT", vec_data[3], vec_data[4], vec_data[5]))
            elif "JNI" in vec_data[2]:
                # 如果最后一个是JNI说明内部嵌套循环，并且当前层的循环没有最后一个V块， 生成一个空的V块，wfc都用.代替
                # 如果此时loop_label也没找到，说明上一层LOOP没有匹配到起始块，就在self.state.vec_data_list中从后往前找到第一个LI{m}的位置
                if not loop_label:
                    self.state.supplment_loop_label -= 1
                    loop_label = self.state.supplment_loop_label
                    for i, vec_datas in enumerate(self.state.vec_data_list): 
                        if "LI" in vec_datas[0][2]:
                            last_LI_index = i
                            break
                new_list.append((vec_data[0], "." * len(vec_data[1]),
                    f"JNI{self.state.loop_deep}", loop_label, vec_data[4], vec_data[5]))
                needRepair = True
            else:
                # 如果self.state.vec_data_list是空则异常
                # if len(self.state.vec_data_list) == 0:
                #     raise Exception("JNI丢失LI的块，但是self.state.vec_data_list是空的")
                # 说明有不止一个V
                # 非 LI 的最后一个改成 JNI，param 改为 loop_label
                # 要匹配LIm如果匹配不到就在最顶层插入一个空块作为LI{m}
                # for i, vec_datas in enumerate(self.state.vec_data_list): 
                #     for vec_data in vec_datas:
                #         if "LI" in vec_data[2]:
                #             last_LI_index = i
                #             break
                # # 如果没找到last_LI_index就插入一个
                # if last_LI_index == -1:
                #     for vec_data in vec_data_list:
                #         supplment_LI_vector_datas.append((vec_data[0], "." * len(vec_data[1]),
                #             f"LI{self.state.loop_deep}", loop_instr_param, loop_label, vec_data[5]))
                #     self.state.vec_data_list.insert(0, supplment_LI_vector_datas)
                #     self.state.supplment_loop_label -= 1
                new_list.append((vec_data[0], vec_data[1],
                    f"JNI{self.state.loop_deep}", loop_label, vec_data[4], vec_data[5]))
        
        # 因为当前层没有最后一个V块，所以刚才移出来的要放回去
        if needRepair:
            self.state.vec_data_list.append(vec_data_list)

        # 然后在它之前插入一个LI{m-1},并自动生成一个Label放在LI{m-1}之前，并作为当前JNI{m}的label，作为loop_label
        if last_LI_index != -1:
            for vec_data in vec_data_list:
                supplment_LI_vector_datas.append((vec_data[0], "." * len(vec_data[1]),
                    f"LI{self.state.loop_deep}", loop_instr_param, loop_label, vec_data[5]))
            # 把supplment_LI_vector_datas放到self.state.vec_data_list的last_LI_index前面
            self.state.vec_data_list.insert(last_LI_index, supplment_LI_vector_datas)

        self.state.vec_data_list.append(new_list)
        
        return {
            "is_loop_end": True
        }
    
    # ========================== Call 语句 ==========================
    @v_args(meta=True)
    def b_procedures__procedure_def(self, meta, children: List) -> Dict[str, Any]:
        """根据索引获取到原始文本，然后当遇到Call的时候会获取文本并处理 Procedure 内容"""
        start = meta.start_pos;
        stop = meta.end_pos;
        proc_name = children[0].value;
        proc_content = (self.text_original[start:stop].strip()
            .strip(proc_name).strip().strip('{').strip('}'));
        self.state.procedures[proc_name] = proc_content;
        return {
            "type": "procedure_def",
            "children": children
        }

    def procedures_block(self, children: List) -> Dict[str, Any]:
        """处理 Procedures 块"""
        return {
            "type": "procedures_block",
            "children": children
        }
        
    def _handle_call(self, call_data: Dict[str, Any]) -> None:
        """处理 Call 指令"""
        proc_name = call_data.get("proc_name", "")
        
        # 检查 Procedure 是否存在
        if proc_name in self.state.procedures:
            proc_content = self.state.procedures[proc_name]
            try:
                # 解析 Procedure 内容
                proc_tree = self.state.multi_parser.parse(proc_content)
                # 触发回调
                self.handler.on_procedure_call(proc_name, proc_content, self.state.vector_address)
                # 递归处理（使用新的 Transformer 实例）
                transformer = STILParserTransformer(self.handler, "", self.state)
                transformer.transform(proc_tree)
                self.state.vector_count += transformer.state.vector_count
            except LarkError as e:
                self.handler.on_parse_error(f"Procedure '{proc_name}' 解析失败: {e}", "")
                self.handler.on_procedure_call(proc_name, "", self.state.vector_address)
                self.state.vector_address += 1
                if self.state.debug:
                    print(f"警告：Procedure '{proc_name}' 解析失败: {e}")
        else:
            self.handler.on_procedure_call(proc_name, "", self.state.vector_address)
            self.state.vector_address += 1
            if self.state.debug:
                print(f"警告：Procedure '{proc_name}' 未找到")

    def call_stmt(self, children: List) -> Dict[str, Any]:
        """处理 Call 语句"""
        tokens = [c.value for c in children if isinstance(c, Token)]
        proc_name = tokens[1] if len(tokens) > 1 else ""
        result = {
            "type": "call",
            "proc_name": proc_name
        }
        self._handle_call(result)
        return result
    
    # ========================== 其他微指令 ==========================
    def s_stmt(self, children: List) -> Dict[str, Any]:
        """处理 Stop 语句"""
        tokens = [c.value for c in children if isinstance(c, Token)]
        self.handler.on_micro_instruction("Stop", tokens[1] if len(tokens) > 1 else "", self.state.vector_address)
        self.state.vector_address += 1
        self.state.vector_count += 1
        return {}
    
    def g_stmt(self, children: List) -> Dict[str, Any]:
        """处理 Goto 语句"""
        tokens = [c.value for c in children if isinstance(c, Token)]
        self.handler.on_micro_instruction("Goto", tokens[1] if len(tokens) > 1 else "", self.state.vector_address)
        self.state.vector_address += 1
        self.state.vector_count += 1
        return {}
    
    def i_stmt(self, children: List) -> Dict[str, Any]:
        """处理 IddqTestPoint 语句"""
        tokens = [c.value for c in children if isinstance(c, Token)]
        self.handler.on_micro_instruction("IddqTestPoint", "", self.state.vector_address)
        self.state.vector_address += 1
        self.state.vector_count += 1
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

class ParserState:
    """解析器共享状态
    
    用于在 Transformer 和主解析器之间共享状态
    """
    
    def __init__(self):
        self.vector_count = 0
        self.vector_address = 0  # 向量地址（用于生成自动 Label 和输出）
        self.supplment_loop_label = 0 # 当JNI丢失LI的块的时候，用这个递减作为label
        self.supplment_loop_instr: Dict[int, str] = {}
        self.loop_deep = 0
        self.vec_data_list = []
        self.current_wft = ""
        self.curr_label = ""
        self.curr_instr = ""
        self.curr_param = ""
        self.procedures: Dict[str, str] = {}
        self.multi_parser: Optional[Lark] = None
        self.debug = False

    def reset(self) -> None:
        self.loop_deep = 0
        self.vec_data_list = []
        self.curr_label = ""
        self.curr_instr = ""
        self.curr_param = ""

    def handle_curr_instr(self) -> str:
        instr = self.curr_instr
        self.curr_instr = ""
        return instr

    def handle_curr_param(self) -> str:
        param = self.curr_param
        self.curr_param = ""
        return param

    def handle_curr_label(self) -> str:
        label = self.curr_label
        self.curr_label = ""
        return label

class PatternStreamParserTransformer:
    """STIL Pattern 流式解析器 - Transformer 版本
    
    使用 Lark Transformer 处理解析树，提供更声明式的编程方式。
    """
    
    def __init__(self, stil_file: str, event_handler: PatternEventHandler, 
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
    
    def _extract_procedures(self) -> None:
        """提取 STIL 文件中的 Procedures 块"""

        is_procedures = False
        buffer_lines = []
        statement_buffer = ""

        try:
            with open(self.stil_file, 'r', encoding='utf-8') as f:
                for line in f:
                    if line.strip().startswith('Pattern '):
                        f.close()
                        break
                    if line.strip().startswith('Procedures'):
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
            transformer = STILParserTransformer(self.handler, statement_buffer, self.state)
            transformer.transform(proc_tree)
                
        except Exception as e:
            self.handler.on_parse_error(str(e), "提取 Procedures 失败")
            if self.debug:
                print(f"提取 Procedures 失败: {e}")
    
    def stop(self) -> None:
        """请求停止解析"""
        self._stop_requested = True
    
    def parse_patterns(self) -> int:
        """流式解析 Pattern 块
        
        Returns:
            解析的向量总数
        """
        # 1. 提取 Procedures
        self._extract_procedures()
        
        # 2. 初始化状态
        self.state.vector_count = 0
        self.state.current_wft = ""
        
        # 3. 触发解析开始回调
        self.handler.on_parse_start()
        
        # 4. 流式解析 Pattern 并触发回调
        buffer_lines = []
        is_pattern = False
        transformer = STILParserTransformer(self.handler, "", self.state)
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
                            transformer.v_stmt([])
                            tree = self.multi_parser.parse(statement_buffer)
                            transformer.transform(tree)
                        except LarkError as e:
                            # 触发错误回调
                            self.handler.on_parse_error(str(e), statement_buffer)
                            if self.debug:
                                print(f"解析失败: {statement_buffer[:50]}...")
                        except Exception as e:
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

