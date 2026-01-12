from dataclasses import dataclass, field
from typing import List
from typing import Optional, Callable
from itertools import groupby
from STILEventHandler import STILEventHandler

@dataclass
class TimingData:
    """Timing Data
    
    存储波形定义信息，包括：
    - 波形表名称、周期、信号名、WFC
    - 最多4组时间/边沿对 (t1/e1 到 t4/e4)
    - 边沿类型和Vector转换信息
    """

    wfcs_strobe = ["L", "H", "X", "T", "V", "l", "h", "x", "t", "v"]
    wfcs_clock = ["D", "U", "N", "Z", "P"]
    # 典型波形
    wfcs_mappint = {
        "D": ["0", "NORMAL"],
        "U": ["1", "NORMAL"],

        "UD": ["0", "DNRZ"],
        "DU": ["1", "DNRZ"],
        "UDU": ["N", ""],
        "DUD": ["P", ""],

        "N": ["0", ""],
        "P": ["Q", ""],

        "Z": ["X", ""],
        "": ["X", ""],

        "L": ["L", "C"],
        "H": ["H", "C"],
        
        "X": ["X", "C"],
        "T": ["T", "C"],
        "V": ["V", "C"],
        "l": ["l", "CC"],
        "h": ["h", "C"],
        "t": ["t", "C"],
        "v": ["v", "C"],
    }

    parent: 'TimingData' = None
    wft: str = ""          # 波形表名称
    period: str = ""       # 周期
    signal: str = ""       # 信号名
    wfc: str = ""          # 波形字符 (WaveForm Character)
    t1: str = ""           # 时间1
    e1: str = ""           # 边沿1
    t2: str = ""           # 时间2
    e2: str = ""           # 边沿2
    t3: str = ""           # 时间3
    e3: str = ""           # 边沿3
    t4: str = ""           # 时间4
    e4: str = ""           # 边沿4
    twas: List = field(default_factory=list)  # 子TimingData列表
    
    # ========== 新增属性 ==========
    is_strobe: int = -1       # 是否是比较沿（STROBE=0），否则是驱动沿（CLOCK=1），InOut类型信号认为是STROBE（STROBE=2）
    edge_format: str = ""         # 边沿格式: NRZ/DNRZ/RZ/RO
    vector_replacement: str = ""  # Vector生成时的替换字符: P(DUD)/N(UDU)/空(不替换)
    
       
    def compute_timing_properties(self, strobe_wfcs: set = None, signal_type: str = "", 
        handler: STILEventHandler = None) -> None:
        """计算并设置 Timing 属性
        
        根据信号类型、WFC 和边沿模式，自动设置：
        - is_strobe: 是否是比较沿
        - edge_format: 边沿格式 (NRZ/DNRZ/RZ/RO)
        - vector_replacement: Vector替换字符 (P/N/空)
        
        Args:
            strobe_wfcs: STROBE类型的WFC字符集合，默认 {'L', 'H', 'l', 'h'}（向后兼容）
            signal_type: 信号类型 (In/Out/InOut/Supply/Pseudo)，优先使用此参数判断
        """
        if self.parent is not None:
            return
        
        self._wfc_replacement(signal_type, handler)

       
    def _wfc_replacement(self, signal_type: str = "", handler: STILEventHandler = None) -> None:
        # 计算边沿格式
        edge_count = self.get_edge_count()

        if edge_count == 0:
            return
        
        # 如果是父节点，此时获取所有子节点，如果所有子节点中同时包含UDU子集和DUD子集，因为可能出现4个沿，
        # 就包含UDU的TimingData的vector_replacement变成N，包含DUD的TimingData的vector_replacement变成P，
        # 此时不需要edge_format。
        # 如果所有子节点中同时包含DDD和DUD，就把edge_format变成RZ, vector_replacement不需要填写，
        # 如果所有子节点中同时包含UUU和UDU，就把edge_format变成RO, vector_replacement不需要填写，
        for td in self.twas:
            td_pattern = td.get_edge_pattern()
            if td_pattern not in self.wfcs_mappint:
                handler.on_parse_error(f"Warning: {td.signal}:{td.wfc}的边沿模式{td_pattern}无法正确计算边沿格式")
                td.vector_replacement = "X"
                continue
            else:
                td.vector_replacement, type  = self.wfcs_mappint.get(td_pattern, [td.wfc, ""])
                # 优先根据信号类型判断：InOut类型信号认为是STROBE
                if signal_type:
                    if signal_type == "Out":
                        td.is_strobe = 0
                    elif signal_type == "In":
                        td.is_strobe = 1
                    elif signal_type == "InOut":
                        td.is_strobe = 2
                    else:
                        td.is_strobe = -1
                if td.is_strobe == -1:
                    td.is_strobe = 0 if type == "C" else 1

    def get_edge_count(self) -> int:
            """获取有效边沿数量（时间和边沿都存在才算）"""
            count = 0
            if self.t1 and self.e1:
                count += 1
            if self.t2 and self.e2:
                count += 1
            if self.t3 and self.e3:
                count += 1
            if self.t4 and self.e4:
                count += 1
            return count
    
    def get_edge_pattern(self) -> str:
        """获取边沿模式（如 DUD, UDU, DU, UD 等）"""
        edges = []
        if self.e1:
            edges.append(self.e1.upper())
        if self.e2:
            edges.append(self.e2.upper())
        if self.e3:
            edges.append(self.e3.upper())
        if self.e4:
            edges.append(self.e4.upper())
        pattern = self._dedup_consecutive("".join(edges))
        return pattern

    def _dedup_consecutive(self, s: str) -> str:
        pattern = s.replace("N", "D")
        result = ''.join(k for k, _ in groupby(pattern))
        # 说明存在两个及以上的不相同的Edge
        if len(result) > 1:
            # 保持可以忽略
            result = result.replace("P", "")
            result = result.replace("X", "")
            result = result.replace("Z", "")
        return result