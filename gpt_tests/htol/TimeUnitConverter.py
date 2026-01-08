"""时间单位转换工具

支持 ps/ns/us/ms/s 之间的相互转换。
"""

from typing import Tuple, Optional
import re


class TimeUnitConverter:
    """时间单位转换器"""
    
    # 单位到皮秒(ps)的转换因子
    UNIT_TO_PS = {
        "ps": 1,
        "pS": 1,
        "ns": 1000,
        "nS": 1000,
        "us": 1000000,
        "uS": 1000000,
        "ms": 1000000000,
        "mS": 1000000000,
        "s": 1000000000000,
        "S": 1000000000000,
    }
    
    # 默认输出单位
    DEFAULT_OUTPUT_UNIT = "ns"
    
    def __init__(self, default_output_unit: str = "ns"):
        """初始化转换器
        
        Args:
            default_output_unit: 默认输出单位，默认为 ns
        """
        self.default_output_unit = default_output_unit
    
    def parse_time_string(self, time_str: str) -> Tuple[float, str]:
        """解析带单位的时间字符串
        
        Args:
            time_str: 时间字符串，如 "100000ps", "100ns", "1.5us"
            
        Returns:
            (数值, 单位) 元组
            
        Raises:
            ValueError: 无法解析的时间字符串
        """
        if not time_str:
            return (0.0, "ns")
        
        time_str = time_str.strip()
        # 如果包含/符号，要根据/切分出来两个数字，然后前后相除，
        # 正则匹配：数字（可带小数,支持科学计数法）+ 单位
        match = re.match(r"^([+-]?\d*\.?\d+([eE][+-]?\d+)?)\s*(ps|ns|us|ms|s|pS|nS|uS|mS|S)?$", time_str, re.IGNORECASE)
        
        if not match:
            raise ValueError(f"无法解析时间字符串: {time_str}")
        
        value = float(match.group(1))
        unit = match.group(2).lower() if match.group(2) else "ns"
        return (value, unit)

        # # 写一个正则匹配 1/数字+单位MHz|KHz|Hz|mHz|uHz|nHz|pHz|fHz
        # match = re.match(r"^1/\d*\.?\d+([MHz|KHz|Hz|mHz|uHz|nHz|pHz|fHz])?$", time_str, re.IGNORECASE)
        # if match:
        #     value = 1 / float(match.group(1))
        #     unit = match.group(2).lower() if match.group(2) else "ns"
        #     return (value, unit)
        # 还要支持 15nS/3=5nS
    
    def to_ps(self, value: float, unit: str) -> float:
        """将任意单位转换为皮秒(ps)"""
        unit = unit.lower()
        if unit not in self.UNIT_TO_PS:
            raise ValueError(f"不支持的单位: {unit}")
        return value * self.UNIT_TO_PS[unit]
    
    def from_ps(self, ps_value: float, target_unit: str) -> float:
        """将皮秒转换为目标单位"""
        target_unit = target_unit.lower()
        if target_unit not in self.UNIT_TO_PS:
            raise ValueError(f"不支持的单位: {target_unit}")
        return ps_value / self.UNIT_TO_PS[target_unit]
    
    def convert(self, value: float, from_unit: str, to_unit: str) -> float:
        """单位转换"""
        ps_value = self.to_ps(value, from_unit)
        return self.from_ps(ps_value, to_unit)
    
    def convert_string(self, time_str: str, to_unit: Optional[str] = None) -> float:
        """解析并转换时间字符串"""
        if to_unit is None:
            to_unit = self.default_output_unit
        value, unit = self.parse_time_string(time_str)
        return self.convert(value, unit, to_unit)
    
    def convert_string_to_int(self, time_str: str, to_unit: Optional[str] = None) -> int:
        """解析并转换时间字符串为整数"""
        return round(self.convert_string(time_str, to_unit))


# 全局默认实例
_default_converter: Optional[TimeUnitConverter] = None


def get_default_converter() -> TimeUnitConverter:
    """获取全局默认转换器实例"""
    global _default_converter
    if _default_converter is None:
        _default_converter = TimeUnitConverter()
    return _default_converter


def convert_to_ns(time_str: str) -> float:
    """将时间字符串转换为纳秒"""
    return get_default_converter().convert_string(time_str, "ns")


def convert_to_ns_int(time_str: str) -> int:
    """将时间字符串转换为纳秒（整数）"""
    return get_default_converter().convert_string_to_int(time_str, "ns")

