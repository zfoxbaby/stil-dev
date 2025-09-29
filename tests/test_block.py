# -*- coding: utf-8 -*-
import os
import sys
import time
from lark import Lark, Tree, Token, LarkError
from datetime import datetime
from gpt_tests.STILToGasc import STILToGasc 

try:
    from Semi_ATE.STIL.parsers.STILParser import STILParser
except:
    cwd = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, cwd)
    from Semi_ATE.STIL.parsers.STILParser import STILParser

def get_stil_file(file_name):
    folder = os.path.dirname(__file__)
    return os.path.join(str(folder), "stil_files", file_name)

def progress_callback(message):
            """Progress callback function with real-time vector counting"""
            print(f"{message}")

def test_block_1():

    grammar_base = os.path.join(os.path.dirname(__file__), "..", "Semi_ATE", "STIL", "parsers", "grammars")
    
    # 构建完整的语法
    pattern_statements_file = os.path.join(grammar_base, "pattern_statements.lark")
    base_file = os.path.join(grammar_base, "base.lark")
    
    try:
        # 读取pattern_statements语法（它会自动通过import_paths导入base.lark）
        with open(pattern_statements_file, 'r') as f:
            pattern_grammar = f.read()
        
        # 添加空格和注释忽略规则（让解析器忽略空格和注释）
        ignore_whitespace = """
        %import common.WS
        %ignore WS
        %import common.CPP_COMMENT  
        %ignore CPP_COMMENT
        %import common.NEWLINE
        %ignore NEWLINE
        """
        
        full_grammar = pattern_grammar + ignore_whitespace
        
        pattern_parser = Lark(
            full_grammar,
            start="pattern_statement",
            parser="lalr",
            import_paths=[grammar_base]
        )
        print("Pattern语句解析器初始化成功")
        # 测试单个语句，pattern_statement只能解析单个语句，不是整个Pattern块
        test_statements = [
            'Ann {* Pattern:0 Vector:0 TesterCycle:0 *}',
            'W wt1;',
            'V { _bidi_= \\r98 X ; _pi_=NNN0NN1N0000NNNNN; _po_=XXXXXX; }',
            'Stop;',
            'Call proc1;',
            'Loop 5 { V { all = PPLL; } }',
        ]
        
        for i, stmt in enumerate(test_statements):
            try:
                print(f"测试语句 {i+1}: {stmt}")
                tree = pattern_parser.parse(stmt)
                print(f"  ✓ 解析成功: {tree.data}")
            except Exception as e:
                print(f"  ✗ 解析失败: {e}")

    except Exception as e:
        print(f"Pattern语句解析器初始化失败: {e}")
        pattern_parser = None
    stil_file = "C:\\Users\\admin\\Desktop\\1\\result\\utc_010_bypass_big.stil"
    target_file_path = "C:\\Users\\admin\\Desktop\\1\\result\\utc_010_bypass.gasc"
    stil_to_gasc = STILToGasc(stil_file, target_file_path, True, progress_callback)
    #stil_to_gasc.convert(progress_callback)
    start = time.time()

    statement_buffer = ""
    with open(stil_file, 'r', encoding='utf-8') as f:
        #read every line in the file
        for line in f:
            if line.strip().startswith('Pattern ') and '{' in line:
                statement_buffer = ""
                continue
            try:
                tree = pattern_parser.parse(statement_buffer)
                print(f"解析成功: {statement_buffer}")
                stil_to_gasc.process_streaming(tree, 121)
                stil_to_gasc.flush()
                statement_buffer = line
            except LarkError:
                print(f"解析失败: {line}")
                statement_buffer += line
            except Exception as e:
                print(f"其他错误: {e}")
                statement_buffer += line
    stil_to_gasc.close()

    end = time.time()
    duration = end - start;
    print("结束时间戳:", duration);
    if tree == None:
        assert False




if __name__ == "__main__":
    test_block_1()
