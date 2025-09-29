# convert stil files to gasc files
import tkinter as tk
from tkinter import ttk, filedialog, scrolledtext, messagebox
import threading
import time
import os
from datetime import datetime
from STILToGasc import STILToGasc 


class ConverterGUI:
    def __init__(self, root):
        self.root = root
        root.geometry("700x550")
        self.root.title("File Converter")

        # ============ Source Type ============
        frame_type = ttk.Frame(root)
        frame_type.pack(fill="x", padx=10, pady=5)

        ttk.Label(frame_type, text="Source Type:").pack(side="left")
        self.source_type = ttk.Combobox(frame_type, values=["Standard", "Specify File"], state="readonly")
        self.source_type.bind("<<ComboboxSelected>>", self.select_combo)
        self.source_type.current(0)
        self.source_type.pack(side="left", padx=5, expand=True, fill="x")

        # ============ Fast Mode Option ============
        frame_fast = ttk.Frame(root)
        frame_fast.pack(fill="x", padx=10, pady=5)
        
        self.fast_mode_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(frame_fast, text="Fast Mode (Recommended for large files/No Include)", 
                       variable=self.fast_mode_var).pack(side="left")

        # ============ Source File ============
        frame_source = ttk.Frame(root)
        frame_source.pack(fill="x", padx=10, pady=5)

        ttk.Label(frame_source, text="Source:").pack(side="left")
        self.source_var = tk.StringVar()
        ttk.Entry(frame_source, textvariable=self.source_var, width=50).pack(side="left", padx=5, expand=True, fill="x")
        ttk.Button(frame_source, text="...", command=self.select_source_type).pack(side="left")

        # ============ Target Folder ============
        frame_target = ttk.Frame(root)
        frame_target.pack(fill="x", padx=10, pady=5)

        ttk.Label(frame_target, text="Target:").pack(side="left")
        self.target_var = tk.StringVar()
        ttk.Entry(frame_target, textvariable=self.target_var, width=50).pack(side="left", padx=5, expand=True, fill="x")
        ttk.Button(frame_target, text="...", command=self.select_target).pack(side="left")

        # ============ Start Button ============
        frame_start = ttk.Frame(root)
        frame_start.pack(fill="x", padx=10, pady=5)

        ttk.Button(frame_start, text="Start", command=self.start_conversion).pack(side="left", padx=0)

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

    def select_target(self):
        folder_path = filedialog.askdirectory(title="Select Target Folder")
        if folder_path:
            self.target_var.set(folder_path)

    def start_conversion(self):
        source = self.source_var.get()
        target = self.target_var.get()
        #if not source or not os.path.isfile(source):
        #    messagebox.showerror("Error", "Please select a valid source file (.stil / .wgl)")
        #    return
        if not target or not os.path.isdir(target):
            messagebox.showerror("Error", "Please select a valid target folder")
            return

        # 启动线程防止 UI 卡死
        threading.Thread(target=self.convert, args=(source, target), daemon=True).start()

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
        fast_mode = self.fast_mode_var.get()
        self.log(f"Fast Mode: {'Enabled' if fast_mode else 'Disabled'}")
        
        def progress_callback(message):
            """Progress callback function with real-time vector counting"""
            elapsed = datetime.now() - start_time
            self.log(f"{message} (Elapsed: {elapsed.total_seconds():.1f}s)")
            # 强制UI更新，确保用户能看到进度
            self.root.update_idletasks()
        
        stil_to_gasc = STILToGasc(source_file, target_file_path,
             fast_mode=fast_mode, progress_callback=progress_callback)
        try:
            stil_to_gasc.convert()
            # Calculate total time
            end_time = datetime.now()
            total_time = end_time - start_time
            self.log(f"End time: {end_time.strftime('%Y-%m-%d %H:%M:%S')}")
            self.log(f"Total conversion time: {total_time.total_seconds():.2f} seconds")
            self.log(f"{target_file_path} conversion successfully!")
        except Exception as e:
            end_time = datetime.now()
            total_time = end_time - start_time
            self.log(f"Conversion failed after {total_time.total_seconds():.2f} seconds: {str(e)}")
            raise

    def convert(self, source, target):
        self.log(f"Starting conversion...")
        self.log(f"Source: {source}")
        self.log(f"Target: {target}")
        self.log(f"Type: {self.source_type.get()}")
        if self.source_type.get() == "Specify File":
            self.convert_file(source, target)
        elif self.source_type.get() == "Standard":
            for filename in os.listdir(source):
                if not filename.endswith(".stil"):   # 找到所有.stil文件
                    continue
                source_file = os.path.join(source, filename)
                self.convert_file(source_file, target)
        else:
            messagebox.showerror("Error", "Please select a valid source type")
            return
        self.log("Conversion  successfully!")

if __name__ == "__main__":
    root = tk.Tk()
    app = ConverterGUI(root)
    root.mainloop()