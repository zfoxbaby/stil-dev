# -*- coding: utf-8 -*-
import os
import sys
import time
from lark import Lark, Tree, Token, LarkError
from STILToGasc import STILToGasc 
from STILToGascStream import STILToGascStream

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
    #debug = False
    debug = True
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
        print("Pattern语句解析器初始化成功")
        # 测试单个语句，pattern_statement只能解析单个语句，不是整个Pattern块
        test_statements = [
            'Ann {* Pattern:0 Vector:0 TesterCycle:0 *}',
            'W wt1;',
            'V { _bidi_= \\r98 X ; _pi_=NNN0NN1N0000NNNNN; _po_=XXXXXX; }',
            'Stop;',
            'Call proc1;',
            'Loop 5 { V { all = PPLL; } }',
            'stop: V {all = PPLLPL;} ',
        ]
        
        for i, stmt in enumerate(test_statements):
            try:
                if debug:
                    print(f"测试语句 {i+1}: {stmt}")
                tree = multi_parser.parse(stmt)
                if debug:
                    print(f"  ✓ 解析成功: {tree.data}")
            except Exception as e:
                if debug:
                    print(f"  ✗ 解析失败: {e}")

    except Exception as e:
        print(f"Pattern语句解析器初始化失败: {e}")

    stil_file = "C:\\Users\\admin\\Desktop\\1\\stil-dev\\tests\\stil_files\\pattern_block\\syn_ok_pattern_block_1.stil"
    target_file_path = "C:\\Users\\admin\\Desktop\\1\\result\\syn_ok_pattern_block_1.gasc"
    stil_to_gasc = STILToGasc(stil_file, target_file_path, True, progress_callback)
    #stil_to_gasc.convert(progress_callback)
    start = time.time()

    header_buffer = "";
    buffer_lines = []
    #with open(stil_file, 'r', encoding='utf-8') as f:
    #    lines = f.read().splitlines()
    #for line in lines:
    isPattern = False
    with open(stil_file, 'r', encoding='utf-8') as f:
        #read every line in the file
        for line in f:
            if line.strip().startswith('Pattern ') and '{' in line:
                isPattern = True;
                if debug:
                    print(header_buffer)
                parser = STILParser(stil_file, propagate_positions=True, debug=debug)
                tree = parser.parse_content(header_buffer)
                if debug:
                    print(tree.pretty())
                break
            if not isPattern:
                header_buffer += line
                continue
        for line in f:
            statement_buffer = "".join(buffer_lines).strip()
            try:
                # if not contains '{' and end with ';' or statement_buffer equal '}'
                if ('{' not in statement_buffer and (statement_buffer.endswith(';'))
                     or statement_buffer.endswith('}')):
                    tree = multi_parser.parse(statement_buffer)
                    stil_to_gasc.process_streaming(tree, 121)
                    buffer_lines.clear()
                    buffer_lines.append(line)
                    if debug:
                        print(f"解析成功: {statement_buffer}")
                        stil_to_gasc.flush()
                    continue
                # else append line to buffer_lines
                buffer_lines.append(line)
            except LarkError: 
                buffer_lines.append(line)
                if debug:
                    print(f"解析失败: {line}")
            except Exception as e:
                buffer_lines.append(line)
                if debug:
                    print(f"其他错误: {e}")
    stil_to_gasc.close()

    end = time.time()
    duration = end - start;
    #if debug:
    print("结束时间戳:", duration);
    if tree == None:
        assert False


def test_block_2():
    stil_file = "C:\\Users\\admin\\Desktop\\1\\result\\syn_ok_pattern_block_1.stil"
    target_file_path = "C:\\Users\\admin\\Desktop\\1\\result\\syn_ok_pattern_block_1.gasc"
    parser = STILParser(stil_file, propagate_positions=True, debug=False)
    tree = parser.parse_syntax(debug=False, preprocess_include=not False)
    print(tree.pretty())


def test_block_3():
    stil_file = "C:\\Users\\admin\\Desktop\\1\\result\\syn_ok_pattern_block_1.stil"
    target_file_path = "C:\\Users\\admin\\Desktop\\1\\result\\syn_ok_pattern_block_1.gasc"

    parser = STILToGascStream(stil_file, target_file_path, progress_callback, debug=True)

    # 测试单个语句，pattern_statement只能解析单个语句，不是整个Pattern块
    test_statements = [
        #'Ann {* Pattern:0 Vector:0 TesterCycle:0 *}',
        #'W wt1;',
        #'V { _bidi_= \\r98 X ; _pi_=NNN0NN1N0000NNNNN; _po_=XXXXXX; }',
        #'Stop;',
        #'Call proc1;',
        #'Loop 5 { V { all = PPLL; } }',
        'stop: V {all = PPLLPL;} ',
    ]
            
    multi_parser = parser.get_multi_parser()
    for i, stmt in enumerate(test_statements):
        try:
            print(f"测试语句 {i+1}: {stmt}")
            tree = multi_parser.parse(stmt)
            for child in tree.children:
                for c in child.children:
                    if (isinstance(c, Token)):
                        print(c.type)
                
        except Exception as e: 
            print(f"  ✗ 解析失败: {e}")
    start = time.time()
    parser.convert()
    end = time.time()
    duration = end - start;
    print("结束时间戳:", duration);

if __name__ == "__main__":
    test_block_3()
