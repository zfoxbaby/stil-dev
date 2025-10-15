# convert stil files to gasc files
import tkinter as tk
from tkinter import ttk, filedialog, scrolledtext, messagebox
import threading
import time
import os
from datetime import datetime
from STILToGascStream import STILToGascStream

class ConverterGUI:
    def __init__(self, root):
        self.root = root
        root.geometry("700x550")
        self.root.title("File Converter")
        
        # 用于存储当前正在运行的转换器实例
        self.current_parser = None
        self._stop_requested = False  # 停止批量转换的标志

        # ============ Source Type ============
        frame_type = ttk.Frame(root)
        frame_type.pack(fill="x", padx=10, pady=5)

        ttk.Label(frame_type, text="Source Type:").pack(side="left")
        self.source_type = ttk.Combobox(frame_type, values=["Standard", "Specify File"], state="readonly")
        self.source_type.bind("<<ComboboxSelected>>", self.select_combo)
        self.source_type.current(1)
        self.source_type.pack(side="left", padx=5, expand=True, fill="x")

        # ============ Fast Mode Option ============
        #frame_fast = ttk.Frame(root)
        #frame_fast.pack(fill="x", padx=10, pady=5)
        #self.fast_mode_var = tk.BooleanVar(value=True)
        #ttk.Checkbutton(frame_fast, text="Fast Mode (Recommended for large files/No Include)", 
        #               variable=self.fast_mode_var).pack(side="left")

        # ============ Source File ============
        frame_source = ttk.Frame(root)
        frame_source.pack(fill="x", padx=10, pady=5)

        ttk.Label(frame_source, text="Source:").pack(side="left")
        self.source_var = tk.StringVar()
        ttk.Entry(frame_source, textvariable=self.source_var, width=50).pack(side="left", padx=5, expand=True, fill="x")
        ttk.Button(frame_source, text="...", command=self.select_source_type).pack(side="left")

        # ============ Target Folder ============
        # frame_target = ttk.Frame(root)
        # frame_target.pack(fill="x", padx=10, pady=5)

        # ttk.Label(frame_target, text="Target:").pack(side="left")
        # self.target_var = tk.StringVar()
        # ttk.Entry(frame_target, textvariable=self.target_var, width=50).pack(side="left", padx=5, expand=True, fill="x")
        # ttk.Button(frame_target, text="...", command=self.select_target).pack(side="left")

        # ============ Start/Stop Buttons ============
        frame_start = ttk.Frame(root)
        frame_start.pack(fill="x", padx=10, pady=5)

        self.start_button = ttk.Button(frame_start, text="Start", command=self.start_conversion)
        self.start_button.pack(side="left", padx=5)
        
        self.stop_button = ttk.Button(frame_start, text="Stop", command=self.stop_conversion, state="disabled")
        self.stop_button.pack(side="left", padx=5)

        # ============ Conversion Progress ============
        frame_progress = ttk.LabelFrame(root, text="Conversion Progress")
        frame_progress.pack(fill="both", expand=True, padx=10, pady=5)

        self.text_area = scrolledtext.ScrolledText(frame_progress, wrap="word", width=60, height=15)
        self.text_area.config(width=450, height=175)  # 设置最小宽高
        self.text_area.pack(fill="both", expand=True)

    def log(self, msg):
        """在进度框输出日志，自动管理文本长度避免内存溢出"""
        self.text_area.insert(tk.END, msg + "\n")
        
        # 更高效的文本长度管理：使用行数而不是字符数
        line_count = int(self.text_area.index('end-1c').split('.')[0])
        if line_count > 5000:  # 超过5000行时进行截断
            # 删除前3000行，保留后2000行
            self.text_area.delete("1.0", "3001.0")
            self.text_area.insert("1.0", "... [日志已自动截断，显示最近 2000 行] ...\n")
        
        self.text_area.see(tk.END)

    def select_combo(self, event=None):
        # set source text empty when the source_type be selected
        self.source_var.set("")

    def select_source_type(self):
        source_type = self.source_type.get()
        if source_type == "Standard":
            self.select_source()
        elif source_type == "Specify File":
            self.select_source_file()

    def select_source_file(self):
        file_path = filedialog.askopenfilename(
            title="Select Source File",
            filetypes=[("STIL/WGL files", "*.stil *.wgl"), ("All files", "*.*")]
        )
        if file_path:
            self.source_var.set(file_path)

    def select_source(self):
        source_folder_path = filedialog.askdirectory(title="Select Source File")
        if source_folder_path:
            self.source_var.set(source_folder_path)

    # def select_target(self):
    #     folder_path = filedialog.askdirectory(title="Select Target Folder")
    #     if folder_path:
    #         self.target_var.set(folder_path)

    def start_conversion(self):
        source = self.source_var.get()
        # target = self.target_var.get()
        target = ""
        #if not source or not os.path.isfile(source):
        #    messagebox.showerror("Error", "Please select a valid source file (.stil / .wgl)")
        #    return
        # if not target or not os.path.isdir(target):
        #     messagebox.showerror("Error", "Please select a valid target folder")
        #     return

        # 重置停止标志
        self._stop_requested = False
        
        # 启用Stop按钮，禁用Start按钮
        self.start_button.config(state="disabled")
        self.stop_button.config(state="normal")
        
        # 启动线程防止 UI 卡死
        threading.Thread(target=self.convert, args=(source, target), daemon=True).start()
    
    def stop_conversion(self):
        """停止当前的转换"""
        self._stop_requested = True  # 设置批量转换停止标志
        if self.current_parser:
            self.current_parser.stop()
            self.log("用户点击Stop按钮，正在停止转换...")

    def convert_file(self, source_file, target_folder):
        # get file name from source
        source_file_name = os.path.basename(source_file)
        # 去掉后缀，加上.gasc
        target_file_path = os.path.join(target_folder, os.path.splitext(source_file_name)[0] + ".gasc")
        self.log(f"Source: {source_file}")
        self.log(f"Target: {target_file_path}")
        
        # Record start time
        start_time = datetime.now()
        self.log(f"Start time: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
        
        def progress_callback(message):
            """Progress callback function with real-time vector counting"""
            elapsed = datetime.now() - start_time
            self.log(f"{message} (Elapsed: {elapsed.total_seconds():.1f}s)")
            # 强制UI更新，确保用户能看到进度
            self.root.update_idletasks()
        
        parser = STILToGascStream(source_file, target_file_path, progress_callback, debug=False)
        self.current_parser = parser  # 保存当前parser实例
        try:
            result = parser.convert()
            # Calculate total time
            end_time = datetime.now()
            total_time = end_time - start_time
            self.log(f"End time: {end_time.strftime('%Y-%m-%d %H:%M:%S')}")
            self.log(f"Total conversion time: {total_time.total_seconds():.2f} seconds")
            if result == -1:
                self.log(f"{target_file_path} conversion stopped by user!")
            else:
                self.log(f"{target_file_path} conversion successfully!")
        except Exception as e:
            end_time = datetime.now()
            total_time = end_time - start_time
            self.log(f"Conversion failed after {total_time.total_seconds():.2f} seconds: {str(e)}")
            raise
        finally:
            self.current_parser = None  # 清除parser实例

    def convert(self, source, target):
        self.log(f"Starting conversion...")
        self.log(f"Source: {source}")
        self.log(f"Target: {target}")
        self.log(f"Type: {self.source_type.get()}")
        try:
            if self.source_type.get() == "Specify File":
                # 获取source_type的父路径，然后拼接一个gasc文件夹，如果文件夹不存在则创建
                target = os.path.join(os.path.dirname(source), "gasc")
                if not os.path.exists(target):
                    os.makedirs(target)
                self.convert_file(source, target)
            elif self.source_type.get() == "Standard":
                # 获取所有.stil文件
                stil_files = [f for f in os.listdir(source) if f.endswith(".stil")]
                total_files = len(stil_files)
                self.log(f"找到 {total_files} 个STIL文件")
                target = os.path.join(os.path.dirname(source), "gasc")
                if not os.path.exists(target):
                    os.makedirs(target)
                for index, filename in enumerate(stil_files, 1):
                    # 检查是否请求停止
                    if self._stop_requested:
                        self.log(f"用户停止批量转换，剩余 {total_files - index + 1} 个文件未转换")
                        break
                    
                    source_file = os.path.join(source, filename)
                    self.log(f"[{index}/{total_files}] 开始转换: {filename}")
                    try:
                        self.convert_file(source_file, target)
                    except Exception as e:
                        self.log(f"文件 {filename} 转换失败: {str(e)}")
                        # 继续转换下一个文件
                        continue
                    
                    # 转换完成后再次检查是否请求停止
                    if self._stop_requested:
                        self.log(f"用户停止批量转换，剩余 {total_files - index} 个文件未转换")
                        break
            else:
                messagebox.showerror("Error", "Please select a valid source type")
                return
            
            if not self._stop_requested:
                self.log("所有转换完成!")
            else:
                self.log("批量转换已停止!")
        finally:
            # 转换完成或停止后，恢复按钮状态
            self.start_button.config(state="normal")
            self.stop_button.config(state="disabled")

if __name__ == "__main__":
    root = tk.Tk()
    app = ConverterGUI(root)
    root.mainloop()