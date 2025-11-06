#REDME

```bash
py -3.11

pip install pyinstaller

# 基本打包（生成单个文件夹）
pyinstaller --onedir --windowed --name="STIL转换工具" gpt_tests/PATConvert.py

# 打包成单个exe文件（推荐）
pyinstaller --onefile --windowed --name="STIL转换工具" gpt_tests/PATConvert.py

# 添加图标（如果有）
pyinstaller --onefile --windowed --icon=icon.ico --name="STIL转换工具" gpt_tests/PATConvert.py

--onefile：打包成单个exe文件
--onedir：打包成文件夹（exe + 依赖文件）
--windowed 或 -w：不显示控制台窗口（GUI程序必需）
--name：指定生成的exe文件名
--icon：指定exe图标

# 先生成spec文件
pyinstaller --onefile --windowed --name="STIL转换工具" gpt_tests/PATConvert.py

# 然后修改生成的 STIL转换工具.spec 文件

```