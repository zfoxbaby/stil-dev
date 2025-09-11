#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
STIL树分析器 - 获取和分析parser.parse_syntax()返回的树结构

这个工具帮助你：
1. 获取 self.tree 的完整内容
2. 分析树的结构和数据
3. 生成你需要的格式文件
"""

import os
import sys
import json
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

try:
    from Semi_ATE.STIL.parsers.STILParser import STILParser
except ImportError as e:
    print(f"导入错误: {e}")
    print("请确保在项目根目录运行此脚本")
    sys.exit(1)


class STILTreeAnalyzer:
    """STIL树分析器"""
    
    def __init__(self, stil_file_path):
        """
        初始化分析器
        
        Args:
            stil_file_path: STIL文件路径
        """
        self.stil_file = stil_file_path
        self.parser = None
        self.tree = None
        
    def parse_file(self):
        """解析STIL文件，获取树结构"""
        try:
            print(f"解析文件: {self.stil_file}")
            
            # 创建解析器
            self.parser = STILParser(self.stil_file)
            
            # 执行语法解析 - 这就是 test_syn_ok_pattern_block_1 中的关键步骤
            self.tree = self.parser.parse_syntax()
            
            if self.tree is None:
                print("解析失败!")
                print(f"错误行: {self.parser.err_line}")
                print(f"错误列: {self.parser.err_col}")
                print(f"错误信息: {self.parser.err_msg}")
                return False
            
            print("解析成功!")
            return True
            
        except Exception as e:
            print(f"解析过程中发生错误: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def print_tree_pretty(self):
        """打印树的美化结构 - 和test方法中print(stil_tree.pretty())一样"""
        if self.tree is None:
            print("树为空，请先解析文件")
            return
            
        print("=" * 80)
        print("STIL解析树结构 (tree.pretty())")
        print("=" * 80)
        print(self.tree.pretty())
    
    def analyze_tree_structure(self):
        """分析树的结构信息"""
        if self.tree is None:
            print("树为空，请先解析文件")
            return {}
            
        analysis = {
            'root_data': str(self.tree.data) if hasattr(self.tree, 'data') else 'N/A',
            'root_type': str(type(self.tree)),
            'children_count': len(self.tree.children) if hasattr(self.tree, 'children') else 0,
            'children_info': []
        }
        
        if hasattr(self.tree, 'children'):
            for i, child in enumerate(self.tree.children):
                child_info = {
                    'index': i,
                    'type': str(type(child)),
                    'data': str(child.data) if hasattr(child, 'data') else str(child)[:100],
                    'children_count': len(child.children) if hasattr(child, 'children') else 0
                }
                analysis['children_info'].append(child_info)
        
        return analysis
    
    def extract_tree_data_recursive(self, node, max_depth=10, current_depth=0):
        """递归提取树的所有数据"""
        if current_depth > max_depth:
            return "MAX_DEPTH_REACHED"
            
        if hasattr(node, 'data') and hasattr(node, 'children'):
            # 这是一个Tree节点
            result = {
                'type': 'Tree',
                'data': str(node.data),
                'children': []
            }
            
            for child in node.children:
                child_data = self.extract_tree_data_recursive(child, max_depth, current_depth + 1)
                result['children'].append(child_data)
                
            return result
            
        elif hasattr(node, 'value'):
            # 这是一个Token节点
            return {
                'type': 'Token',
                'value': str(node.value),
                'token_type': str(node.type) if hasattr(node, 'type') else 'Unknown'
            }
        else:
            # 其他类型的节点
            return {
                'type': str(type(node)),
                'value': str(node)
            }
    
    def get_tree_as_dict(self, max_depth=10):
        """将整个树转换为字典格式"""
        if self.tree is None:
            return {}
            
        return {
            'file_path': self.stil_file,
            'tree_data': self.extract_tree_data_recursive(self.tree, max_depth)
        }
    
    def save_tree_to_json(self, output_file, max_depth=10):
        """保存树结构为JSON文件"""
        tree_dict = self.get_tree_as_dict(max_depth)
        
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(tree_dict, f, indent=2, ensure_ascii=False)
        
        print(f"树结构已保存到: {output_file}")
    
    def find_specific_blocks(self):
        """查找特定的块（Signal、SignalGroup、Timing、Pattern）"""
        if self.tree is None:
            return {}
            
        blocks = {
            'signals_blocks': [],
            'signal_groups_blocks': [],
            'timing_blocks': [],
            'pattern_blocks': [],
            'pattern_burst_blocks': []
        }
        
        def search_blocks(node):
            if hasattr(node, 'data'):
                data_str = str(node.data)
                if 'signals_block' in data_str:
                    blocks['signals_blocks'].append(node)
                elif 'signal_groups_block' in data_str:
                    blocks['signal_groups_blocks'].append(node)
                elif 'timing_block' in data_str:
                    blocks['timing_blocks'].append(node)
                elif 'pattern_block' in data_str:
                    blocks['pattern_blocks'].append(node)
                elif 'pattern_burst_block' in data_str:
                    blocks['pattern_burst_blocks'].append(node)
            
            if hasattr(node, 'children'):
                for child in node.children:
                    search_blocks(child)
        
        search_blocks(self.tree)
        
        # 统计信息
        summary = {block_type: len(block_list) for block_type, block_list in blocks.items()}
        
        return blocks, summary
    
    def generate_analysis_report(self, output_file):
        """生成完整的分析报告"""
        if self.tree is None:
            print("请先解析文件")
            return
            
        # 获取各种分析数据
        structure_analysis = self.analyze_tree_structure()
        blocks, block_summary = self.find_specific_blocks()
        
        report = {
            'file_info': {
                'path': self.stil_file,
                'exists': os.path.exists(self.stil_file)
            },
            'tree_structure': structure_analysis,
            'block_summary': block_summary,
            'tree_pretty_print': self.tree.pretty(),
            'full_tree_data': self.get_tree_as_dict(max_depth=15)
        }
        
        # 保存报告
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        
        print(f"完整分析报告已保存到: {output_file}")
        
        # 同时打印摘要
        print("\n" + "=" * 80)
        print("分析摘要")
        print("=" * 80)
        print(f"文件: {self.stil_file}")
        print(f"根节点: {structure_analysis['root_data']}")
        print(f"顶层子节点数: {structure_analysis['children_count']}")
        print("\n发现的块:")
        for block_type, count in block_summary.items():
            if count > 0:
                print(f"  {block_type}: {count}个")


def main():
    """主函数 - 演示如何使用树分析器"""
    
    # 测试文件列表
    test_files = [
        "tests/stil_files/pattern_block/syn_ok_pattern_block_1.stil",
        "tests/stil_files/signals_block/sem_ok_signals_block_1.stil",
    ]
    
    for test_file in test_files:
        if not os.path.exists(test_file):
            print(f"跳过不存在的文件: {test_file}")
            continue
            
        print(f"\n{'='*100}")
        print(f"分析文件: {test_file}")
        print(f"{'='*100}")
        
        # 创建分析器
        analyzer = STILTreeAnalyzer(test_file)
        
        # 解析文件
        if analyzer.parse_file():
            
            # 1. 打印树结构（和test方法一样）
            analyzer.print_tree_pretty()
            
            # 2. 生成完整分析报告
            base_name = os.path.basename(test_file).replace('.stil', '')
            report_file = f"py_tests/tree_analysis_{base_name}.json"
            analyzer.generate_analysis_report(report_file)
            
            # 3. 单独保存树数据
            tree_file = f"py_tests/tree_data_{base_name}.json"
            analyzer.save_tree_to_json(tree_file, max_depth=20)
            
            print(f"\n生成的文件:")
            print(f"  - 分析报告: {report_file}")
            print(f"  - 树数据: {tree_file}")
        
        else:
            print("文件解析失败，跳过分析")


if __name__ == "__main__":
    main() 