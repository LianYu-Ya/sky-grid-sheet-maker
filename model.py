# -*- coding: utf-8 -*-
"""格子谱数据模型：3 行 × 动态节拍的音符网格（version 2）。

行 0（高音行）: Y U I O P
行 1（中音行）: H J K L ;
行 2（低音行）: N M , . /

每个节拍（列）为一个音符对象数组 [(key, is_chord), ...]：
- 同一节拍内可同时存在多个主旋律键与多个和弦键；
- 同一键在一个节拍内唯一（添加重复键时更新其类型）；
- key 为 15 个键字母之一，is_chord=True 表示该键为和弦标记。
"""

ROWS = 3

# 15 个键位字母（顺序即键盘面板从左到右、从上到下的排列顺序）
KEYS = ["Y", "U", "I", "O", "P",
        "H", "J", "K", "L", ";",
        "N", "M", ",", ".", "/"]

# 主音（菱形 / 白底）：位于键盘中间列（6 个）
MAIN_KEYS = {"Y", "J", "K", "L", "M", "."}

# 变化音（圆形 / 浅灰底）：其余键
SHARP_KEYS = {k for k in KEYS if k not in MAIN_KEYS}

# 键 → 行号映射：YUIOP→0, HJKL;→1, NM,./→2
KEY_ROWS = {key: row for row, chunk in enumerate(
    (KEYS[0:5], KEYS[5:10], KEYS[10:15])) for key in chunk}

# 键 → 列号映射：每行内从左到右 0..4
KEY_COLS = {key: i % 5 for i, key in enumerate(KEYS)}

# 每横排可显示的节拍块数选项（兼容旧引用；新版 UI 用 QSpinBox 范围 4–16）
COLUMNS_PER_LINE_CHOICES = [4, 6, 8, 10, 12, 16]

# 默认主旋律标记色（红）
DEFAULT_MARK_COLOR = "#E84848"

# 默认和弦标记色（蓝）
DEFAULT_CHORD_COLOR = "#4A90D9"

# 键位编号（参考用户标注图：按 KEYS 顺序 1..7 循环）
KEY_NUMBERS = [(i % 7) + 1 for i in range(len(KEYS))]

# 音调名：按用户标注图，C 大调音阶循环（C D E F G A B ×2 + C，共 15 键）
KEY_TONES = {k: t for k, t in zip(
    KEYS, ["C", "D", "E", "F", "G", "A", "B",
           "C", "D", "E", "F", "G", "A", "B", "C"])}

# 键位图标类型（参考用户标注图，按 KEYS 顺序）：
# 菱形中带圆 ◈：Y K /（对角线分布，C 音专属）
# 纯菱形   ◇：U O J L M .
# 纯圆形   ○：其余（I P H ; N ,）
SHAPE_DIAMOND_CIRCLE = {"Y", "K", "/"}
SHAPE_DIAMOND = {"U", "O", "J", "L", "M", "."}
SHAPE_CIRCLE = {k for k in KEYS
                if k not in SHAPE_DIAMOND_CIRCLE and k not in SHAPE_DIAMOND}


class NoteGrid:
    """音符网格（version 2）。

    内部存储 self._cols: list[list[tuple[str, bool]]]，
    self._cols[beat] 为该节拍的音符对象数组，元素 (key, is_chord)，
    按插入顺序排列，同一节拍内 key 全局唯一。
    """

    def __init__(self, columns: int = 0):
        self._cols: list[list[tuple[str, bool]]] = []
        self.ensure_columns(columns)

    # ---------- 列管理 ----------

    def num_columns(self) -> int:
        """当前节拍数（列数）。"""
        return len(self._cols)

    def ensure_columns(self, n: int):
        """扩展节拍至至少 n 列，新增节拍均为空。"""
        while len(self._cols) < n:
            self._cols.append([])

    def is_beat_empty(self, col: int) -> bool:
        """判断某一节拍是否全空。"""
        if col < 0 or col >= len(self._cols):
            return True
        return len(self._cols[col]) == 0

    def last_used_beat(self) -> int:
        """最后一个存在音符的节拍号，无则返回 -1。"""
        for col in range(len(self._cols) - 1, -1, -1):
            if not self.is_beat_empty(col):
                return col
        return -1

    def trim_trailing_empty(self):
        """删除尾部全空节拍，至少保留 1 列。"""
        while len(self._cols) > 1 and self.is_beat_empty(len(self._cols) - 1):
            self._cols.pop()

    # ---------- 节拍内音符读写 ----------

    def notes(self, col: int) -> list[tuple[str, bool]]:
        """返回某节拍的音符对象列表 [(key, is_chord), ...]（副本，按插入顺序）。"""
        if col < 0 or col >= len(self._cols):
            return []
        return list(self._cols[col])

    def melody_keys(self, col: int) -> list[str]:
        """某节拍的全部主旋律键字母。"""
        return [k for k, c in self.notes(col) if not c]

    def chord_keys(self, col: int) -> list[str]:
        """某节拍的全部和弦键字母。"""
        return [k for k, c in self.notes(col) if c]

    def has_note(self, col: int, key: str) -> bool:
        """某节拍是否存在指定键（不分主旋律/和弦）。"""
        return any(k == key for k, _ in self.notes(col))

    def is_chord(self, col: int, key: str) -> bool:
        """某节拍中指定键是否为和弦标记。"""
        return any(k == key and c for k, c in self.notes(col))

    def set_note(self, col: int, key: str, chord: bool, present: bool):
        """设置某节拍中指定键的存在性与类型。

        present=True 时添加（已存在则更新类型），present=False 时移除；
        key 非法的调用被忽略。
        """
        if key not in KEYS:
            return
        self.ensure_columns(col + 1)
        col_notes = self._cols[col]
        for i, (k, _c) in enumerate(col_notes):
            if k == key:
                if present:
                    col_notes[i] = (key, bool(chord))
                else:
                    del col_notes[i]
                return
        if present:
            col_notes.append((key, bool(chord)))

    def toggle_note(self, col: int, key: str, chord: bool) -> bool:
        """切换某节拍中指定键的标记状态。

        同键同类型存在 → 移除；同键不同类型存在 → 更新类型；
        不存在 → 添加。返回切换后该键是否存在。
        key 非法的调用返回 False。
        """
        if key not in KEYS:
            return False
        self.ensure_columns(col + 1)
        col_notes = self._cols[col]
        for i, (k, c) in enumerate(col_notes):
            if k == key:
                if c == bool(chord):
                    del col_notes[i]        # 同类型 → 取消
                else:
                    col_notes[i] = (key, bool(chord))   # 不同类型 → 更新
                return True
        col_notes.append((key, bool(chord)))
        return True

    def delete_column(self, col: int):
        """删除某节拍（列），后续节拍整体左移；越界忽略；至少保留 1 列空拍。"""
        if 0 <= col < len(self._cols):
            del self._cols[col]
        if not self._cols:
            self._cols.append([])

    def clear_beat(self, col: int):
        """清空某节拍（列）的全部音符。"""
        if 0 <= col < len(self._cols):
            self._cols[col] = []

    def remove_key(self, col: int, key: str):
        """移除某节拍中指定键的标记（不分主旋律/和弦），键不存在时无副作用。"""
        if 0 <= col < len(self._cols) and key in KEYS:
            self._cols[col] = [(k, c) for k, c in self._cols[col] if k != key]

    def clear_cell(self, row: int, col: int):
        """清某节拍中该行（row）对应的全部音符。"""
        if 0 <= col < len(self._cols):
            row_keys = {k for k, r in KEY_ROWS.items() if r == row}
            col_notes = self._cols[col]
            self._cols[col] = [(k, c) for k, c in col_notes if k not in row_keys]

    def cell(self, row: int, col: int) -> str:
        """返回某节拍中该行的第一个主旋律键字母，无则 ""。"""
        if col < 0 or col >= len(self._cols):
            return ""
        for k, c in self._cols[col]:
            if KEY_ROWS.get(k) == row and not c:
                return k
        return ""

    def place_key(self, key: str, col: int, chord: bool = False) -> int:
        """将 key 放入第 col 节拍（添加或更新类型），自动扩展节拍；返回行号。

        key 不合法时返回 -1。
        """
        if key not in KEY_ROWS:
            return -1
        row = KEY_ROWS[key]
        self.set_note(col, key, chord, True)
        return row

    # ---------- 序列化 ----------

    def to_list(self) -> list[list[dict]]:
        """导出为 note_grid 结构（version 2）：[beat][{"k":键,"c":bool和弦}]。"""
        return [[{"k": k, "c": bool(c)} for k, c in col] for col in self._cols]

    def from_list(self, data):
        """用外部数据重建网格。

        兼容两种格式：
        - version 1：[col][row] 单字母字符串（转换为全部主旋律音符对象）；
        - version 2：[beat][{"k":.., "c":..}, ...]。
        每列最多保留 15 个音符，键非法或重复的条目被忽略。
        """
        new_cols: list[list[tuple[str, bool]]] = []
        for raw_col in data or []:
            col_notes: list[tuple[str, bool]] = []
            seen: set[str] = set()
            if isinstance(raw_col, list):
                for item in raw_col:
                    if len(col_notes) >= 15:
                        break
                    if isinstance(item, str):
                        # v1：单字母 → 主旋律
                        if item in KEYS and item not in seen:
                            col_notes.append((item, False))
                            seen.add(item)
                    elif isinstance(item, dict):
                        k = item.get("k")
                        if isinstance(k, str) and k in KEYS and k not in seen:
                            col_notes.append((k, bool(item.get("c", False))))
                            seen.add(k)
            new_cols.append(col_notes)
        # 至少保留 1 列
        if not new_cols:
            new_cols.append([])
        self._cols = new_cols
