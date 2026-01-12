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
            self.text_area.insert("1.0", "... [日志已自动截断，显示最近 5000 行] ...\n")
        
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
            self.text_area.insert("1.0", "... [日志已自动截断，显示最近 5000 行] ...\n")
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
            filetypes=[("STIL/WGL files", "*.stil *.wgl"), ("All files", "*.*")]
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
            messagebox.showinfo("提示", "Option配置仅适用于VCT格式，请先选择VCT。")
            return
        
        # 检查Source是否已选择
        source = self.source_var.get()
        if not source:
            messagebox.showwarning("警告", "请先选择Source文件或文件夹。")
            return
        
        # 确定要解析的文件
        if self.source_type.get() == "Specify File":
            if not os.path.isfile(source):
                messagebox.showerror("错误", f"文件不存在: {source}")
                return
            stil_file = source
        else:  # Standard - 文件夹模式，取第一个.stil文件
            if not os.path.isdir(source):
                messagebox.showerror("错误", f"文件夹不存在: {source}")
                return
            stil_files = [f for f in os.listdir(source) if f.endswith(".stil")]
            if not stil_files:
                messagebox.showerror("错误", f"文件夹中没有找到.stil文件: {source}")
                return
            stil_file = os.path.join(source, stil_files[0])
            self.log(f"使用第一个STIL文件进行信号解析: {stil_files[0]}")
        
        # 创建或复用VCT转换器
        self.log("=" * 50)
        
        # 检查是否需要重新解析（源文件变化或首次使用）
        old_mapping = None
        if self.vct_converter != None:
            old_mapping = self.vct_converter.get_channel_mapping().copy()
        self.log("开始解析STIL文件，提取信号信息...")
        self.vct_converter = STILToVCTStream(stil_file, progress_callback=self.progress_callback)
    
        # 启动线程防止 UI 卡死
        used_signals = self.vct_converter.read_stil_signals(print_log=True)
        #threading.Thread(target=self.convert, args=(source, target), daemon=True).start()
        
        
        if not used_signals:
            messagebox.showerror("错误", "未能从STIL文件中提取到信号信息。")
            return

        # VCT模式：重新读取信号并自动重新映射
        if old_mapping != None:
            result = self.vct_converter.refresh_signals_and_remap(old_mapping)    
            if not result['success']:
                messagebox.showerror("错误", f"信号刷新失败: {result['error']}")
                return

        self.log("=" * 50)
        self.log("打开通道映射配置窗口...")
        
        # 弹出配置对话框
        dialog = ChannelMappingDialog(self.root, used_signals, self.vct_converter, self.log)
        self.root.wait_window(dialog.top)
        
        self.vct_converter.close()

        if dialog.result:
            self.log("通道映射配置完成！\n")
        else:
            self.log("通道映射配置已取消。")
        
    # def select_target(self):
    #     folder_path = filedialog.askdirectory(title="Select Target Folder")
    #     if folder_path:
    #         self.target_var.set(folder_path)

    def start_conversion(self):
        source = self.source_var.get()
        target = ""
        
        # 检查Source是否已选择
        if not source:
            messagebox.showerror("错误", "请先选择Source文件或文件夹")
            return
        
        # 如果是VCT模式，检查是否已配置通道映射
        if self.output_format_var.get() == "VCT":
            stil_file = source
            if self.source_type.get() == "Standard":
                stil_files = [f for f in os.listdir(source) if f.endswith(".stil")]
                if not stil_files:
                    messagebox.showerror("错误", "文件夹中没有找到.stil文件: {source}")
                    return
                stil_file = os.path.join(source, stil_files[0])
            if not self.vct_converter or not self.vct_converter.get_channel_mapping():
                # 弹出对话框，如果点击确定将从0开始自动映射通道. 点击X退出
                result = messagebox.askyesno("提示", "VCT模式需要先点击Option按钮配置通道映射！"+
                "\n如果点击确定将从0开始自动映射通道. \n点击X退出")
                if result:
                    self.vct_converter = STILToVCTStream(stil_file, progress_callback=self.progress_callback)
                    used_signals = self.vct_converter.read_stil_signals(print_log=True)
                    mapping = {signal: [i] for i, signal in enumerate(used_signals)}
                    self.vct_converter.set_channel_mapping(mapping)
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
    
    def _refresh_signal_mapping(self, source):
        """重新读取信号信息并自动重新映射
        
        Args:
            source: STIL文件或文件夹路径
            
        Returns:
            bool: True表示继续转换，False表示取消或失败
        """
        self.log("=" * 50)
        self.log("开始刷新信号映射...")
        
        # 确定要解析的文件
        if self.source_type.get() == "Specify File":
            stil_file = source
        else:  # Standard - 文件夹模式，取第一个.stil文件
            stil_files = [f for f in os.listdir(source) if f.endswith(".stil")]
            if stil_files:
                stil_file = os.path.join(source, stil_files[0])
            else:
                self.log("警告：未找到STIL文件，跳过信号刷新")
                self.log("=" * 50)
                return True  # 继续使用原配置
        
        # 保存旧的映射配置
        old_mapping = self.vct_converter.get_channel_mapping().copy()
        old_signal_count = len(old_mapping)
        self.log(f"当前有 {old_signal_count} 个信号已映射")
    
        
        # 创建新的转换器实例并刷新信号
        temp_converter = STILToVCTStream(stil_file, progress_callback=self.progress_callback, debug=self.vct_converter.debug)
        result = temp_converter.refresh_signals_and_remap(old_mapping)
        
        if not result['success']:
            self.log(f"警告：{result['error']}，使用原配置")
            self.log("=" * 50)
            return True  # 继续使用原配置
        
        # 更新转换器
        self.vct_converter = temp_converter
        
        # 输出映射结果
        self.log(f"重新读取到 {len(result['new_signals'])} 个信号")
        self.log(f"✓ 成功重新映射 {len(result['mapped_signals'])} 个信号")
        
        if result['removed_signals']:
            self.log(f"⚠ 有 {len(result['removed_signals'])} 个旧信号不再存在:")
            for sig in result['removed_signals'][:10]:  # 只显示前10个
                self.log(f"   - {sig}")
            if len(result['removed_signals']) > 10:
                self.log(f"   ... 还有 {len(result['removed_signals']) - 10} 个")
        
        if result['unmapped_signals']:
            self.log(f"⚠ 有 {len(result['unmapped_signals'])} 个新信号未映射:")
            for sig in result['unmapped_signals'][:10]:  # 只显示前10个
                self.log(f"   - {sig}")
            if len(result['unmapped_signals']) > 10:
                self.log(f"   ... 还有 {len(result['unmapped_signals']) - 10} 个")
            
            # 弹出提示
            msg = f"检测到 {len(result['unmapped_signals'])} 个新信号未映射到通道。\n\n"
            if len(result['unmapped_signals']) <= 5:
                msg += "未映射的信号:\n" + "\n".join(f"  • {sig}" for sig in result['unmapped_signals'])
            else:
                msg += "未映射的信号:\n" + "\n".join(f"  • {sig}" for sig in result['unmapped_signals'][:5])
                msg += f"\n  ... 还有 {len(result['unmapped_signals']) - 5} 个"
            msg += "\n\n是否继续转换？（未映射的信号将不输出）"
            
            if not messagebox.askyesno("信号映射提示", msg):
                self.log("用户取消转换")
                self.log("=" * 50)
                return False  # 用户取消
        
        self.log("信号映射刷新完成")
        self.log("=" * 50)
        return True  # 继续转换
    
    def stop_conversion(self):
        """停止当前的转换"""
        self._stop_requested = True  # 设置批量转换停止标志
        self.log("用户点击Stop按钮，正在停止转换...")
        
        # 停止当前正在运行的解析器（PAT 或 VCT）
        if self.current_parser:
            self.current_parser.stop()
            self.log("用户点击Stop按钮，正在停止转换...")
        if self.vct_converter:
            self.vct_converter.stop()
            self.log("用户点击Stop按钮，正在停止VCT转换...")

    def progress_callback(self, message):
        """Progress callback function with real-time vector counting"""
        if "错误" in message or "失败" in message or "Error" in message or "警告" in message:
            self.log_error(message)
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
            self.log(f"{target_file_path} conversion successfully!")
        except Exception as e:
            Logger.error(f"文件转换失败: {e}", exc_info=True)
            end_time = datetime.now()
            total_time = end_time - start_time
            self.log(f"Conversion failed after {total_time.total_seconds():.2f} seconds: {str(e)}")
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
    
    def convert_file_vct(self, source_file, target_file_path, progress_callback):
        """VCT格式转换（使用STILToVCTStream）"""
        # 检查是否已配置通道映射
        if not self.vct_converter or not self.vct_converter.get_channel_mapping():
            raise Exception("请先点击Option按钮配置通道映射！")
        
        # 批量转换时，每个文件需要重新读取信号并重新映射
        old_mapping = self.vct_converter.get_channel_mapping().copy()
        
        # 创建新的转换器实例
        new_converter = STILToVCTStream(source_file, target_file_path,
         progress_callback=progress_callback, debug=self.vct_converter.debug)
        
        # 刷新信号并自动重新映射
        result = new_converter.refresh_signals_and_remap(old_mapping)
        
        if not result['success']:
            raise Exception(f"信号读取失败: {result['error']}")
        
        if result['unmapped_signals']:
            progress_callback(f"⚠ 检测到 {len(result['unmapped_signals'])} 个新信号未映射")
        
        self.current_parser = new_converter
        
        # 调用VCT转换
        progress_callback(f"通道映射配置: {len(result['new_mapping'])} 个信号")
        convert_result = new_converter.convert()
        if convert_result == -1:
            self.log(f"{target_file_path} conversion stopped by user!")

        self.current_parser.close()

    def convert(self, source, target):
        self.log(f"Starting conversion...")
        self.log(f"Source: {source}")
        self.log(f"Target: {target}")
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
                self.log(f"找到 {total_files} 个STIL文件")
                target = os.path.join(source, "converted")
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
                        Logger.error(f"文件 {filename} 转换失败: {e}", exc_info=True)
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