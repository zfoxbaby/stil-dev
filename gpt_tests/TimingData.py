from dataclasses import dataclass, field
from typing import List

@dataclass
class TimingData:
    """Timing Data"""
    wft: str = ""          # 波形表名称
    period: str = ""
    signal: str = ""
    wfc: str = ""
    t1: str = ""
    e1: str = ""
    t2: str = "" 
    e2: str = ""
    t3: str = ""
    e3: str = ""
    t4: str = ""
    e4: str = ""
    twas: List = field(default_factory=list)
    # def __init__(self):
        # self.wft: str      # 波形表名称
        # self.period: str
        # self.signal: str
        # self.wfc: str
        # self.time1: str
        # self.edge1: str
        # self.time2: str
        # self.edge2: str
        # self.time3: str
        # self.edge3: str
        # self.time4: str
        # self.edge4: str
