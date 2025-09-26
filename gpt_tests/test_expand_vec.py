#!/usr/bin/env python3
"""
测试 expand_vec_data 函数的各种情况
"""

from STILToGasc import STILToGasc

def test_expand_vec_data():
    """测试向量数据展开功能"""
    converter = STILToGasc("dummy", "dummy")
    
    # 测试用例
    test_cases = [
        # 简单情况：\r98 X
        ("\\r3 X", "XXX"),
        ("\\r5 H", "HHHHH"),
        
        # 复杂情况：XLLL \r98 X HHH \r4 H LL
        ("XLLL \\r3 X HHH", "XLLLXXXHHH"),
        ("XLLL \\r2 X HHH \\r3 H LL", "XLLLXXHHHHHHHLL"),
        
        # 边界情况
        ("\\r1 X", "X"),
        ("ABC", "ABC"),  # 没有重复指令
        ("", ""),  # 空字符串
        
        # 复杂混合
        ("A \\r2 B C \\r3 D E", "ABBCDDDDE"),
        ("\\r2 X Y \\r3 Z", "XXYZZZ"),
    ]
    
    print("测试 expand_vec_data 函数:")
    print("=" * 50)
    
    for i, (input_data, expected) in enumerate(test_cases, 1):
        result = converter.expand_vec_data(input_data)
        status = "✓" if result == expected else "✗"
        
        print(f"测试 {i}: {status}")
        print(f"  输入: '{input_data}'")
        print(f"  期望: '{expected}'")
        print(f"  实际: '{result}'")
        
        if result != expected:
            print(f"  错误: 结果不匹配!")
        print()

if __name__ == "__main__":
    test_expand_vec_data() 