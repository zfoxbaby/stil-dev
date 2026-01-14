# convert stil files to gasc files
import tkinter as tk
from tkinter import ttk, filedialog, scrolledtext, messagebox
import threading
import os
from datetime import datetime
from STILToGascStream import STILToGascStream
from htol.STILToVCTStream import STILToVCTStream
from htol.ChannelMappingDialog import ChannelMappingDialog
import Logger

class PATConvert:
    def __init__(self, root):
        self.root = root
        root.geometry("900x550")
        self.root.title("File Converter")
        
        # 用于存储当前正在运行的转换器实例
        self.current_parser = None
        self._stop_requested = False  # 停止批量转换的标志
        
        # VCT转换器实例（用于存储通道映射配置）
        self.vct_converter = None

        # ============ Container for Input and Output Groups (左右布局) ============
        container = ttk.Frame(root)
        container.pack(fill="x", padx=10, pady=5)

        # ============ Input Group (左边) ============
        input_group = ttk.LabelFrame(container, text="Input Group")
        input_group.pack(side="left", fill="both", expand=True, padx=(0, 5))

        # Source Type
        frame_type = ttk.Frame(input_group)
        frame_type.pack(fill="x", padx=5, pady=2)

        ttk.Label(frame_type, text="Source Type:").pack(side="left")
        self.source_type = ttk.Combobox(frame_type, values=["Standard", "Specify File"], state="readonly")
        self.source_type.bind("<<ComboboxSelected>>", self.select_combo)
        self.source_type.current(1)
        self.source_type.pack(side="left", padx=5, expand=True, fill="x")

        # Source File
        frame_source = ttk.Frame(input_group)
        frame_source.pack(fill="x", padx=5, pady=2)

        ttk.Label(frame_source, text="Source:").pack(side="left")
        self.source_var = tk.StringVar()
        self.source_entry = ttk.Entry(frame_source, textvariable=self.source_var, width=40)
        self.source_entry.pack(side="left", padx=5, expand=True, fill="x")
        self.source_browse_btn = ttk.Button(frame_source, text="...", command=self.select_source_type)
        self.source_browse_btn.pack(side="left")

        # ============ Output File Group (右边) ============
        output_group = ttk.LabelFrame(container, text="Output Group")
        output_group.pack(side="left", fill="both", padx=(5, 0))

        # Option Button
        frame_option = ttk.Frame(output_group)
        frame_option.pack(fill="x", padx=5, pady=2)
        self.option_btn = ttk.Button(frame_option, text="Option", command=self.on_option_click)
        self.option_btn.pack(side="left")

        # Radio Buttons: VCT and PAT
        frame_radio = ttk.Frame(output_group)
        frame_radio.pack(fill="x", padx=5, pady=2)
        self.output_format_var = tk.StringVar(value="VCT")  # 默认选中VCT
        self.vct_radio = ttk.Radiobutton(frame_radio, text="VCT", variable=self.output_format_var, value="VCT")
        self.vct_radio.pack(side="left", padx=5)
        self.pat_radio = ttk.Radiobutton(frame_radio, text="PAT", variable=self.output_format_var, value="PAT")
        self.pat_radio.pack(side="left", padx=5)

        # ============ Target Folder ============
        # frame_target = ttk.Frame(root)
        # frame_target.pack(fill="x", padx=10, pady=5)

        # ttk.Label(frame_target, text="Target:").pack(side="left")
        # self.target_var = tk.StringVar()
        # ttk.Entry(frame_target, textvariable=self.target_var, width=50).pack(side="left", padx=5, expand=True, fill="x")
        # ttk.Button(frame_target, text="...", command=self.select_target).pack(side="left")

        # ============ Start/Stop/Clear Buttons ============
        frame_start = ttk.Frame(root)
        frame_start.pack(fill="x", padx=10, pady=5)

        self.start_button = ttk.Button(frame_start, text="Start", command=self.start_conversion)
        self.start_button.pack(side="left", padx=5)
        
        self.stop_button = ttk.Button(frame_start, text="Stop", command=self.stop_conversion, state="disabled")
        self.stop_button.pack(side="left", padx=5)
        
        self.clear_button = ttk.Button(frame_start, text="Clear Log", command=self.clear_log)
        self.clear_button.pack(side="left", padx=5)

        # ============ Conversion Progress ============
        frame_progress = ttk.LabelFrame(root, text="Conversion Progress")
        frame_progress.pack(fill="both", expand=True, padx=10, pady=5)

        self.text_area = scrolledtext.ScrolledText(frame_progress, wrap="word", width=60, height=15)
        self.text_area.config(width=450, height=175)  # 设置最小宽高
        self.text_area.pack(fill="both", expand=True)
        
        # 配置红色文本标签（用于错误消息）
        self.text_area.tag_config("error", foreground="red")
        self.text_area.tag_config("warning", foreground="orange")

    def log(self, msg):
        """在进度框输出日志，自动管理文本长度避免内存溢出"""
        self.text_area.insert(tk.END, msg + "\n")
        # 检查滚动条是否在底部（或接近底部）
        # yview() 返回 (起始位置, 结束位置)，如 (0.0, 1.0) 表示显示全部
        # 如果结束位置 >= 0.99，认为在底部
        scroll_position = self.text_area.yview()
        at_bottom = scroll_position[1] >= 0.95

        # 更高效的文本长度管理：使用行数而不是字符数
        line_count = int(self.text_area.index('end-1c').split('.')[0])
        if line_count > 10000:  # 超过10000行时进行截断
            # 删除前5000行，保留后5000行
            self.text_area.delete("1.0", "5001.0")
            self.text_area.insert("1.0", "... [Log truncated, showing last 5000 lines] ...\n")
        
        # 只有在底部时才自动滚动
        if at_bottom:
            self.text_area.see(tk.END)
    
    def log_error(self, msg):
        """在进度框输出错误日志（红色字体）"""
        self.text_area.insert(tk.END, msg + "\n", "error")
        scroll_position = self.text_area.yview()
        at_bottom = scroll_position[1] >= 0.95
        line_count = int(self.text_area.index('end-1c').split('.')[0])
        if line_count > 10000:
            self.text_area.delete("1.0", "5001.0")
            self.text_area.insert("1.0", "... [Log truncated, showing last 5000 lines] ...\n")
        if at_bottom:
            self.text_area.see(tk.END)

    def log_warn(self, msg):
        """在进度框输出警告日志（黄色字体）"""
        self.text_area.insert(tk.END, msg + "\n", "warning")
        scroll_position = self.text_area.yview()
        at_bottom = scroll_position[1] >= 0.95
        line_count = int(self.text_area.index('end-1c').split('.')[0])
        if line_count > 10000:
            self.text_area.delete("1.0", "5001.0")
            self.text_area.insert("1.0", "... [Log truncated, showing last 5000 lines] ...\n")
        if at_bottom:
            self.text_area.see(tk.END)
    
    def clear_log(self):
        """清空日志文本框"""
        self.text_area.delete("1.0", tk.END)

    def set_controls_state(self, state: str) -> None:
        """设置 Input Group 和 Output File 控件的状态
        
        Args:
            state: "normal" 或 "disabled"
        """
        # Input Group 控件
        self.source_type.config(state=state if state == "disabled" else "readonly")
        self.source_entry.config(state=state)
        self.source_browse_btn.config(state=state)
        
        # Output File 控件
        self.option_btn.config(state=state)
        self.vct_radio.config(state=state)
        self.pat_radio.config(state=state)

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
            filetypes=[("STIL/WGL files", "*.stil"), ("All files", "*.*")]
        )
        if file_path:
            self.source_var.set(file_path)

    def select_source(self):
        source_folder_path = filedialog.askdirectory(title="Select Source File")
        if source_folder_path:
            self.source_var.set(source_folder_path)

    def on_option_click(self):
        """Option按钮点击事件 - 配置VCT通道映射"""
        # 检查是否选择了VCT格式
        if self.output_format_var.get() != "VCT":
            messagebox.showinfo("Info", "Option is only for VCT format. Please select VCT first.")
            return
        
        # 检查Source是否已选择
        source = self.source_var.get()
        if not source:
            messagebox.showwarning("Warning", "Please select a source file or folder first.")
            return
        
        # 确定要解析的文件
        if self.source_type.get() == "Specify File":
            if not os.path.isfile(source):
                messagebox.showerror("Error", f"File not found: {source}")
                return
            stil_file = source
        else:  # Standard - 文件夹模式，取第一个.stil文件
            if not os.path.isdir(source):
                messagebox.showerror("Error", f"Folder not found: {source}")
                return
            stil_files = [f for f in os.listdir(source) if f.endswith(".stil")]
            if not stil_files:
                messagebox.showerror("Error", f"No .stil files found in: {source}")
                return
            stil_file = os.path.join(source, stil_files[0])
            self.log(f"Using first STIL file: {stil_files[0]}")
        
        # 创建或复用VCT转换器
        self.log("=" * 50)
        
        # 检查是否需要重新解析（源文件变化或首次使用）
        old_mapping = None
        if self.vct_converter != None:
            old_mapping = self.vct_converter.get_channel_mapping().copy()
        self.log("Parsing STIL file, extracting signals...")
        self.vct_converter = STILToVCTStream(stil_file, progress_callback=self.progress_callback)
    
        # 启动线程防止 UI 卡死
        used_signals = self.vct_converter.read_stil_signals(print_log=True)
        #threading.Thread(target=self.convert, args=(source, target), daemon=True).start()
        
        
        if not used_signals:
            messagebox.showerror("Error", "Failed to extract signal info from STIL file.")
            return

        # VCT模式：重新读取信号并自动重新映射
        if old_mapping != None:
            result = self.vct_converter.refresh_signals_and_remap(old_mapping)    
            if not result['success']:
                messagebox.showerror("Error", f"Signal refresh failed: {result['error']}")
                return

        self.log("=" * 50)
        self.log("Opening channel mapping dialog...")
        
        # 弹出配置对话框
        dialog = ChannelMappingDialog(self.root, used_signals, self.vct_converter, self.log)
        self.root.wait_window(dialog.top)
        
        self.vct_converter.close()

        if dialog.result:
            self.log("Channel mapping configured!\n")
        else:
            self.log("Channel mapping cancelled.")
        
    # def select_target(self):
    #     folder_path = filedialog.askdirectory(title="Select Target Folder")
    #     if folder_path:
    #         self.target_var.set(folder_path)

    def start_conversion(self):
        source = self.source_var.get()
        target = ""
        
        # 检查Source是否已选择
        if not source:
            messagebox.showerror("Error", "Please select a source file or folder first")
            return
        
        # 如果是VCT模式，检查是否已配置通道映射
        if self.output_format_var.get() == "VCT":
            stil_file = source
            if self.source_type.get() == "Standard":
                stil_files = [f for f in os.listdir(source) if f.endswith(".stil")]
                if not stil_files:
                    messagebox.showerror("Error", f"No .stil files found in: {source}")
                    return
                stil_file = os.path.join(source, stil_files[0])
            if not self.vct_converter or not self.vct_converter.get_channel_mapping():
                # 弹出对话框，如果点击确定将从0开始自动映射通道. 点击X退出
                result = messagebox.askyesno("Info", "VCT mode requires channel mapping via Option button!\n"+
                "Click Yes to auto-map channels from 0.\nClick No to cancel.")
                if result:
                    self.vct_converter = STILToVCTStream(stil_file, progress_callback=self.progress_callback)
                    used_signals = self.vct_converter.read_stil_signals(print_log=True)
                    mapping = {signal: [i] for i, signal in enumerate(used_signals)}
                    self.vct_converter.set_channel_mapping(mapping)
                    self.log_error("No channel-to-pin mapping! Auto-mapping from channel 0, may not work on BIB board!")
                else:
                    return
            # # VCT模式：重新读取信号并自动重新映射
            # if not self._refresh_signal_mapping(source):
            #     # 用户取消或刷新失败
            #     return

        # 重置停止标志
        self._stop_requested = False
        
        # 启用Stop按钮，禁用Start按钮和输入控件
        self.start_button.config(state="disabled")
        self.stop_button.config(state="normal")
        self.set_controls_state("disabled")
        
        # 启动线程防止 UI 卡死
        threading.Thread(target=self.convert, args=(source, target), daemon=True).start()
    
    def stop_conversion(self):
        """停止当前的转换"""
        self._stop_requested = True  # 设置批量转换停止标志
        self.log("Stop button clicked, stopping conversion...")
        
        # 停止当前正在运行的解析器（PAT 或 VCT）
        if self.current_parser:
            self.current_parser.stop()
            self.log("Stopping parser...")
        if self.vct_converter:
            self.vct_converter.stop()
            self.log("Stopping VCT conversion...")

    def progress_callback(self, message):
        """Progress callback function with real-time vector counting"""
        if "Fail" in message or "failed" in message in message or "Error" in message or "ERROR" in message:
            self.log_error(message)
        elif "Warning" in message or "warning" in message:
            self.log_warn(message)
        else:
            self.log(message)
        # 强制UI更新，确保用户能看到进度
        self.root.update_idletasks()

    def convert_file(self, source_file, target_folder):
        """转换单个文件，根据选择的格式使用不同的转换器"""
        source_file_name = os.path.basename(source_file)
        output_format = self.output_format_var.get()
        
        # 根据输出格式确定文件后缀
        if output_format == "VCT":
            target_file_path = os.path.join(target_folder, os.path.splitext(source_file_name)[0] + ".vct")
        else:  # PAT
            target_file_path = os.path.join(target_folder, os.path.splitext(source_file_name)[0] + ".gasc")
        
        self.log(f"Source: {source_file}")
        self.log(f"Target: {target_file_path}")
        self.log(f"Format: {output_format}")
        
        # Record start time
        start_time = datetime.now()
        self.log(f"Start time: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
    
        
        try:
            if output_format == "VCT":
                # VCT格式转换
                self.convert_file_vct(source_file, target_file_path, self.progress_callback)
            else:
                # PAT格式转换（使用原有的STILToGascStream）
                self.convert_file_pat(source_file, target_file_path, self.progress_callback)
            
            # Calculate total time
            end_time = datetime.now()
            total_time = end_time - start_time
            self.log(f"End time: {end_time.strftime('%Y-%m-%d %H:%M:%S')}")
            self.log(f"Total conversion time: {total_time.total_seconds():.2f} seconds")
        except Exception as e:
            end_time = datetime.now()
            total_time = end_time - start_time
            Logger.error(f"Conversion failed after {total_time.total_seconds():.2f} seconds: {str(e)}", exc_info=True)
            raise
        finally:
            self.current_parser = None  # 清除parser实例
        self.log("="*100 + "\n")
    
    def convert_file_pat(self, source_file, target_file_path, progress_callback):
        """PAT格式转换（使用STILToGascStream）"""
        parser = STILToGascStream(source_file, target_file_path, progress_callback, debug=False)
        self.current_parser = parser
        result = parser.convert()
        if result == -1:
            self.log(f"{target_file_path} conversion stopped by user!")
        self.current_parser.close()
    
    def convert_file_vct(self, source_file, target_file_path, progress_callback):
        """VCT格式转换（使用STILToVCTStream）"""
        # 检查是否已配置通道映射
        if not self.vct_converter or not self.vct_converter.get_channel_mapping():
            raise Exception("Please configure channel mapping via Option button first!")
        
        # 批量转换时，每个文件需要重新读取信号并重新映射
        old_mapping = self.vct_converter.get_channel_mapping().copy()
        
        # 创建新的转换器实例
        new_converter = STILToVCTStream(source_file, target_file_path,
         progress_callback=progress_callback, debug=self.vct_converter.debug)
        
        # 刷新信号并自动重新映射
        result = new_converter.refresh_signals_and_remap(old_mapping)
        
        if not result['success']:
            raise Exception(f"Signal read failed: {result['error']}")
        
        if result['unmapped_signals']:
            progress_callback(f"⚠ {len(result['unmapped_signals'])} unmapped signals")
        
        # 设置 current_parser 以便 stop_conversion 能够停止它
        self.vct_converter = new_converter
        
        # 调用VCT转换
        progress_callback(f"Channel mapping: {len(result['new_mapping'])} signals")
        convert_result = new_converter.convert()
        if convert_result == -1:
            self.log(f"{target_file_path} conversion stopped by user!")

        new_converter.close()

    def convert(self, source, target):
        self.log(f"* * * Starting conversion...")
        self.log(f"Type: {self.source_type.get()}")
        try:
            if self.source_type.get() == "Specify File":
                # 获取source_type的父路径，然后拼接一个gasc文件夹，如果文件夹不存在则创建
                target = os.path.join(os.path.dirname(source), "converted")
                if not os.path.exists(target):
                    os.makedirs(target)
                self.convert_file(source, target)
            elif self.source_type.get() == "Standard":
                # 获取所有.stil文件
                stil_files = [f for f in os.listdir(source) if f.endswith(".stil")]
                total_files = len(stil_files)
                self.log(f"Found {total_files} STIL files")
                target = os.path.join(source, "converted")
                if not os.path.exists(target):
                    os.makedirs(target)
                for index, filename in enumerate(stil_files, 1):
                    # 检查是否请求停止
                    if self._stop_requested:
                        self.log(f"User stopped, {total_files - index + 1} files remaining")
                        break
                    
                    source_file = os.path.join(source, filename)
                    self.log(f"[{index}/{total_files}] Converting: {filename}")
                    try:
                        self.convert_file(source_file, target)
                    except Exception as e:
                        Logger.error(f"File {filename} conversion failed: {e}", exc_info=True)
                        # 继续转换下一个文件
                        continue
                    
                    # 转换完成后再次检查是否请求停止
                    if self._stop_requested:
                        self.log(f"User stopped, {total_files - index} files remaining")
                        break
            else:
                messagebox.showerror("Error", "Please select a valid source type")
                return
            
            if not self._stop_requested:
                self.log("All conversions completed!")
            else:
                self.log("Batch conversion stopped!")
        finally:
            # 转换完成或停止后，恢复按钮和控件状态
            self.start_button.config(state="normal")
            self.stop_button.config(state="disabled")
            self.set_controls_state("normal")

if __name__ == "__main__":
    # 初始化日志系统并安装全局异常处理器
    Logger.get_logger(console_output=True, file_output=True)
    Logger.install_global_exception_handler()
    
    root = tk.Tk()
    app = PATConvert(root)
    
    # 设置日志的 progress_callback 为 GUI 的 log 方法
    Logger.set_progress_callback(app.log)
    
    Logger.info("程序启动", notify_gui=False)
    root.mainloop()
    Logger.info("程序退出", notify_gui=False)