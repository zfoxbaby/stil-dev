#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
STIL到SPM格式转换器 - 新版本

按照指定逻辑直接从tree节点提取数据：
1. 从 b_signals__signals_list 获取信号定义
2. 从 b_pattern__pattern_statements__w_stmt 获取 timing (wft)
3. 从 b_pattern__pattern_statements__*_stmt 获取微指令
4. 从 b_pattern__pattern_statements__vec_data_block 获取 Vector 原始数据
"""

import os
import sys
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

try:
    from Semi_ATE.STIL.parsers.STILParser import STILParser
except ImportError as e:
    print(f"导入错误: {e}")
    sys.exit(1)


class STILToSPMConverterNew:
    """STIL到SPM格式转换器 - 新版本"""
    
    def __init__(self, stil_file_path):
        self.stil_file = stil_file_path
        self.parser = None
        self.tree = None
        
        # 解析结果存储
        self.signals = []  # 信号列表（按定义顺序）
        self.timing_name = ""  # 当前使用的timing名称
        self.pattern_instructions = []  # 模式指令序列
        
    def parse_stil_file(self):
        """解析STIL文件"""
        try:
            print(f"解析STIL文件: {self.stil_file}")
            
            self.parser = STILParser(self.stil_file)
            self.tree = self.parser.parse_syntax()
            
            if self.tree is None:
                print("语法解析失败!")
                return False
                
            print("STIL文件解析成功!")
            return True
            
        except Exception as e:
            print(f"解析错误: {e}")
            return False
    
    def extract_signals_from_tree(self):
        """从tree中提取信号定义 - 直接查找 b_signals__signals_list 节点"""
        def find_signals_list_nodes(node):
            signals_found = []
            
            if hasattr(node, 'data') and str(node.data) == 'b_signals__signals_list':
                # 找到 b_signals__signals_list 节点，提取信号名
                signal_name = self._extract_signal_name_from_list_node(node)
                if signal_name:
                    signals_found.append(signal_name)
                    print(f"在 b_signals__signals_list 中找到信号: {signal_name}")
            
            # 递归查找子节点
            if hasattr(node, 'children'):
                for child in node.children:
                    signals_found.extend(find_signals_list_nodes(child))
                    
            return signals_found
        
        all_signals = find_signals_list_nodes(self.tree)
        
        # 保持顺序并去重
        for signal in all_signals:
            if signal not in self.signals:
                self.signals.append(signal)
        
        print(f"提取到信号（按顺序）: {self.signals}")
    
    def _extract_signal_name_from_list_node(self, signals_list_node):
        """从 b_signals__signals_list 节点提取信号名 - 直接取第一个元素"""
        if hasattr(signals_list_node, 'children'):
            for child in signals_list_node.children:
                if hasattr(child, 'value'):
                    value = str(child.value).strip('"')
                    if value != ';':  # 只跳过分号
                        return value
        return None
    
    def extract_pattern_data_from_tree(self):
        """从tree中提取Pattern数据 - 直接查找特定节点"""
        def find_pattern_nodes(node):
            instructions_found = []
            
            if hasattr(node, 'data'):
                node_data = str(node.data)
                
                # 查找 W 语句 - b_pattern__pattern_statements__w_stmt
                if node_data == 'b_pattern__pattern_statements__w_stmt':
                    timing = self._extract_timing_from_w_node(node)
                    if timing:
                        self.timing_name = timing
                        print(f"在 w_stmt 中找到 timing: {timing}")
                
                # 查找各种指令语句
                elif node_data.startswith('b_pattern__pattern_statements__') and node_data.endswith('_stmt'):
                    instruction = self._extract_instruction_from_stmt_node(node)
                    if instruction:
                        instructions_found.append(instruction)
                        print(f"在 {node_data} 中找到指令: {instruction}")
            
            # 递归查找子节点
            if hasattr(node, 'children'):
                for child in node.children:
                    instructions_found.extend(find_pattern_nodes(child))
                    
            return instructions_found
        
        all_instructions = find_pattern_nodes(self.tree)
        self.pattern_instructions = all_instructions
        
        print(f"提取到Pattern指令: {len(self.pattern_instructions)}条")
        
        # 打印前几个指令用于调试
        for i, inst in enumerate(self.pattern_instructions[:3]):
            print(f"  指令{i+1}: {inst}")
    
    def _extract_timing_from_w_node(self, w_node):
        """从 w_stmt 节点提取 timing 名称"""
        if hasattr(w_node, 'children'):
            for child in w_node.children:
                if hasattr(child, 'value'):
                    value = str(child.value)
                    if value != 'W':  # 跳过 'W' 关键字
                        return value
        return ""
    
    def _extract_instruction_from_stmt_node(self, stmt_node):
        """从指令语句节点提取指令信息 - 用第一个元素作为指令名，第二个作为参数"""
        node_data = str(stmt_node.data)
        
        # 从节点中提取指令类型和参数
        instruction_type = ""
        instruction_params = ""
        
        if hasattr(stmt_node, 'children'):
            values = []
            for child in stmt_node.children:
                if hasattr(child, 'value'):
                    value = str(child.value)
                    if value not in ['{', '}', ';']:
                        values.append(value)
            
            # 第一个元素作为指令名，第二个作为参数
            if len(values) >= 1:
                first = values[0].upper()
                if first == 'C':
                    instruction_type = "START"
                elif first == 'F':
                    instruction_type = "FORCE"
                elif first == 'V':
                    instruction_type = ""  # V指令不显示类型
                elif first in ['CALL', 'MACRO', 'LOOP', 'MATCHLOOP', 'GOTO', 'SCANCHAIN']:
                    instruction_type = first
                elif first == 'BREAKPOINT':
                    instruction_type = "BREAKPOINT"
                elif first == 'IDDQTESTPOINT':
                    instruction_type = "IDDQ"
                elif first == 'STOP':
                    instruction_type = "STOP"
                
                # 第二个元素作为参数
                if len(values) >= 2:
                    instruction_params = values[1]
        
        # 查找向量数据
        vector_data = self._find_vector_data_in_node(stmt_node)
        
        return {
            'type': instruction_type,
            'params': instruction_params,
            'vector_data': vector_data,
            'timing': self.timing_name,
            'node_type': node_data
        }
    

    
    def _find_vector_data_in_node(self, node):
        """在节点中查找 vec_data_block 并提取向量数据"""
        def find_vec_data_block(n):
            if hasattr(n, 'data') and 'vec_data_block' in str(n.data):
                # 找到 vec_data_block，提取其中的数据
                return self._extract_vector_from_data_block(n)
            
            if hasattr(n, 'children'):
                for child in n.children:
                    result = find_vec_data_block(child)
                    if result:
                        return result
                        
            return None
        
        return find_vec_data_block(node)
    
    def _extract_vector_from_data_block(self, data_block):
        """从 vec_data_block 提取向量数据 - 不写死信号组"""
        signal_group = None
        vector_data = None
        
        if hasattr(data_block, 'children'):
            values = []
            for child in data_block.children:
                if hasattr(child, 'value'):
                    value = str(child.value).strip()
                    if value not in ['=', '{', '}', ';']:
                        values.append(value)
                        
                # 递归查找子节点
                elif hasattr(child, 'children'):
                    nested_result = self._extract_vector_from_data_block(child)
                    if nested_result:
                        return nested_result
            
            # 第一个是信号组，第二个是向量数据
            if len(values) >= 1:
                signal_group = values[0]
            if len(values) >= 2:
                # 检查是否为向量数据
                potential_vector = values[1]
                if len(potential_vector) > 1 and all(c in 'PLHXTDUZ01' for c in potential_vector.upper()):
                    vector_data = potential_vector
                    print(f"在 vec_data_block 中找到向量数据: {vector_data} (信号组: {signal_group})")
        
        return {
            'signal_group': signal_group,
            'data': vector_data
        } if vector_data else None
    
    def generate_spm_file(self, output_file):
        """生成SPM格式文件"""
        try:
            with open(output_file, 'w', encoding='utf-8') as f:
                # 写入HEADER
                f.write("HEADER\n")
                f.write("     ")
                
                # 写入信号列表
                line_length = 5
                for i, signal in enumerate(self.signals):
                    signal_text = signal + ","
                    if line_length + len(signal_text) > 75 and i > 0:
                        f.write("\n     ")
                        line_length = 5
                    f.write(signal_text)
                    line_length += len(signal_text)
                
                # 替换最后一个逗号为分号
                f.seek(f.tell() - 1)
                f.write(";\n\n")
                
                # 写入SPM_PATTERN
                f.write("SPM_PATTERN (SCAN) {\n")
                
                for i, instruction in enumerate(self.pattern_instructions):
                    inst_type = instruction['type']
                    inst_params = instruction['params']
                    vector_info = instruction['vector_data']
                    timing = instruction['timing']
                    
                    # 处理向量数据 - 保持原始格式
                    if vector_info and vector_info.get('data'):
                        vector_str = vector_info['data']
                    else:
                        vector_str = 'X' * len(self.signals)
                    
                    line = f"       *{vector_str}*"
                    
                    # 添加指令信息
                    if inst_type:
                        line += f" {inst_type}"
                        if inst_params:
                            line += f" {inst_params}"
                        if timing:
                            line += f";{timing}"
                    
                    line += ";\n"
                    f.write(line)
                    
                    # 在START/FORCE后添加间隔行，STOP后不添加
                    if inst_type in ['START', 'FORCE'] and i < len(self.pattern_instructions) - 1:
                        next_inst = self.pattern_instructions[i + 1]
                        if next_inst['type'] != 'STOP':
                            f.write(f"       *{'X' * len(self.signals)}*;\n")
                
                f.write("}\n")
            
            print(f"SPM文件已生成: {output_file}")
            
        except Exception as e:
            print(f"生成SPM文件失败: {e}")
    
    def convert(self, output_file):
        """执行完整的转换过程"""
        print("=" * 60)
        print("STIL到SPM转换器 - 新版本")
        print("=" * 60)
        
        # 1. 解析STIL文件
        if not self.parse_stil_file():
            return False
        
        # 2. 从tree中提取信号
        self.extract_signals_from_tree()
        
        # 3. 从tree中提取模式数据
        self.extract_pattern_data_from_tree()
        
        # 4. 生成SPM文件
        self.generate_spm_file(output_file)
        
        return True


def test_converter_new():
    """测试新版转换器"""
    
    test_files = [
        "tests/stil_files/pattern_block/syn_ok_pattern_block_1.stil",
    ]
    
    for stil_file in test_files:
        if not os.path.exists(stil_file):
            print(f"跳过不存在的文件: {stil_file}")
            continue
            
        print(f"\n{'='*80}")
        print(f"转换文件: {stil_file}")
        print(f"{'='*80}")
        
        converter = STILToSPMConverterNew(stil_file)
        
        base_name = os.path.basename(stil_file).replace('.stil', '')
        output_file = f"py_tests/spm_output_new_{base_name}.spm"
        
        if converter.convert(output_file):
            print(f"转换成功! 输出文件: {output_file}")
            
            print(f"\n生成的SPM文件内容:")
            print("-" * 40)
            try:
                with open(output_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                    print(content)
            except Exception as e:
                print(f"读取输出文件失败: {e}")
        else:
            print("转换失败!")


if __name__ == "__main__":
    test_converter_new() 