"""向量字符映射器

将STIL中的向量字符转换成VCT格式的字符。
支持自由添加映射条目，找不到映射时保留原始字符。

映射规则格式: Z=.
"""

from typing import Dict, List, Optional
import json


class VectorCharMapper:
    """向量字符映射器类"""
    
    # 默认的STIL到VCT向量字符映射表
    DEFAULT_MAPPING = {
        "Z": ".",   # 高阻态
    }
    
    def __init__(self):
        """初始化映射器，使用默认映射表"""
        self.mapping: Dict[str, str] = self.DEFAULT_MAPPING.copy()
    
    def add_mapping(self, stil_char: str, vct_char: str) -> None:
        """添加一条映射规则
        
        Args:
            stil_char: STIL中的字符
            vct_char: 映射后的VCT字符
        """
        self.mapping[stil_char] = vct_char
    
    def remove_mapping(self, stil_char: str) -> bool:
        """移除一条映射规则
        
        Args:
            stil_char: 要移除的STIL字符
            
        Returns:
            是否成功移除
        """
        if stil_char in self.mapping:
            del self.mapping[stil_char]
            return True
        return False
    
    def map_char(self, stil_char: str) -> str:
        """映射单个字符
        
        Args:
            stil_char: STIL中的字符
            
        Returns:
            映射后的字符，找不到则返回原字符
        """
        return self.mapping.get(stil_char, stil_char)
    
    def map_vector(self, vector: str) -> str:
        """映射整个向量字符串
        
        Args:
            vector: STIL向量字符串
            
        Returns:
            映射后的VCT向量字符串
        """
        return "".join(self.map_char(c) for c in vector)
    
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
    
    def clear_mappings(self) -> None:
        """清空所有映射规则"""
        self.mapping.clear()
    
    def reset_to_default(self) -> None:
        """重置为默认映射表"""
        self.mapping = self.DEFAULT_MAPPING.copy()
    
    def parse_mapping_string(self, mapping_str: str) -> bool:
        """解析映射字符串（格式: A=B）
        
        Args:
            mapping_str: 映射字符串，如 "Z=."
            
        Returns:
            是否解析成功
        """
        if "=" not in mapping_str:
            return False
        
        parts = mapping_str.split("=", 1)
        if len(parts) != 2:
            return False
        
        stil_char = parts[0].strip()
        vct_char = parts[1].strip()
        
        if not stil_char:
            return False
        
        # vct_char 可以为空（表示删除该字符）
        self.mapping[stil_char] = vct_char
        return True
    
    def parse_mapping_lines(self, lines: str) -> int:
        """解析多行映射字符串
        
        Args:
            lines: 多行映射字符串，每行格式为 "A=B"
            
        Returns:
            成功解析的映射数量
        """
        count = 0
        for line in lines.strip().split("\n"):
            line = line.strip()
            if line and not line.startswith("#"):  # 忽略空行和注释
                if self.parse_mapping_string(line):
                    count += 1
        return count
    
    def to_mapping_string(self) -> str:
        """导出为映射字符串格式
        
        Returns:
            多行映射字符串
        """
        lines = []
        for stil_char, vct_char in sorted(self.mapping.items()):
            lines.append(f"{stil_char}={vct_char}")
        return "\n".join(lines)
    
    def export_to_json(self, filepath: str) -> bool:
        """导出映射到JSON文件
        
        Args:
            filepath: 文件路径
            
        Returns:
            是否成功
        """
        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(self.mapping, f, indent=2, ensure_ascii=False)
            return True
        except Exception:
            return False
    
    def import_from_json(self, filepath: str) -> bool:
        """从JSON文件导入映射
        
        Args:
            filepath: 文件路径
            
        Returns:
            是否成功
        """
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if isinstance(data, dict):
                self.mapping.update(data)
                return True
            return False
        except Exception:
            return False
    
    def __repr__(self) -> str:
        return f"VectorCharMapper(mappings={self.mapping})"


# 全局默认实例，方便直接使用
_default_mapper: Optional[VectorCharMapper] = None


def get_default_mapper() -> VectorCharMapper:
    """获取全局默认映射器实例"""
    global _default_mapper
    if _default_mapper is None:
        _default_mapper = VectorCharMapper()
    return _default_mapper


# 便捷函数
def map_char(stil_char: str) -> str:
    """使用默认映射器映射单个字符"""
    return get_default_mapper().map_char(stil_char)


def map_vector(vector: str) -> str:
    """使用默认映射器映射向量字符串"""
    return get_default_mapper().map_vector(vector)


# 测试代码
if __name__ == "__main__":
    mapper = VectorCharMapper()
    
    print("=== 向量字符映射测试 ===")
    print(f"映射器: {mapper}")
    print()
    
    # 测试单字符映射
    print("单字符映射测试:")
    test_chars = ["0", "1", "Z", "X", "L", "H"]
    for char in test_chars:
        result = mapper.map_char(char)
        print(f"  '{char}' -> '{result}'")
    
    print()
    
    # 测试向量映射
    print("向量字符串映射测试:")
    test_vectors = [
        "01ZX",
        "LLHHZZ",
        "0101ZXZX",
    ]
    for vec in test_vectors:
        result = mapper.map_vector(vec)
        print(f"  '{vec}' -> '{result}'")
    
    print()
    
    # 测试添加映射
    print("=== 添加自定义映射 ===")
    mapper.add_mapping("X", ".")
    mapper.add_mapping("L", "0")
    mapper.add_mapping("H", "1")
    print(f"添加: X=., L=0, H=1")
    print(f"当前映射: {mapper.to_mapping_string()}")
    
    print()
    
    # 再次测试向量映射
    print("添加映射后的向量转换:")
    for vec in test_vectors:
        result = mapper.map_vector(vec)
        print(f"  '{vec}' -> '{result}'")
    
    print()
    
    # 测试解析映射字符串
    print("=== 解析映射字符串 ===")
    mapper.reset_to_default()
    mapping_text = """
    Z=.
    X=.
    L=0
    H=1
    # 这是注释
    N=N
    """
    count = mapper.parse_mapping_lines(mapping_text)
    print(f"解析了 {count} 条映射规则")
    print(f"当前映射:\n{mapper.to_mapping_string()}")

