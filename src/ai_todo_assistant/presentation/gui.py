"""
图形界面模块
使用tkinter提供可视化操作界面
优化版本:更大字体、更简洁布局、更低资源占用
"""
import tkinter as tk
from tkinter import ttk, messagebox
from datetime import datetime
from ai_todo_assistant.infrastructure.persistence import TodoManager
from ai_todo_assistant.presentation.calendar_view import CalendarView


class TodoGUI:
    """待办事项图形界面"""
    
    def __init__(self, root):
        """初始化GUI"""
        self.root = root
        self.root.title("待办事项管理")
        self.root.geometry("1000x650")
        
        # 设置窗口居中
        self.center_window(self.root, 1000, 650)
        
        # 设置主题样式
        self.setup_styles()
        
        self.manager = TodoManager()
        self.calendar_view = CalendarView()
        self.current_year, self.current_month = CalendarView.get_current_month()
        
        self.setup_ui()
        self.refresh_list()
    
    def center_window(self, window, width, height):
        """窗口居中"""
        screen_width = window.winfo_screenwidth()
        screen_height = window.winfo_screenheight()
        x = (screen_width - width) // 2
        y = (screen_height - height) // 2
        window.geometry(f"{width}x{height}+{x}+{y}")
    
    def setup_styles(self):
        """设置样式主题"""
        style = ttk.Style()
        
        # 设置整体字体
        default_font = ("Microsoft YaHei UI", 11)
        title_font = ("Microsoft YaHei UI", 20, "bold")
        button_font = ("Microsoft YaHei UI", 10)
        
        # 配置样式
        style.configure("Title.TLabel", font=title_font, foreground="#2c3e50")
        style.configure("TButton", font=button_font, padding=8)
        style.configure("TLabel", font=default_font)
        style.configure("Treeview", font=default_font, rowheight=30)
        style.configure("Treeview.Heading", font=("Microsoft YaHei UI", 11, "bold"))
        
        # 设置Notebook标签字体
        style.configure("TNotebook.Tab", font=("Microsoft YaHei UI", 11), padding=[20, 10])
    
    def setup_ui(self):
        """设置用户界面"""
        # 创建主框架
        main_frame = ttk.Frame(self.root, padding="20")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # 配置权重
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main_frame.columnconfigure(0, weight=1)
        main_frame.rowconfigure(1, weight=1)
        
        # 标题
        title_label = ttk.Label(
            main_frame,
            text="📝 待办事项管理",
            style="Title.TLabel"
        )
        title_label.grid(row=0, column=0, pady=(0, 20))
        
        # 创建Notebook(标签页)
        self.notebook = ttk.Notebook(main_frame)
        self.notebook.grid(row=1, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # 列表视图标签页
        self.list_frame = ttk.Frame(self.notebook, padding="15")
        self.notebook.add(self.list_frame, text="  📋 列表  ")
        self.setup_list_view()
        
        # 日历视图标签页
        self.calendar_frame = ttk.Frame(self.notebook, padding="15")
        self.notebook.add(self.calendar_frame, text="  📅 日历  ")
        self.setup_calendar_view()
        
        # 统计信息标签页
        self.stats_frame = ttk.Frame(self.notebook, padding="15")
        self.notebook.add(self.stats_frame, text="  📊 统计  ")
        self.setup_stats_view()
        
        # 绑定标签页切换事件 - 只在切换时刷新,减少资源占用
        self.notebook.bind("<<NotebookTabChanged>>", self.on_tab_changed)
    
    def setup_list_view(self):
        """设置列表视图"""
        # 按钮框架
        button_frame = ttk.Frame(self.list_frame)
        button_frame.grid(row=0, column=0, sticky=(tk.W, tk.E), pady=(0, 15))
        
        ttk.Button(button_frame, text="➕ 添加", command=self.add_todo, width=12).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="✏️ 编辑", command=self.edit_todo, width=12).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="✅ 完成", command=self.toggle_todo, width=12).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="🗑️ 删除", command=self.delete_todo, width=12).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="🔄 刷新", command=self.refresh_list, width=12).pack(side=tk.LEFT, padx=5)
        
        # 筛选框架
        filter_frame = ttk.Frame(self.list_frame)
        filter_frame.grid(row=1, column=0, sticky=(tk.W, tk.E), pady=(0, 15))
        
        ttk.Label(filter_frame, text="筛选:", font=("Microsoft YaHei UI", 11, "bold")).pack(side=tk.LEFT, padx=(0, 10))
        
        self.filter_var = tk.StringVar(value="all")
        ttk.Radiobutton(filter_frame, text="全部", variable=self.filter_var, value="all", command=self.refresh_list).pack(side=tk.LEFT, padx=5)
        ttk.Radiobutton(filter_frame, text="未完成", variable=self.filter_var, value="pending", command=self.refresh_list).pack(side=tk.LEFT, padx=5)
        ttk.Radiobutton(filter_frame, text="已完成", variable=self.filter_var, value="completed", command=self.refresh_list).pack(side=tk.LEFT, padx=5)
        ttk.Radiobutton(filter_frame, text="已过期", variable=self.filter_var, value="overdue", command=self.refresh_list).pack(side=tk.LEFT, padx=5)
        
        # 创建Treeview
        tree_frame = ttk.Frame(self.list_frame)
        tree_frame.grid(row=2, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        self.list_frame.rowconfigure(2, weight=1)
        
        # 滚动条
        scrollbar = ttk.Scrollbar(tree_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # Treeview
        self.tree = ttk.Treeview(
            tree_frame,
            columns=("status", "title", "due_date", "description"),
            show="headings",
            yscrollcommand=scrollbar.set
        )
        scrollbar.config(command=self.tree.yview)
        
        # 列定义
        self.tree.heading("status", text="状态")
        self.tree.heading("title", text="标题")
        self.tree.heading("due_date", text="截止日期")
        self.tree.heading("description", text="描述")
        
        self.tree.column("status", width=80, anchor=tk.CENTER)
        self.tree.column("title", width=250)
        self.tree.column("due_date", width=120, anchor=tk.CENTER)
        self.tree.column("description", width=350)
        
        self.tree.pack(fill=tk.BOTH, expand=True)
        
        # 双击事件
        self.tree.bind("<Double-1>", lambda e: self.toggle_todo())
    
    def setup_calendar_view(self):
        """设置交互式日历视图"""
        # 使用 Grid 布局替代 PanedWindow 以获得更稳定的布局
        # 调整权重: 左侧 55%，右侧 45%
        self.calendar_frame.columnconfigure(0, weight=11)
        self.calendar_frame.columnconfigure(1, weight=0)  # 分割线
        self.calendar_frame.columnconfigure(2, weight=9)
        self.calendar_frame.rowconfigure(0, weight=1)

        # 左侧：日历显示区域 - 减小 padding 避免拥挤
        self.left_cal_frame = ttk.Frame(self.calendar_frame, padding="10")
        self.left_cal_frame.grid(row=0, column=0, sticky="nsew")

        # 中间：分割线
        ttk.Separator(self.calendar_frame, orient=tk.VERTICAL).grid(row=0, column=1, sticky="ns", padx=2)

        # 右侧：任务详情区域 - 减小 padding
        self.right_detail_frame = ttk.Frame(self.calendar_frame, padding="10")
        self.right_detail_frame.grid(row=0, column=2, sticky="nsew")
        
        # --- 左侧日历内容 ---
        # 导航头 - 减小 pady
        nav_frame = ttk.Frame(self.left_cal_frame)
        nav_frame.pack(fill=tk.X, pady=(0, 10))
        
        # 缩小按钮宽度 (width=10 -> width=6)
        ttk.Button(nav_frame, text="◀ 上月", command=self.prev_month, width=6).pack(side=tk.LEFT)
        # 缩小标题字体 (18 -> 14)
        self.month_label = ttk.Label(nav_frame, text="", font=("Microsoft YaHei UI", 14, "bold"), anchor="center")
        self.month_label.pack(side=tk.LEFT, expand=True, fill=tk.X)
        # 缩小按钮宽度
        ttk.Button(nav_frame, text="下月 ▶", command=self.next_month, width=6).pack(side=tk.RIGHT)
        
        # 日历网格区域
        self.grid_frame = ttk.Frame(self.left_cal_frame)
        self.grid_frame.pack(fill=tk.BOTH, expand=True)
        
        # --- 右侧详情内容 ---
        # 详情标题 - 缩小字体
        self.detail_title = ttk.Label(self.right_detail_frame, text="任务详情", font=("Microsoft YaHei UI", 12, "bold"))
        self.detail_title.pack(fill=tk.X, pady=(0, 8))
        
        # 详情列表
        self.detail_text = tk.Text(
            self.right_detail_frame,
            font=("Microsoft YaHei UI", 10), # 字体微调
            bg="#fdfdfd",
            relief=tk.FLAT,
            padx=10,
            pady=10,
            state=tk.DISABLED
        )
        self.detail_text.pack(fill=tk.BOTH, expand=True)
        
        # 初始化选中的日期
        self.selected_date = datetime.now().strftime("%Y-%m-%d")

    def refresh_calendar(self):
        """刷新日历组件"""
        # 清空网格
        for widget in self.grid_frame.winfo_children():
            widget.destroy()
            
        # 设置星期表头
        days = ["一", "二", "三", "四", "五", "六", "日"]
        for i, day in enumerate(days):
            lbl = ttk.Label(self.grid_frame, text=day, font=("Microsoft YaHei UI", 12, "bold"), foreground="#7f8c8d", anchor="center")
            lbl.grid(row=0, column=i, pady=(0, 15), sticky="ew")
            
        # 获取当月日历数据
        import calendar
        cal = calendar.monthcalendar(self.current_year, self.current_month)
        
        # 获取当月有任务的日期
        todos_by_date = self.manager.get_by_month(self.current_year, self.current_month)
        
        # 填充日期
        today_str = datetime.now().strftime("%Y-%m-%d")
        
        for r_idx, week in enumerate(cal):
            self.grid_frame.rowconfigure(r_idx + 1, weight=1)
            
            for c_idx, day in enumerate(week):
                if day == 0:
                    # 占位符确保网格对齐
                    tk.Label(self.grid_frame, bg="#f0f0f0").grid(row=r_idx+1, column=c_idx, sticky="nsew", padx=2, pady=2)
                    continue
                
                date_str = f"{self.current_year:04d}-{self.current_month:02d}-{day:02d}"
                
                # --- 样式逻辑 ---
                if date_str == today_str:
                    text_color = "#3498db" # 今天
                elif c_idx >= 5: # 周末
                    text_color = "#e67e22"
                else:
                    text_color = "#2c3e50"
                
                bg_color = "#ffffff"
                if date_str == self.selected_date:
                    bg_color = "#d6eaf8"
                
                # --- 内容调整: 上面是点，下面是数字 ---
                # 用换行符实现布局:  • \n 27
                mark = ""
                if date_str in todos_by_date:
                    mark = "•"
                
                # 如果没有标记,用空格占位保持高度一致
                display_text = f"{mark if mark else ' '}\n{day}"
                
                btn = tk.Button(
                    self.grid_frame,
                    text=display_text,
                    font=("Microsoft YaHei UI", 11),
                    bg=bg_color,
                    fg=text_color,
                    relief=tk.FLAT,
                    padx=10,
                    pady=5,  # 稍微减小垂直padding，因为内容有两行
                    command=lambda d=date_str: self.select_date(d),
                    cursor="hand2",
                    justify=tk.CENTER # 文字居中
                )
                btn.grid(row=r_idx+1, column=c_idx, sticky="nsew", padx=3, pady=3)
                
        # 配置网格自适应
        for i in range(7):
            self.grid_frame.columnconfigure(i, weight=1, minsize=40) # 设置最小宽度确保一致
            
        # 更新月份标题
        self.month_label.config(text=f"{self.current_year}年 {self.current_month}月")
        
        # 更新右侧详情
        self.refresh_date_details()

    def select_date(self, date_str):
        """选择日期"""
        self.selected_date = date_str
        self.refresh_calendar()

    def refresh_date_details(self):
        """更新右侧详情面板"""
        self.detail_text.config(state=tk.NORMAL)
        self.detail_text.delete("1.0", tk.END)
        self.detail_title.config(text=f"📅 {self.selected_date} 任务详情")
        
        tasks = self.manager.get_tasks_on_date(self.selected_date)
        
        # 重新定义 Tag 样式，确保颜色生效
        self.detail_text.tag_configure("header", font=("Microsoft YaHei UI", 11, "bold"), foreground="#34495e", spacing1=10, spacing3=5)
        self.detail_text.tag_configure("normal", foreground="#2c3e50")
        # 优化颜色显示: 使用背景色块更明显，文字用黑色
        self.detail_text.tag_configure("urgent", background="#fff3cd", foreground="#856404") # 浅黄背景+深黄字
        self.detail_text.tag_configure("overdue", background="#f8d7da", foreground="#721c24") # 浅红背景+深红字
        self.detail_text.tag_configure("info", foreground="#95a5a6", font=("Microsoft YaHei UI", 10, "italic"))
        self.detail_text.tag_configure("small", font=("Microsoft YaHei UI", 9), foreground="#7f8c8d", lmargin1=20)
        
        if not tasks:
            self.detail_text.insert(tk.END, "\n今日无相关任务。", "info")
        else:
            # 分类
            starting = []
            ending = []
            ongoing = []
            
            for t in tasks:
                if t.start_time and t.start_time.startswith(self.selected_date):
                    starting.append(t)
                elif t.end_time and t.end_time.startswith(self.selected_date):
                    ending.append(t)
                else:
                    ongoing.append(t)
            
            self._insert_task_group("🚀 当天开始", starting)
            self._insert_task_group("🔔 当天截止", ending)
            self._insert_task_group("🔄 正在进行", ongoing)
            
        self.detail_text.config(state=tk.DISABLED)

    def _insert_task_group(self, title, tasks):
        """插入任务组到详情区"""
        if not tasks:
            return
            
        self.detail_text.insert(tk.END, f"{title}\n", "header")
        for i, t in enumerate(tasks, 1):
            status = "✓" if t.completed else "✗"
            tag = "normal"
            suffix = ""
            
            if not t.completed:
                if t.is_overdue():
                    tag = "overdue"
                    suffix = " [已过期]"
                elif t.is_urgent():
                    tag = "urgent"
                    suffix = " [即将到期]"
            
            # 使用整体高亮
            line_content = f" {i}. [{status}] {t.title}{suffix}\n"
            self.detail_text.insert(tk.END, line_content, tag)
            
            if t.end_time:
                self.detail_text.insert(tk.END, f"    截止: {t.end_time}\n", "small")
    
    def setup_stats_view(self):
        """设置统计视图"""
        self.stats_text = tk.Text(
            self.stats_frame,
            font=("Microsoft YaHei UI", 13),
            wrap=tk.WORD,
            bg="#f8f9fa",
            relief=tk.FLAT,
            padx=20,
            pady=20
        )
        self.stats_text.pack(fill=tk.BOTH, expand=True)

    def refresh_list(self):
        """刷新列表"""
        # 清空现有项
        for item in self.tree.get_children():
            self.tree.delete(item)
        
        # 获取待办事项
        filter_type = self.filter_var.get()
        
        if filter_type == "all":
            todos = self.manager.get_all()
        elif filter_type == "pending":
            todos = self.manager.get_by_status(False)
        elif filter_type == "completed":
            todos = self.manager.get_by_status(True)
        elif filter_type == "overdue":
            todos = self.manager.get_overdue()
        else:
            todos = []
        
        # 对任务进行排序：按截止时间排序
        todos.sort(key=lambda x: x.end_time or "9999-12-31")

        # 添加到树形视图
        for todo in todos:
            status = "✓" if todo.completed else "✗"
            due_date = todo.end_time or ""
            start_date = todo.start_time or ""
            
            self.tree.insert(
                "",
                tk.END,
                iid=todo.id,
                values=(status, todo.title, f"{start_date} ~ {due_date}", todo.description)
            )

    
    def refresh_stats(self):
        """刷新统计"""
        self.stats_text.delete("1.0", tk.END)
        
        stats = self.manager.get_statistics()
        
        stats_str = f"""
📊 待办事项统计信息
{'=' * 50}

总计: {stats['total']}
已完成: {stats['completed']}
未完成: {stats['pending']}
已过期: {stats['overdue']}
完成率: {stats['completion_rate']}

{'=' * 50}
        """
        
        self.stats_text.insert("1.0", stats_str)
    
    def add_todo(self):
        """添加待办事项"""
        dialog = AddTodoDialog(self.root, self.manager)
        self.root.wait_window(dialog.dialog)
        self.refresh_list()
    
    def edit_todo(self):
        """编辑待办事项"""
        selection = self.tree.selection()
        if not selection:
            messagebox.showwarning("警告", "请先选择一个待办事项")
            return
        
        todo_id = selection[0]
        todo = self.manager.get_by_id(todo_id)
        
        if todo:
            dialog = EditTodoDialog(self.root, self.manager, todo)
            self.root.wait_window(dialog.dialog)
            self.refresh_list()
    
    def toggle_todo(self):
        """切换完成状态"""
        selection = self.tree.selection()
        if not selection:
            messagebox.showwarning("警告", "请先选择一个待办事项")
            return
        
        todo_id = selection[0]
        self.manager.toggle_completed(todo_id)
        self.refresh_list()
    
    def delete_todo(self):
        """删除待办事项"""
        selection = self.tree.selection()
        if not selection:
            messagebox.showwarning("警告", "请先选择一个待办事项")
            return
        
        if messagebox.askyesno("确认", "确定要删除这个待办事项吗?"):
            todo_id = selection[0]
            self.manager.delete(todo_id)
            self.refresh_list()
    
    def prev_month(self):
        """上一个月"""
        self.current_year, self.current_month = CalendarView.get_prev_month(
            self.current_year, self.current_month
        )
        self.refresh_calendar()
    
    def next_month(self):
        """下一个月"""
        self.current_year, self.current_month = CalendarView.get_next_month(
            self.current_year, self.current_month
        )
        self.refresh_calendar()
    
    def goto_current_month(self):
        """回到本月"""
        self.current_year, self.current_month = CalendarView.get_current_month()
        self.refresh_calendar()
    
    
    def on_tab_changed(self, event):
        """标签页切换事件"""
        current_tab = self.notebook.index(self.notebook.select())
        
        if current_tab == 0:  # 列表视图
            self.refresh_list()
        elif current_tab == 1:  # 日历视图
            self.refresh_calendar()
        elif current_tab == 2:  # 统计视图
            self.refresh_stats()


class AddTodoDialog:
    """添加待办事项对话框"""
    
    def __init__(self, parent, manager):
        self.manager = manager
        
        self.dialog = tk.Toplevel(parent)
        self.dialog.title("添加待办事项")
        self.dialog.geometry("600x480")
        self.dialog.transient(parent)
        self.dialog.grab_set()
        
        # 居中显示
        self.center_dialog(parent, 600, 480)
        
        # 设置内边距
        main_frame = ttk.Frame(self.dialog, padding="25")
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # 标题
        ttk.Label(
            main_frame,
            text="标题:",
            font=("Microsoft YaHei UI", 11, "bold")
        ).grid(row=0, column=0, sticky=tk.W, pady=(0, 10))
        
        self.title_entry = ttk.Entry(main_frame, width=45, font=("Microsoft YaHei UI", 11))
        self.title_entry.grid(row=0, column=1, pady=(0, 10), sticky=(tk.W, tk.E))
        self.title_entry.focus()
        
        # 描述
        ttk.Label(
            main_frame,
            text="描述:",
            font=("Microsoft YaHei UI", 11, "bold")
        ).grid(row=1, column=0, sticky=(tk.W, tk.N), pady=(0, 10))
        
        self.desc_text = tk.Text(main_frame, width=45, height=4, font=("Microsoft YaHei UI", 11))
        self.desc_text.grid(row=1, column=1, pady=(0, 10), sticky=(tk.W, tk.E))
        
        # 开始时间
        ttk.Label(
            main_frame,
            text="开始时间:",
            font=("Microsoft YaHei UI", 11, "bold")
        ).grid(row=2, column=0, sticky=tk.W, pady=(0, 10))
        
        start_frame = ttk.Frame(main_frame)
        start_frame.grid(row=2, column=1, pady=(0, 10), sticky=tk.W)
        
        self.start_date_entry = ttk.Entry(start_frame, width=15, font=("Microsoft YaHei UI", 11))
        self.start_date_entry.pack(side=tk.LEFT)
        self.start_date_entry.insert(0, datetime.now().strftime("%Y-%m-%d"))
        
        ttk.Label(start_frame, text=" ").pack(side=tk.LEFT)
        self.start_hour = ttk.Combobox(start_frame, values=[f"{i:02d}:00" for i in range(24)], width=8, font=("Microsoft YaHei UI", 11))
        self.start_hour.pack(side=tk.LEFT)
        self.start_hour.set(datetime.now().strftime("%H:00"))
        
        # 截止时间
        ttk.Label(
            main_frame,
            text="截止时间:",
            font=("Microsoft YaHei UI", 11, "bold")
        ).grid(row=3, column=0, sticky=tk.W, pady=(0, 20))
        
        end_frame = ttk.Frame(main_frame)
        end_frame.grid(row=3, column=1, pady=(0, 20), sticky=tk.W)
        
        self.end_date_entry = ttk.Entry(end_frame, width=15, font=("Microsoft YaHei UI", 11))
        self.end_date_entry.pack(side=tk.LEFT)
        self.end_date_entry.insert(0, datetime.now().strftime("%Y-%m-%d"))
        
        ttk.Label(end_frame, text=" ").pack(side=tk.LEFT)
        self.end_hour = ttk.Combobox(end_frame, values=[f"{i:02d}:00" for i in range(24)], width=8, font=("Microsoft YaHei UI", 11))
        self.end_hour.pack(side=tk.LEFT)
        self.end_hour.set(datetime.now().strftime("%H:00"))
        
        # 按钮
        button_frame = ttk.Frame(main_frame)
        button_frame.grid(row=4, column=0, columnspan=2)
        
        ttk.Button(
            button_frame,
            text="确定",
            command=self.save,
            width=15
        ).pack(side=tk.LEFT, padx=10)
        
        ttk.Button(
            button_frame,
            text="取消",
            command=self.dialog.destroy,
            width=15
        ).pack(side=tk.LEFT, padx=10)
        
        # 配置列权重
        main_frame.columnconfigure(1, weight=1)
    
    def center_dialog(self, parent, width, height):
        """对话框居中"""
        self.dialog.update_idletasks()
        parent_x = parent.winfo_x()
        parent_y = parent.winfo_y()
        parent_width = parent.winfo_width()
        parent_height = parent.winfo_height()
        
        x = parent_x + (parent_width - width) // 2
        y = parent_y + (parent_height - height) // 2
        
        self.dialog.geometry(f"{width}x{height}+{x}+{y}")
    
    def save(self):
        """保存"""
        title = self.title_entry.get().strip()
        if not title:
            messagebox.showerror("错误", "标题不能为空", parent=self.dialog)
            return
        
        description = self.desc_text.get("1.0", tk.END).strip()
        start_time = f"{self.start_date_entry.get()} {self.start_hour.get()}".strip()
        end_time = f"{self.end_date_entry.get()} {self.end_hour.get()}".strip()
        
        try:
            self.manager.add(title, description, start_time, end_time)
            messagebox.showinfo("成功", "添加成功!", parent=self.dialog)
            self.dialog.destroy()
        except Exception as e:
            messagebox.showerror("错误", f"格式错误: {e}", parent=self.dialog)


class EditTodoDialog:
    """编辑待办事项对话框"""
    
    def __init__(self, parent, manager, todo):
        self.manager = manager
        self.todo = todo
        
        self.dialog = tk.Toplevel(parent)
        self.dialog.title("编辑待办事项")
        self.dialog.geometry("600x480")
        self.dialog.transient(parent)
        self.dialog.grab_set()
        
        # 居中显示
        self.center_dialog(parent, 600, 480)
        
        # 设置内边距
        main_frame = ttk.Frame(self.dialog, padding="25")
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # 标题
        ttk.Label(
            main_frame,
            text="标题:",
            font=("Microsoft YaHei UI", 11, "bold")
        ).grid(row=0, column=0, sticky=tk.W, pady=(0, 10))
        
        self.title_entry = ttk.Entry(main_frame, width=45, font=("Microsoft YaHei UI", 11))
        self.title_entry.grid(row=0, column=1, pady=(0, 10), sticky=(tk.W, tk.E))
        self.title_entry.insert(0, todo.title)
        self.title_entry.focus()
        
        # 描述
        ttk.Label(
            main_frame,
            text="描述:",
            font=("Microsoft YaHei UI", 11, "bold")
        ).grid(row=1, column=0, sticky=(tk.W, tk.N), pady=(0, 10))
        
        self.desc_text = tk.Text(main_frame, width=45, height=4, font=("Microsoft YaHei UI", 11))
        self.desc_text.grid(row=1, column=1, pady=(0, 10), sticky=(tk.W, tk.E))
        self.desc_text.insert("1.0", todo.description)

        # 时间解析
        s_date, s_hour = "", ""
        if todo.start_time:
            parts = todo.start_time.split(' ')
            s_date = parts[0]
            s_hour = parts[1] if len(parts) > 1 else "00:00"
        
        e_date, e_hour = "", ""
        if todo.end_time:
            parts = todo.end_time.split(' ')
            e_date = parts[0]
            e_hour = parts[1] if len(parts) > 1 else "00:00"

        # 开始时间
        ttk.Label(
            main_frame,
            text="开始时间:",
            font=("Microsoft YaHei UI", 11, "bold")
        ).grid(row=2, column=0, sticky=tk.W, pady=(0, 10))
        
        start_frame = ttk.Frame(main_frame)
        start_frame.grid(row=2, column=1, pady=(0, 10), sticky=tk.W)
        
        self.start_date_entry = ttk.Entry(start_frame, width=15, font=("Microsoft YaHei UI", 11))
        self.start_date_entry.pack(side=tk.LEFT)
        self.start_date_entry.insert(0, s_date)
        
        ttk.Label(start_frame, text=" ").pack(side=tk.LEFT)
        self.start_hour = ttk.Combobox(start_frame, values=[f"{i:02d}:00" for i in range(24)], width=8, font=("Microsoft YaHei UI", 11))
        self.start_hour.pack(side=tk.LEFT)
        self.start_hour.set(s_hour)
        
        # 截止时间
        ttk.Label(
            main_frame,
            text="截止时间:",
            font=("Microsoft YaHei UI", 11, "bold")
        ).grid(row=3, column=0, sticky=tk.W, pady=(0, 20))
        
        end_frame = ttk.Frame(main_frame)
        end_frame.grid(row=3, column=1, pady=(0, 20), sticky=tk.W)
        
        self.end_date_entry = ttk.Entry(end_frame, width=15, font=("Microsoft YaHei UI", 11))
        self.end_date_entry.pack(side=tk.LEFT)
        self.end_date_entry.insert(0, e_date)
        
        ttk.Label(end_frame, text=" ").pack(side=tk.LEFT)
        self.end_hour = ttk.Combobox(end_frame, values=[f"{i:02d}:00" for i in range(24)], width=8, font=("Microsoft YaHei UI", 11))
        self.end_hour.pack(side=tk.LEFT)
        self.end_hour.set(e_hour)
        
        # 按钮
        button_frame = ttk.Frame(main_frame)
        button_frame.grid(row=4, column=0, columnspan=2)
        
        ttk.Button(
            button_frame,
            text="保存",
            command=self.save,
            width=15
        ).pack(side=tk.LEFT, padx=10)
        
        ttk.Button(
            button_frame,
            text="取消",
            command=self.dialog.destroy,
            width=15
        ).pack(side=tk.LEFT, padx=10)
        
        main_frame.columnconfigure(1, weight=1)
    
    def center_dialog(self, parent, width, height):
        """对话框居中"""
        self.dialog.update_idletasks()
        parent_x = parent.winfo_x()
        parent_y = parent.winfo_y()
        parent_width = parent.winfo_width()
        parent_height = parent.winfo_height()
        
        x = parent_x + (parent_width - width) // 2
        y = parent_y + (parent_height - height) // 2
        
        self.dialog.geometry(f"{width}x{height}+{x}+{y}")
    
    def save(self):
        """保存"""
        title = self.title_entry.get().strip()
        if not title:
            messagebox.showerror("错误", "标题不能为空", parent=self.dialog)
            return
        
        description = self.desc_text.get("1.0", tk.END).strip()
        start_time = f"{self.start_date_entry.get()} {self.start_hour.get()}".strip()
        end_time = f"{self.end_date_entry.get()} {self.end_hour.get()}".strip()
        
        try:
            self.manager.update(self.todo.id, title, description, start_time, end_time)
            messagebox.showinfo("成功", "更新成功!", parent=self.dialog)
            self.dialog.destroy()
        except Exception as e:
            messagebox.showerror("错误", f"格式错误: {e}", parent=self.dialog)


def main():
    """主函数"""
    root = tk.Tk()
    app = TodoGUI(root)
    print("GUI 应用已启动。")
    root.mainloop()


if __name__ == "__main__":
    main()

