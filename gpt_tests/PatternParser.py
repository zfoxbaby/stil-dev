"""STIL Pattern 流式解析器模块

提供 Pattern 解析的通用功能，支持多种输出格式（VCT、GASC等）。
采用事件驱动的回调机制，将解析逻辑与格式生成逻辑解耦。

核心类：
- PatternEventHandler: 事件处理接口（基类）
- PatternStreamParser: Pattern 流式解析器
"""

from __future__ import annotations

import os
import re
import sys
from typing import List, Dict, Tuple, Optional
from lark import Lark, Tree, Token, LarkError
from STILParserUtils import PatternEventHandler

class PatternStreamParser:
    """STIL Pattern 流式解析器
    
    负责解析 STIL 文件中的 Pattern 块，并通过回调接口通知事件处理器。
    采用流式解析，适合处理大文件。
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
        
        # Procedures 存储
        self.procedures: Dict[str, str] = {}  # {procedure_name: procedure_content}
        
        # 解析状态
        self.current_wft: str = ""           # 当前波形表名
        self.label_value: str = ""           # 当前待输出的 LABEL
        self.vector_count: int = 0           # 向量计数
        
        # 解析器初始化
        self.multi_parser: Optional[Lark] = None
        self._init_parser()
        
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
                print("Pattern 语句解析器初始化成功")
        except Exception as e:
            error_msg = f"Pattern 语句解析器初始化失败: {e}"
            self.handler.on_parse_error(error_msg, "")
            if self.debug:
                print(error_msg)
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
                            self.procedures[current_proc_name] = proc_content
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
                            self.procedures[current_proc_name] = proc_content
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
                print(f"提取了 {len(self.procedures)} 个 Procedures")
                
        except Exception as e:
            error_msg = f"提取 Procedures 失败: {e}"
            self.handler.on_parse_error(error_msg, "")
            if self.debug:
                print(error_msg)
    
    def stop(self) -> None:
        """请求停止解析"""
        self._stop_requested = True
    
    def _expand_vec_data(self, data: str) -> str:
        """展开向量数据中的重复指令，如 \\r98 X
        
        Args:
            data: 原始向量数据字符串
            
        Returns:
            展开后的向量数据字符串
        """
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
    
    def _collect_vec_data_from_node(self, node, pending_label: str = "") -> List[Tuple[str, List[Tuple[str, str]]]]:
        """从节点中收集所有 V 块的 vec_data，同时收集 LABEL
        
        Args:
            node: 解析树节点
            pending_label: 待关联的 LABEL（来自前一个 pattern_statement）
            
        Returns:
            列表，每个元素是 (label, vec_data_list)，label 为空字符串表示无 label
        """
        all_vec_data: List[Tuple[str, List[Tuple[str, str]]]] = []
        
        if not isinstance(node, Tree):
            return all_vec_data
        
        # 遍历子节点，收集 LABEL 和 V 块
        for child in node.children:
            # 情况1: 直接是 LABEL Token
            if isinstance(child, Token) and child.type == "LABEL":
                pending_label = child.value.strip('"').strip("'").rstrip(':')
                continue
            
            if isinstance(child, Tree):
                # 情况2: pattern_statement 只包含 LABEL（检查其子节点）
                if child.data.endswith("pattern_statement"):
                    # 检查这个 pattern_statement 是否只包含 LABEL
                    label_tokens = [c for c in child.children if isinstance(c, Token) and c.type == "LABEL"]
                    if label_tokens and len(child.children) == 1:
                        # 这个 pattern_statement 只包含 LABEL
                        pending_label = label_tokens[0].value.strip('"').strip("'").rstrip(':')
                        continue
                
                # 检查当前子节点是否有 vec_block
                has_vec = any(isinstance(ch, Tree) and ch.data.endswith("vec_block") 
                              for ch in child.children)
                
                if has_vec:
                    # 检查这个节点内部是否有 LABEL（如 llabel1: V { } 在同一个 pattern_statement 中）
                    for ch in child.children:
                        if isinstance(ch, Token) and ch.type == "LABEL":
                            pending_label = ch.value.strip('"').strip("'").rstrip(':')
                    
                    vec_data_list: List[Tuple[str, str]] = []
                    for vb in child.iter_subtrees():
                        if isinstance(vb, Tree) and vb.data.endswith("vec_data_block"):
                            vec_tokens = [t.value for t in vb.scan_values(lambda c: isinstance(c, Token))]
                            if vec_tokens:
                                pat_key = vec_tokens[0].strip()
                                wfc_str = self._expand_vec_data(vec_tokens[-1].strip())
                                vec_data_list.append((pat_key, wfc_str))
                    if vec_data_list:
                        all_vec_data.append((pending_label, vec_data_list))
                        pending_label = ""  # 清空，只用一次
                
                # 递归处理嵌套的 pattern_statement（传递 pending_label）
                elif child.data.endswith("pattern_statement"):
                    sub_results = self._collect_vec_data_from_node(child, pending_label)
                    if sub_results:
                        all_vec_data.extend(sub_results)
                        pending_label = ""  # 已被使用
                elif not child.data.endswith("vec_block"):
                    sub_results = self._collect_vec_data_from_node(child, pending_label)
                    if sub_results:
                        all_vec_data.extend(sub_results)
                        pending_label = ""  # 已被使用
        
        return all_vec_data
    
    def _process_loop_block(self, node, loop_count: str) -> None:
        """处理 Loop 块
        
        Args:
            node: Loop 节点（包含嵌套的 pattern_statement）
            loop_count: 循环次数
        """
        # 1. 收集 Loop 内的所有 V 块（包含 label 信息）
        all_vec_data = self._collect_vec_data_from_node(node)
        
        if len(all_vec_data) == 0:
            return
        
        # 2. 触发 Loop 开始回调
        loop_label = self.label_value if self.label_value else ""
        self.handler.on_loop_start(loop_count, loop_label)
        self.label_value = ""  # 清空
        
        # 3. 触发每个向量的回调
        total = len(all_vec_data)
        for index, (vec_label, vec_data_list) in enumerate(all_vec_data):
            self.handler.on_loop_vector(vec_data_list, index, total, vec_label)
            self.vector_count += 1
        
        # 4. 触发 Loop 结束回调
        self.handler.on_loop_end(loop_count)
    
    def _process_pattern_node(self, node, micro_tokens: List[str]) -> None:
        """处理 Pattern 节点，触发相应回调
        
        Args:
            node: 解析树节点
            micro_tokens: 当前微指令 token 列表
        """
        # 处理 LABEL Token
        if isinstance(node, Token) and node.type == "LABEL":
            self.label_value = node.value.strip().rstrip(':').strip('"').strip("'")
            return
        
        if not isinstance(node, Tree):
            return
        
        data = node.data
        
        if data.endswith("pattern_statement"):
            for child in node.children:
                self._process_pattern_node(child, micro_tokens)
            return
        
        # 跳过注释、开闭块
        if (data.endswith("annotation") 
            or data.endswith("open_pattern_block")
            or data.endswith("close_pattern_block")):
            return
        
        # 处理波形表切换 W wft_name
        if data.endswith("w_stmt"):
            tokens = [t.value for t in node.children if isinstance(t, Token)]
            if len(tokens) >= 2:
                self.current_wft = tokens[1]
                self.handler.on_waveform_change(self.current_wft)
            return
        
        # 获取微指令
        micro_tokens_temp = [c.value for c in node.children if isinstance(c, Token)][:2]
        micro = " ".join(micro_tokens_temp)
        if micro != "V":
            micro_tokens = micro_tokens_temp
        
        # 检查是否是 Loop 指令
        if micro_tokens and (micro_tokens[0] == "Loop" or micro_tokens[0] == "MatchLoop"):
            loop_count = micro_tokens[1] if len(micro_tokens) > 1 else "1"
            self._process_loop_block(node, loop_count)
            return
        
        # 检查是否有 vec_block
        has_vec = any(isinstance(ch, Tree) and ch.data.endswith("vec_block")
                      for ch in node.children)
        
        if has_vec:
            # 提取每个 vec_data_block 的 (pat_key, wfc) 对
            vec_data_list: List[Tuple[str, str]] = []
            
            # 获取微指令
            instr = micro_tokens[0] if micro_tokens else ""
            param = micro_tokens[1] if len(micro_tokens) > 1 else ""

            for vb in node.iter_subtrees():
                if isinstance(vb, Tree) and vb.data.endswith("vec_data_block"):
                    vec_tokens = [t.value for t in vb.scan_values(lambda c: isinstance(c, Token))]
                    if vec_tokens:
                        # 第一个 token 是 pat_header 的 key
                        pat_key = vec_tokens[0].strip()
                        # 最后一个 token 是 WFC 数据
                        wfc_str = self._expand_vec_data(vec_tokens[-1].strip())
                        vec_data_list.append((pat_key, wfc_str, instr, param))
            
            # 如果有 LABEL，先触发 label 回调
            if self.label_value:
                self.handler.on_label(self.label_value)
                self.label_value = ""
            
            # 触发向量回调
            self.handler.on_vector(vec_data_list, instr, param, self.label_value)
            self.vector_count += 1
            return
        
        # 处理 Call 指令 - 展开 Procedure
        if data.endswith("call_stmt"):
            # 获取微指令
            instr = micro_tokens[0] if micro_tokens else ""
            param = micro_tokens[1] if len(micro_tokens) > 1 else ""  # Procedure 名称
            
            # 如果有 LABEL，先触发 label 回调
            if self.label_value:
                self.handler.on_label(self.label_value)
                self.label_value = ""
            
            # 检查 Procedure 是否存在
            if param in self.procedures:
                # 展开 Procedure 内容
                proc_content = self.procedures[param]
                try:
                    # 解析 Procedure 内容
                    proc_tree = self.multi_parser.parse(proc_content)
                    # 触发 Call 回调（带 Procedure 内容）
                    self.handler.on_procedure_call(param, proc_content)
                    # 递归处理 Procedure 内容
                    self._process_pattern_node(proc_tree, [])
                except LarkError as e:
                    # 解析失败，触发 Call 回调（不带内容）
                    error_msg = f"警告：Procedure '{param}' 解析失败: {e}"
                    self.handler.on_parse_error(error_msg, proc_content[:100] if proc_content else "")
                    self.handler.on_procedure_call(param, "")
                    if self.debug:
                        print(error_msg)
            else:
                # Procedure 不存在，触发 Call 回调（不带内容）
                warning_msg = f"警告：Procedure '{param}' 未找到"
                self.handler.on_parse_error(warning_msg, "")
                self.handler.on_procedure_call(param, "")
                if self.debug:
                    print(warning_msg)
            return
        
        # 处理其他微指令（没有 vec_block 的语句，如 Stop、Goto 等）
        micro_only_stmts = ("s_stmt", "g_stmt", "i_stmt", "uk_stmt")
        if any(data.endswith(stmt) for stmt in micro_only_stmts):
            # 获取微指令
            instr = micro_tokens[0] if micro_tokens else ""
            param = micro_tokens[1] if len(micro_tokens) > 1 else ""
            
            # 如果有 LABEL，先触发 label 回调
            if self.label_value:
                self.handler.on_label(self.label_value)
                self.label_value = ""
            
            self.vector_count += 1
            # 触发微指令回调
            self.handler.on_micro_instruction(instr, param)
            return
        
        # 处理嵌套的 pattern_statement
        nested = [ch for ch in node.children 
                  if isinstance(ch, Tree) and ch.data.endswith("pattern_statement")]
        if nested:
            for child in nested:
                self._process_pattern_node(child, micro_tokens)
    
    def parse_patterns(self) -> int:
        """流式解析 Pattern 块
        
        Returns:
            解析的向量总数
        """
        # 1. 提取 Procedures
        self._extract_procedures()
        
        # 2. 初始化状态
        self.vector_count = 0
        self.current_wft = ""
        self.label_value = ""
        
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
                            tree = self.multi_parser.parse(statement_buffer)
                            self._process_pattern_node(tree, [])
                        except LarkError as e:
                            # 触发错误回调
                            error_msg = f"Lark 解析失败: {str(e)}"
                            self.handler.on_parse_error(error_msg, statement_buffer[:200] if statement_buffer else "")
                            if self.debug:
                                print(f"解析失败: {statement_buffer[:50]}...")
                        except Exception as e:
                            error_msg = f"解析过程发生错误: {type(e).__name__}: {str(e)}"
                            self.handler.on_parse_error(error_msg, statement_buffer[:200] if statement_buffer else "")
                            if self.debug:
                                print(f"其他错误: {e}")
                        
                        buffer_lines.clear()
        except Exception as e:
            error_msg = f"文件读取错误: {type(e).__name__}: {str(e)}"
            self.handler.on_parse_error(error_msg, "")
            if self.debug:
                print(error_msg)
                import traceback
                traceback.print_exc()
        
        # 5. 触发解析完成回调
        self.handler.on_parse_complete(self.vector_count)
        
        return self.vector_count

