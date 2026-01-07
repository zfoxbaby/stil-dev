from dataclasses import dataclass, field
from typing import List
from typing import Optional, Callable
from STILEventHandler import STILEventHandler

@dataclass
class TimingData:
    """Timing Data
    
    存储波形定义信息，包括：
    - 波形表名称、周期、信号名、WFC
    - 最多4组时间/边沿对 (t1/e1 到 t4/e4)
    - 边沿类型和Vector转换信息
    """
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
    is_strobe: int = -1       # 是否是比较沿（STROBE=0），否则是驱动沿（CLOCK=1）
    edge_format: str = ""         # 边沿格式: NRZ/DNRZ/RZ/RO
    vector_replacement: str = ""  # Vector生成时的替换字符: P(DUD)/N(UDU)/空(不替换)
    
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
        return "".join(edges)
    
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
        if strobe_wfcs is None:
            strobe_wfcs = {'L', 'H', 'l', 'h'}
        
        # 优先根据信号类型判断：InOut类型信号认为是STROBE
        if signal_type:
            if signal_type == "InOut" or signal_type == "Out":
                self.is_strobe = 0
            elif signal_type == "In":
                self.is_strobe = 1
            else:
                self.is_strobe = -1
        else:
            # 向后兼容：根据WFC字符判断
            # 判断是否是比较沿，需要把wfc拆分成单个字符，然后到strobe_wfcs中找，
            # 如果有一个wfc的单个字符存在就是比较沿，否则是驱动沿
            for wfc in self.wfc:
                if wfc in strobe_wfcs:
                    self.is_strobe = 0
                    break
            else:
                self.is_strobe = 1
        
        if (self.is_strobe == -1 and self.parent is None):
            progress_callback(f"Warning: {self.signal}:信号类型是{signal_type}，而不是InOut/Out/In，{self.wfc}无法正确计算边沿格式")
            return

        # 计算边沿格式
        edge_count = self.get_edge_count()
        pattern = self.get_edge_pattern()
        
        if edge_count <= 1:
            self.edge_format = "NORMAL"
            self.vector_replacement = ""
        elif edge_count == 2:
            if pattern in ("DU", "UD"):
                self.edge_format = "DNRZ"
            else:
                self.edge_format = ""
            self.vector_replacement = ""

        # 如果是父节点，此时获取所有子节点，如果所有子节点中同时包含UDU子集和DUD子集，因为可能出现4个沿，
        # 就包含UDU的TimingData的vector_replacement变成N，包含DUD的TimingData的vector_replacement变成P，
        # 此时不需要edge_format。
        # 如果所有子节点中同时包含DDD和DUD，就把edge_format变成RZ, vector_replacement不需要填写，
        # 如果所有子节点中同时包含UUU和UDU，就把edge_format变成RO, vector_replacement不需要填写，
        if edge_count >= 3 and self.parent is None:
            hasUUU = False; hasDUD = False; hasDDD = False; hasUDU = False;
            for td in self.twas:
                child_edges = td.get_edge_pattern()
                if child_edges.find("UUU") != -1:
                    hasUUU = hasUUU | True
                if child_edges.find("DUD") != -1:
                    hasDUD = hasDUD | True
                if child_edges.find("DDD") != -1:
                    hasDDD = hasDDD | True
                if child_edges.find("UDU") != -1:
                    hasUDU = hasUDU | True
            
            if hasUUU and hasUDU and not hasDDD and not hasDUD:
                self.edge_format = "RO"
            elif hasDDD and hasDUD and not hasUUU and not hasUDU:
                self.edge_format = "RZ"
            else:
                # 到这一步如果所有子节点没有Format,则初段DUD和UDU的就需要转换成P/N
                for td in self.twas:
                    child_edges = td.get_edge_pattern()
                    if not td.edge_format:
                        if child_edges.find("DUD") != -1:
                            td.vector_replacement = "P"
                        elif child_edges.find("UDU") != -1:
                            td.vector_replacement = "N"
