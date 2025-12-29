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
from lark import Lark, Tree, Token, Transformer, LarkError

# 复用原有的 PatternEventHandler
from PatternParser import PatternEventHandler


class PatternTransformer(Transformer):
    """Pattern 语句转换器
    
    使用 Lark Transformer 自动遍历和处理解析树。
    每个方法对应一个语法规则。
    """
    
    def __init__(self, handler: PatternEventHandler, parser_state):
        """初始化 Transformer
        
        Args:
            handler: 事件处理器
            parser_state: 解析器状态（共享状态对象）
        """
        super().__init__()
        self.handler = handler
        self.state = parser_state
    
    # ========================== Token 处理 ==========================
    
    def LABEL(self, token: Token) -> Dict[str, Any]:
        """处理 LABEL token"""
        label_name = token.value.strip('"').strip("'").rstrip(':')
        return {"type": "label", "value": label_name}
    
    # ========================== 语句处理 ==========================
    
    def pattern_statement(self, children: List) -> Dict[str, Any]:
        """处理 pattern_statement
        
        这是顶层规则，会收集所有子元素的结果
        """
        result = {
            "type": "statement",
            "label": None,
            "instruction": None,
            "vectors": [],
            "waveform": None,
            "children": []
        }
        
        for child in children:
            if isinstance(child, dict):
                if child.get("type") == "label":
                    result["label"] = child.get("value")
                elif child.get("type") == "waveform":
                    result["waveform"] = child.get("value")
                elif child.get("type") == "vector":
                    result["vectors"].append(child)
                elif child.get("type") == "v_stmt":
                    # V 语句返回的数据
                    result["vectors"].extend(child.get("vectors", []))
                    if child.get("instruction"):
                        result["instruction"] = child.get("instruction")
                elif child.get("type") == "loop":
                    result["children"].append(child)
                elif child.get("type") == "call":
                    result["children"].append(child)
                elif child.get("type") == "micro_instr":
                    result["instruction"] = child
                elif child.get("type") == "statement":
                    result["children"].append(child)
            elif isinstance(child, list):
                # 可能是 vec_block 直接返回的列表
                for item in child:
                    if isinstance(item, dict) and item.get("type") == "vector":
                        result["vectors"].append(item)
        
        # 执行回调
        self._execute_callbacks(result)
        
        return result
    
    def _execute_callbacks(self, result: Dict[str, Any]) -> None:
        """执行回调
        
        Args:
            result: 解析结果字典
        """
        # 处理 label
        if result.get("label"):
            self.handler.on_label(result["label"])
        
        # 处理 waveform 切换
        if result.get("waveform"):
            self.handler.on_waveform_change(result["waveform"])
        
        # 处理向量数据
        if result.get("vectors"):
            vec_data_list = []
            for vec in result["vectors"]:
                vec_data_list.append((vec["signal"], vec["data"]))
            
            instr = result.get("instruction", {})
            self.handler.on_vector(
                vec_data_list,
                instr.get("name", ""),
                instr.get("param", "")
            )
            self.state.vector_count += 1
        
        # 递归处理子语句（Loop、Call 等）
        for child in result.get("children", []):
            if child.get("type") == "loop":
                self._handle_loop(child)
            elif child.get("type") == "call":
                self._handle_call(child)
            elif child.get("type") == "micro_instr":
                self._handle_micro_instr(child)
    
    def _handle_loop(self, loop_data: Dict[str, Any]) -> None:
        """处理 Loop 指令"""
        loop_count = loop_data.get("count", "1")
        loop_label = loop_data.get("label", "")
        vectors = loop_data.get("vectors", [])
        
        # 触发 Loop 开始
        self.handler.on_loop_start(loop_count, loop_label)
        
        # 触发每个向量
        total = len(vectors)
        for index, vec_data in enumerate(vectors):
            vec_label = vec_data.get("label", "")
            vec_list = vec_data.get("vec_data", [])
            self.handler.on_loop_vector(vec_list, index, total, vec_label)
            self.state.vector_count += 1
        
        # 触发 Loop 结束
        self.handler.on_loop_end(loop_count)
    
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
                self.handler.on_procedure_call(proc_name, proc_content)
                # 递归处理（使用新的 Transformer 实例）
                transformer = PatternTransformer(self.handler, self.state)
                transformer.transform(proc_tree)
            except LarkError as e:
                self.handler.on_procedure_call(proc_name, "")
                if self.state.debug:
                    print(f"警告：Procedure '{proc_name}' 解析失败: {e}")
        else:
            self.handler.on_procedure_call(proc_name, "")
            if self.state.debug:
                print(f"警告：Procedure '{proc_name}' 未找到")
    
    def _handle_micro_instr(self, instr_data: Dict[str, Any]) -> None:
        """处理其他微指令"""
        self.handler.on_micro_instruction(
            instr_data.get("name", ""),
            instr_data.get("param", "")
        )
    
    # ========================== W 语句（波形表切换）==========================
    
    def w_stmt(self, children: List) -> Dict[str, Any]:
        """处理 W 语句（波形表切换）"""
        # children 包含所有 token
        tokens = [c for c in children if isinstance(c, Token)]
        if len(tokens) >= 2:
            wft_name = tokens[1].value
            self.state.current_wft = wft_name
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
        
        vec_block 包含多个 vec_data_block，需要把它们收集起来传递给上层
        """
        vectors = []
        for child in children:
            if isinstance(child, dict) and child.get("type") == "vector":
                vectors.append(child)
        return vectors
    
    def v_stmt(self, children: List) -> Dict[str, Any]:
        """处理 V 语句
        
        V 语句可能包含微指令和 vec_block
        """
        vectors = []
        micro_instr = {"name": "", "param": ""}
        
        for child in children:
            # 收集微指令 token
            if isinstance(child, Token):
                if child.value not in ["V", "{", "}", ";"]:
                    if not micro_instr["name"]:
                        micro_instr["name"] = child.value
                    else:
                        micro_instr["param"] = child.value
            # 收集向量数据（vec_block 返回的列表）
            elif isinstance(child, list):
                vectors.extend(child)
            # 收集向量数据（单个 dict）
            elif isinstance(child, dict) and child.get("type") == "vector":
                vectors.append(child)
        
        return {
            "type": "v_stmt",
            "vectors": vectors,
            "instruction": micro_instr if micro_instr["name"] else None
        }
    
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
    
    def loop_stmt(self, children: List) -> Dict[str, Any]:
        """处理 Loop 语句
        
        需要手动收集 Loop 内的向量数据
        """
        # 获取 Loop 计数
        tokens = [c.value for c in children if isinstance(c, Token)]
        loop_count = tokens[1] if len(tokens) > 1 else "1"
        
        # 收集 Loop 内的向量
        vectors = self._collect_loop_vectors(children)
        
        return {
            "type": "loop",
            "count": loop_count,
            "label": "",  # Loop label 在外层 pattern_statement 处理
            "vectors": vectors
        }
    
    def _collect_loop_vectors(self, children: List) -> List[Dict[str, Any]]:
        """收集 Loop 内的所有向量"""
        vectors = []
        current_label = ""
        
        def collect_from_node(node):
            nonlocal current_label
            
            if isinstance(node, dict):
                if node.get("type") == "label":
                    current_label = node.get("value", "")
                elif node.get("type") == "vector":
                    vectors.append({
                        "label": current_label,
                        "vec_data": [(node["signal"], node["data"])]
                    })
                    current_label = ""  # 清空，只用一次
                elif node.get("type") == "v_stmt":
                    # V 语句包含多个向量
                    vec_list = []
                    for vec in node.get("vectors", []):
                        vec_list.append((vec["signal"], vec["data"]))
                    if vec_list:
                        vectors.append({
                            "label": current_label,
                            "vec_data": vec_list
                        })
                        current_label = ""
                elif node.get("type") == "statement":
                    # 递归处理嵌套语句
                    for child in node.get("vectors", []):
                        collect_from_node(child)
                    for child in node.get("children", []):
                        collect_from_node(child)
            elif isinstance(node, list):
                for item in node:
                    collect_from_node(item)
        
        for child in children:
            collect_from_node(child)
        
        return vectors
    
    # ========================== Call 语句 ==========================
    
    def call_stmt(self, children: List) -> Dict[str, Any]:
        """处理 Call 语句"""
        tokens = [c.value for c in children if isinstance(c, Token)]
        proc_name = tokens[1] if len(tokens) > 1 else ""
        
        return {
            "type": "call",
            "proc_name": proc_name
        }
    
    # ========================== 其他微指令 ==========================
    
    def s_stmt(self, children: List) -> Dict[str, Any]:
        """处理 Stop 语句"""
        tokens = [c.value for c in children if isinstance(c, Token)]
        return {
            "type": "micro_instr",
            "name": "Stop",
            "param": tokens[1] if len(tokens) > 1 else ""
        }
    
    def g_stmt(self, children: List) -> Dict[str, Any]:
        """处理 Goto 语句"""
        tokens = [c.value for c in children if isinstance(c, Token)]
        return {
            "type": "micro_instr",
            "name": "Goto",
            "param": tokens[1] if len(tokens) > 1 else ""
        }
    
    def i_stmt(self, children: List) -> Dict[str, Any]:
        """处理 IddqTestPoint 语句"""
        tokens = [c.value for c in children if isinstance(c, Token)]
        return {
            "type": "micro_instr",
            "name": "IddqTestPoint",
            "param": tokens[1] if len(tokens) > 1 else ""
        }
    
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
        self.current_wft = ""
        self.procedures: Dict[str, str] = {}
        self.multi_parser: Optional[Lark] = None
        self.debug = False


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
                import_paths=[grammar_base]
            )
            if self.debug:
                print("Pattern 语句解析器初始化成功 (Transformer 版本)")
        except Exception as e:
            if self.debug:
                print(f"Pattern 语句解析器初始化失败: {e}")
            raise
    
    def _extract_procedures(self) -> None:
        """提取 STIL 文件中的 Procedures 块"""
        try:
            with open(self.stil_file, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            
            in_procedures = False
            in_procedure_def = False
            current_proc_name = ""
            current_proc_body = []
            brace_count = 0
            proc_brace_count = 0
            
            for line in lines:
                stripped = line.strip()
                
                # 检测 Procedures 块开始
                if 'Procedures' in line and '{' in line:
                    in_procedures = True
                    brace_count = line.count('{') - line.count('}')
                    continue
                
                if in_procedures:
                    # 更新花括号计数
                    brace_count += line.count('{') - line.count('}')
                    
                    # Procedures 块结束
                    if brace_count == 0:
                        # 保存最后一个 Procedure
                        if in_procedure_def and current_proc_name and current_proc_body:
                            proc_content = "\n".join(current_proc_body)
                            self.state.procedures[current_proc_name] = proc_content
                            if self.debug:
                                print(f"找到 Procedure: {current_proc_name}")
                        in_procedures = False
                        continue
                    
                    # 检测 Procedure 定义开始
                    if not in_procedure_def:
                        # 匹配: procedure_name {
                        if '{' in line and not stripped.startswith('//'):
                            # 提取 procedure 名称
                            proc_name_match = re.match(r'\s*(\w+)\s*\{', line)
                            if proc_name_match:
                                current_proc_name = proc_name_match.group(1)
                                in_procedure_def = True
                                proc_brace_count = 1
                                current_proc_body = []
                                # 如果 { 后面还有内容，加入 body
                                after_brace = line.split('{', 1)[1].strip()
                                if after_brace:
                                    current_proc_body.append(after_brace)
                                continue
                    else:
                        # 在 Procedure 定义内部
                        proc_brace_count += line.count('{') - line.count('}')
                        
                        if proc_brace_count == 0:
                            # Procedure 定义结束，保存前去掉最后的 }
                            line_without_close = line.rsplit('}', 1)[0].strip()
                            if line_without_close:
                                current_proc_body.append(line_without_close)
                            
                            # 保存 Procedure
                            proc_content = "\n".join(current_proc_body)
                            self.state.procedures[current_proc_name] = proc_content
                            if self.debug:
                                print(f"找到 Procedure: {current_proc_name}")
                            
                            # 重置状态
                            in_procedure_def = False
                            current_proc_name = ""
                            current_proc_body = []
                        else:
                            # 添加行到 body
                            current_proc_body.append(line.rstrip())
            
            if self.debug:
                print(f"提取了 {len(self.state.procedures)} 个 Procedures")
                
        except Exception as e:
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
        
        try:
            with open(self.stil_file, 'r', encoding='utf-8') as f:
                for line in f:
                    if self._stop_requested:
                        break
                    
                    # 检测 Pattern 块开始
                    if line.strip().startswith('Pattern ') and '{' in line:
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
                            transformer = PatternTransformer(self.handler, self.state)
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
        except Exception as e:
            self.handler.on_parse_error(str(e), "")
            if self.debug:
                print(f"文件读取错误: {e}")
        
        # 5. 触发解析完成回调
        self.handler.on_parse_complete(self.state.vector_count)
        
        return self.state.vector_count

