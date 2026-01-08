# STIL 转换与解析工具说明文档

## 1. 软件概述

### 1.1 功能简介

本工具用于将 **STIL (Standard Test Interface Language)** 格式的测试向量文件转换为其他格式，支持：

- **VCT 格式**：适用于 HTOL（High Temperature Operating Life）测试的向量格式，支持 256 通道映射
- **GASC 格式**：通用 ATE 扫描代码格式

### 1.2 主要特性

- 流式解析，支持大文件处理
- 实时进度显示
- 通道映射配置（支持导入/导出 Excel、CSV、JSON）
- 微指令自动映射
- Procedure 和 MacroDef 自动展开
- 嵌套 Loop 支持
- 智能日志滚动

---

## 2. 支持的 STIL 结构

### 2.1 头部信息

| 块名称 | 说明 |
|--------|------|
| `STIL` | 版本声明 |
| `Header` | 标题、日期、来源等元信息 |
| `Signals` | 信号定义（In、Out、InOut、Supply、Pseudo） |
| `SignalGroups` | 信号组定义 |
| `Timing` | 时序定义（WaveformTable） |

### 2.2 Pattern 语句

| 语句类型 | 说明 | VCT 映射 |
|----------|------|----------|
| `V { }` | 向量数据 | ADV |
| `W wft_name;` | 波形表切换 | RRADR 切换 |
| `Loop count { }` | 循环块 | LI/RPT + JNI |
| `MatchLoop count { }` | 匹配循环 | MBGN + MEND/IMATCH |
| `Call proc_name;` | 调用 Procedure | CALL（或展开） |
| `Macro macro_name;` | 调用 MacroDef | 展开 |
| `Stop;` | 停止 | HALT |
| `Goto label;` | 跳转 | JUMP |
| `IddqTestPoint;` | IDDQ 测试点 | IDDQ |
| `label:` | 标签定义 | 标签行 |

### 2.3 重复指令

STIL 支持向量数据中的重复指令：

```stil
V { signal = \r10 0; }  // 重复 10 个 '0'
```

工具会自动展开为完整的向量字符串。

---

## 3. VCT 格式转换

### 3.1 VCT 文件结构

VCT 文件包含以下部分：

```
; 文件头注释（来源、日期等）
; Timing 定义注释
; DRVR 通道分配
#VECTOR
  ORG 0
; 信号名垂直排列
; 通道号标尺
VECTOR:
START:
  MSSA          % .. ..0 ................ ... 0 1  [256通道数据] ; 0x000000
  ADV           % .. ..0 ................ ... 0 1  [256通道数据] ; 0x000001
  ...
#VECTOREND
```

### 3.2 Vector 行格式

每行 Vector 数据格式（共 51 字符前缀 + 256 通道 + 地址）：

```
  [微指令14字符]% [MRST MCMP] [GTST TENA TMEM] [RESERVED 16字符] [SYNC 3字符] [RRADR] [CS]  [256通道] ; 0x[地址]
```

| 字段 | 宽度 | 说明 |
|------|------|------|
| 微指令 | 14 | 如 `ADV`, `RPT 50`, `HALT` |
| MRST | 1 | Master Reset |
| MCMP | 1 | Master Compare |
| GTST | 1 | Global Test |
| TENA | 1 | Test Enable |
| TMEM | 1 | Test Memory |
| RESERVED | 16 | 保留位 |
| SYNC | 3 | 同步位 |
| RRADR | 1 | 波形表编号 (0-7) |
| CS | 1 | Chip Select |
| 通道数据 | 256 | 每通道一个字符 |
| 地址 | 6 | 十六进制向量地址 |

### 3.3 微指令映射表

| STIL 指令 | VCT 指令 | 说明 |
|-----------|----------|------|
| (无) | ADV | 默认前进 |
| `Loop n` | LI0/LI1/LI2/LI3 | 循环开始（n 为嵌套层级） |
| `Loop` (单V) | RPT n | 重复指令 |
| (Loop 结束) | JNI0/JNI1/JNI2/JNI3 | 跳回循环开始 |
| `MatchLoop` | MBGN | 匹配循环开始 |
| (MatchLoop 结束) | MEND | 匹配循环结束 |
| (MatchLoop 单V) | IMATCH | 立即匹配 |
| `Stop` | HALT | 停止 |
| `Goto label` | JUMP label | 跳转 |
| `Call proc` | CALL proc | 调用（未展开时） |
| `Return` | RET | 返回 |
| `IddqTestPoint` | IDDQ | IDDQ 测试 |

### 3.4 通道映射

VCT 格式使用 256 个通道（0-255），需要将 STIL 中的信号映射到具体通道：

- 每个信号可以映射到一个或多个通道
- 未映射的通道输出 `.`
- 通过 Option 对话框配置映射关系

### 3.5 WFC 字符替换

根据 Timing 定义中的波形，WFC（Waveform Character）可能被替换：

| 原始 WFC | 替换后 | 条件 |
|----------|--------|------|
| 0 | D | Drive Low |
| 1 | U | Drive High |
| L | l | Strobe Low |
| H | h | Strobe High |
| X | X | Don't Care |
| Z | Z | High-Z |

---

## 4. GASC 格式转换

### 4.1 GASC 文件结构

```
HEADER {
     signal1,signal2,signal3,...;
}

Signals {
     signal1,signal2,signal3,...;
}

SignalGroups {
     group1 = 'sig1 + sig2';
}

Timing {
     wft_name, period, signal, wfc, t1, e1, t2, e2, t3, e3, t4, e4;
}

SPM_PATTERN (SCAN) {
       *向量数据*#微指令;波形表:标签
       *向量数据*#微指令
       ...
}
```

### 4.2 向量行格式

```
       *[向量数据]*#[微指令];[波形表]:[标签]
```

- 向量数据：按 Header 中信号顺序排列的 WFC 字符
- 微指令：可选，如 `LI0 50`、`HALT`
- 波形表：可选，波形切换时显示
- 标签：可选，标签名

---

## 5. GUI 使用说明

### 5.1 界面布局

```
+------------------+------------------+
|   Input Group    |   Output Group   |
+------------------+------------------+
| Source Type: [v] | [Option]         |
| Source: [...] [.]| (o) VCT  (o) PAT |
+------------------+------------------+
| [Start] [Stop] [Clear Log]         |
+------------------------------------+
|         Conversion Progress         |
|  [日志文本区域，支持智能滚动]        |
+------------------------------------+
```

### 5.2 操作步骤

#### 转换为 VCT 格式

1. **选择源文件**：设置 Source Type 为 "Specify File"，点击 `...` 选择 STIL 文件
2. **配置通道映射**：
   - 点击 `Option` 按钮
   - 系统自动解析 STIL 文件中的信号
   - 为每个信号配置通道号（0-255）
   - 可导入/导出映射配置
3. **选择输出格式**：选择 `VCT`
4. **开始转换**：点击 `Start`
5. **查看进度**：在日志区域查看转换进度

#### 转换为 GASC/PAT 格式

1. 选择源文件
2. 选择 `PAT` 格式
3. 点击 `Start`（无需配置通道映射）

### 5.3 Option 对话框（通道映射）

| 功能 | 说明 |
|------|------|
| 信号列表 | 显示 STIL 文件中使用的信号 |
| 通道配置 | 为每个信号配置通道号，支持多通道（逗号分隔） |
| 导入 | 从 Excel/CSV/JSON 导入映射配置 |
| 导出 | 导出当前配置到 Excel/CSV/JSON |
| 确定 | 保存配置并关闭 |
| 取消 | 放弃修改 |

#### 导入文件格式

**Excel/CSV 格式：**
```
Signal,Channel
clk,0
data,1,2,3
reset,10
```

**JSON 格式：**
```json
{
  "clk": [0],
  "data": [1, 2, 3],
  "reset": [10]
}
```

---

## 6. 高级功能

### 6.1 Procedure 和 MacroDef 展开

工具会自动解析 STIL 文件中的 `Procedures` 和 `MacroDefs` 块，当遇到 `Call` 或 `Macro` 指令时自动展开内容。

```stil
Procedures {
  init_proc {
    W wft1;
    V { sig = 0; }
    V { sig = 1; }
  }
}

Pattern test {
  Call init_proc;  // 自动展开为 init_proc 的内容
}
```

### 6.2 嵌套 Loop 支持

支持最多 4 层嵌套循环（LI0-LI3）：

```stil
Loop 10 {           // LI0
  V { ... }
  Loop 5 {          // LI1
    V { ... }
  }                 // JNI1
  V { ... }
}                   // JNI0
```

### 6.3 禁用指令配置

可以在代码中配置禁用的指令，遇到这些指令时会跳过并提示用户：

```python
# STILParserTransformer.py
DISABLED_INSTRUCTIONS: List[str] = [
    "ScanChain",    # 禁用 ScanChain
    "Shift",        # 禁用 Shift
]
```

### 6.4 日志智能滚动

- 正常情况下，日志自动滚动到最新内容
- 用户滚动查看历史日志时，自动滚动暂停
- 滚动回底部后，恢复自动滚动
- 超过 10000 行时自动截断，保留最近 5000 行

---

## 7. 文件说明

| 文件 | 说明 |
|------|------|
| `PATConvert.py` | GUI 主程序 |
| `STILParserTransformer.py` | STIL 解析器（Transformer 实现） |
| `STILToVCTStream.py` | VCT 格式转换器 |
| `STILToGascStream.py` | GASC 格式转换器 |
| `STILEventHandler.py` | 事件处理接口 |
| `STILParserUtils.py` | 解析工具函数 |
| `TimingData.py` | Timing 数据结构 |
| `TimingFormatter.py` | Timing 格式化 |
| `MicroInstructionMapper.py` | 微指令映射（已集成到 Transformer） |
| `ChannelMappingDialog.py` | 通道映射对话框 |
| `Logger.py` | 日志系统 |

---

## 8. 常见问题

### Q1: 转换时提示"未能从STIL文件中提取到信号信息"

**原因**：STIL 文件格式不正确或缺少必要的块

**解决**：检查文件是否包含 `Signals`、`Pattern` 等必要块

### Q2: VCT 文件中部分通道显示 `.`

**原因**：该通道未映射信号

**解决**：在 Option 中为相关信号配置通道号

### Q3: Loop 转换后指令不正确

**原因**：Loop 块结构不符合预期

**说明**：
- 单个 V 的 Loop → RPT
- 多个 V 的 Loop → LI + JNI
- Loop 块中只能有 1 个或 2 个 V 语句

### Q4: 转换速度慢

**建议**：
- 大文件会显示进度百分比
- 可以点击 Stop 中断转换
- 日志区域会自动截断避免内存溢出

---

## 9. 版本历史

| 版本 | 日期 | 更新内容 |
|------|------|----------|
| 1.0 | 2026-01 | 初始版本，支持 VCT 和 GASC 转换 |

---

*文档生成日期：2026年1月*

