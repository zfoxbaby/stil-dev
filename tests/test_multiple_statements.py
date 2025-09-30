# -*- coding: utf-8 -*-
import os
import sys
from lark import Lark, LarkError

def test_parsing_approaches():
    """测试不同的解析方法"""
    
    grammar_base = os.path.join(os.path.dirname(__file__), "..", "Semi_ATE", "STIL", "parsers", "grammars")
    
    # 方案1：使用单个pattern_statement解析器
    print("=== 方案1：单个pattern_statement解析器 ===")
    try:
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
        
        full_grammar = pattern_grammar + ignore_whitespace
        
        single_parser = Lark(
            full_grammar,
            start="pattern_statement",
            parser="lalr",
            import_paths=[grammar_base]
        )
        
        # 测试单独的语句
        test_single = ["stop:", "V {all = PPLLPL;}"]
        for stmt in test_single:
            try:
                tree = single_parser.parse(stmt)
                print(f"✓ 解析成功: '{stmt}' -> {tree.data}")
            except Exception as e:
                print(f"✗ 解析失败: '{stmt}' -> {e}")
        
        # 测试组合语句（预期失败）
        combined = "stop: V {all = PPLLPL;}"
        try:
            tree = single_parser.parse(combined)
            print(f"✓ 组合解析成功: '{combined}' -> {tree.data}")
        except Exception as e:
            print(f"✗ 组合解析失败（预期）: '{combined}' -> {e}")
    
    except Exception as e:
        print(f"方案1初始化失败: {e}")
    
    # 方案2：使用多个pattern_statement解析器
    print("\n=== 方案2：多个pattern_statement解析器 ===")
    try:
        # 创建能解析多个pattern_statement的语法
        multi_grammar = """
        start: pattern_statement+
        """ + pattern_grammar + ignore_whitespace
        
        multi_parser = Lark(
            multi_grammar,
            start="start",
            parser="lalr",
            import_paths=[grammar_base]
        )
        
        # 测试组合语句
        test_combinations = [
            "stop: V {all = PPLLPL;}",
            "start: V {all = LLLLLL;}",
            "test_label: W wft1;",
            "Loop1: Call proc1;",
            "_private: Stop;",
            "MAIN_LOOP: Loop 5 { V { all = PPLL; } }",
            "end_section: Ann {* End of test *}",
        ]
        
        for combined in test_combinations:
            try:
                tree = multi_parser.parse(combined)
                print(f"✓ 多语句解析成功: '{combined}'")
                print(f"  包含 {len(tree.children)} 个语句")
                for i, child in enumerate(tree.children):
                    print(f"    语句{i+1}: {child.data}")
            except Exception as e:
                print(f"✗ 多语句解析失败: '{combined}' -> {e}")
                 
        print()
         
        # 测试更复杂的组合（多个标签+语句）
        complex_combination = """test1: V {all = PPLL;}
test2: W wft1;
test3: Stop;"""
        try:
            tree = multi_parser.parse(complex_combination)
            print(f"✓ 复杂多语句解析成功")
            print(f"  包含 {len(tree.children)} 个语句")
            for i, child in enumerate(tree.children):
                print(f"    语句{i+1}: {child.data}")
        except Exception as e:
            print(f"✗ 复杂多语句解析失败: {e}")
    
    except Exception as e:
        print(f"方案2初始化失败: {e}")
    
    # 方案3：使用完整的Pattern块解析器
    print("\n=== 方案3：完整Pattern块解析器 ===")
    try:
        b_pattern_file = os.path.join(grammar_base, "b_pattern.lark")
        with open(b_pattern_file, 'r') as f:
            pattern_block_grammar = f.read()
        
        pattern_block_grammar_full = pattern_block_grammar + ignore_whitespace
        
        pattern_block_parser = Lark(
            pattern_block_grammar_full,
            start="pattern_block",
            parser="lalr",
            import_paths=[grammar_base]
        )
        
        # 测试完整的Pattern块
        full_pattern = """Pattern test_pattern {
    stop: V {all = PPLLPL;}
}"""
        try:
            tree = pattern_block_parser.parse(full_pattern)
            print(f"✓ Pattern块解析成功")
            print(f"  Pattern名称: {tree.children[0]}")
        except Exception as e:
            print(f"✗ Pattern块解析失败: {e}")
    
    except Exception as e:
        print(f"方案3初始化失败: {e}")

if __name__ == "__main__":
    test_parsing_approaches() 