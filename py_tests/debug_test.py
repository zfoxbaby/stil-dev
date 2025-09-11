#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试debug=True是否工作
"""

import os
import sys
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from Semi_ATE.STIL.parsers.STILParser import STILParser

def test_debug_functionality():
    """测试debug功能"""
    
    stil_file = "tests/stil_files/pattern_block/syn_ok_pattern_block_1.stil"
    
    if not os.path.exists(stil_file):
        print(f"文件不存在: {stil_file}")
        return
    
    print("=" * 60)
    print("测试 debug=True 功能")
    print("=" * 60)
    
    # 创建解析器
    parser = STILParser(stil_file)
    
    print("\n1. 测试 parse_syntax(debug=True):")
    print("-" * 40)
    
    # 调用 parse_syntax with debug=True
    tree = parser.parse_syntax(debug=True)
    
    print(f"\n2. 解析结果:")
    print(f"   tree is None: {tree is None}")
    print(f"   parser.err_line: {parser.err_line}")
    print(f"   parser.err_col: {parser.err_col}")
    
    if tree is not None:
        print(f"   tree type: {type(tree)}")
        print(f"   tree data: {tree.data if hasattr(tree, 'data') else 'N/A'}")
    
    print("\n3. 手动打印 tree.pretty():")
    print("-" * 40)
    if tree is not None:
        print(tree.pretty())
    else:
        print("Tree is None, 无法打印")

if __name__ == "__main__":
    test_debug_functionality() 