"""微指令映射器

将STIL中的标准微指令转换成VCT格式能识别的指令。
支持自由添加映射条目，找不到映射时保留原始指令。
"""

from typing import Dict, Optional, Tuple


class MicroInstructionMapper:
    """微指令映射器类"""
    
    # 默认的STIL到VCT微指令映射表
    DEFAULT_MAPPING = {
        "Stop": "HALT",
        "Goto": "JUMP",
        "Loop": "LI",  # 如果Loop里面只有一个V那么就替换成RPT
        "Call": "CALL",
        "Return": "RET",
        "IddqTestPoint": "IDDQ",
        "IDDQTestPoint": "IDDQ",
    }
    
    # 无指令时的缺省值
    DEFAULT_INSTRUCTION = "ADV"
    
    def __init__(self):
        """初始化映射器，使用默认映射表"""
        self.mapping: Dict[str, str] = self.DEFAULT_MAPPING.copy()
        self.default_instruction = self.DEFAULT_INSTRUCTION
    
    def set_default_instruction(self, instr: str) -> None:
        """设置缺省指令（当STIL中没有指令时使用）
        
        Args:
            instr: 缺省指令名
        """
        self.default_instruction = instr
    
    def map(self, stil_instr: str, param: str = "") -> Tuple[str, str]:
        """映射STIL指令到VCT指令
        
        Args:
            stil_instr: STIL中的指令名（如 "Stop", "Loop", "V" 等）
            param: 指令参数（如 Loop 的循环次数）
            
        Returns:
            (vct_instr, param) 元组
            - 如果找到映射，返回映射后的指令
            - 如果没找到映射，返回原始指令
            - 如果是空或"V"，返回缺省指令(ADV)
        """
        # 如果没有指令或只是单纯的V，使用缺省值
        if not stil_instr or stil_instr.strip() == "" or stil_instr == "V":
            return (self.default_instruction, "")
        
        # 查找映射
        if stil_instr in self.mapping:
            return (self.mapping[stil_instr], param)
        
        # 没找到映射，保留原始指令
        return (stil_instr, param)
    
    def format_vct_instruction(self, stil_instr: str, param: str = "") -> str:
        """格式化为VCT指令字符串（固定14字符宽度）
        
        Args:
            stil_instr: STIL中的指令名
            param: 指令参数
            
        Returns:
            格式化后的VCT指令字符串（14字符宽度）
        """
        vct_instr, vct_param = self.map(stil_instr, param)
        
        if vct_param:
            # 有参数的指令，如 "RPT       50"
            instr_str = f"{vct_instr} {vct_param}"
        else:
            # 无参数的指令，如 "ADV" 或 "HALT"
            instr_str = vct_instr
        
        # 填充到14字符宽度
        return instr_str.ljust(14)
    
    def get_all_mappings(self) -> Dict[str, str]:
        """获取所有映射规则
        
        Returns:
            映射字典的副本
        """
        return self.mapping.copy()
    
    def load_mappings(self, mappings: Dict[str, str]) -> None:
        """批量加载映射规则
        
        Args:
            mappings: 映射字典
        """
        self.mapping.update(mappings)
    
    def reset_to_default(self) -> None:
        """重置为默认映射表"""
        self.mapping = self.DEFAULT_MAPPING.copy()
        self.default_instruction = self.DEFAULT_INSTRUCTION
    
    def __repr__(self) -> str:
        return f"MicroInstructionMapper(mappings={self.mapping}, default='{self.default_instruction}')"


# 全局默认实例，方便直接使用
_default_mapper = None

def get_default_mapper() -> MicroInstructionMapper:
    """获取全局默认映射器实例"""
    global _default_mapper
    if _default_mapper is None:
        _default_mapper = MicroInstructionMapper()
    return _default_mapper


# 便捷函数
def map_instruction(stil_instr: str, param: str = "") -> Tuple[str, str]:
    """使用默认映射器映射指令"""
    return get_default_mapper().map(stil_instr, param)


def format_instruction(stil_instr: str, param: str = "") -> str:
    """使用默认映射器格式化指令"""
    return get_default_mapper().format_vct_instruction(stil_instr, param)


# 测试代码
if __name__ == "__main__":
    mapper = MicroInstructionMapper()
    
    print("=== 微指令映射测试 ===")
    print(f"映射器: {mapper}")
    print()
    
    # 测试映射
    test_cases = [
        ("Stop", ""),           # 应该映射为 HALT
        ("Jump", "label1"),     # 应该映射为 JUMP label1
        ("Loop", "50"),         # 应该映射为 RPT 50
        ("Call", "sub1"),       # 应该映射为 CALL sub1
        ("V", ""),              # 无指令，应该为 ADV
        ("", ""),               # 无指令，应该为 ADV
        ("Unknown", ""),        # 未知指令，保留原样
    ]
    
    print("测试用例:")
    for stil_instr, param in test_cases:
        result = mapper.map(stil_instr, param)
        formatted = mapper.format_vct_instruction(stil_instr, param)
        print(f"  STIL: '{stil_instr}' + '{param}' -> VCT: {result} -> 格式化: '{formatted}'")
    
    print()
    print("=== 添加自定义映射 ===")
    mapper.add_mapping("Shift", "SHFT")
    print(f"添加: Shift -> SHFT")
    result = mapper.map("Shift", "8")
    print(f"测试: Shift + '8' -> {result}")

