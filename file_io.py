# -*- coding: utf-8 -*-
""".ggp 源文件（JSON）读写、应用数据目录管理与历史乐谱列表浏览。

.ggp 文件格式（version 2）：
{
  "version": 2,
  "title": "标题",
  "created_at": "ISO 时间字符串",
  "updated_at": "ISO 时间字符串",
  "columns_per_line": 4,
  "keys": ["Y", ...],          # 15 个键字母，供校验
  "rows": 3,
  "note_grid": [[{"k":"Y","c":false}, ...], ...],   # [beat][音符对象]
  "mark_color": "#E84848",     # 可选：主旋律标记色
  "chord_color": "#4A90D9"     # 可选：和弦标记色
}

向后兼容 version 1：v1 的 note_grid 为 [col][row] 单字母字符串，
加载时由 NoteGrid.from_list 自动转换为全部主旋律的音符对象。
"""

import json
import os
import pathlib
import shutil
import datetime
import re

from model import KEYS, ROWS, NoteGrid, DEFAULT_MARK_COLOR, DEFAULT_CHORD_COLOR

VERSION = 2

# 乐谱 .ggp 单独存放的应用子目录名（用英文避免路径编码问题）
SHEETS_DIR_NAME = "sheets"

# 合法 hex 颜色字符串（#RRGGBB）
_HEX_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")


def _now_iso() -> str:
    """当前本地时间的 ISO 格式字符串。"""
    return datetime.datetime.now().isoformat(timespec="seconds")


def default_data_dir() -> pathlib.Path:
    """返回默认数据目录：应用文件夹下的"乐谱"子目录（保存 .ggp），不存在则创建。"""
    data_dir = pathlib.Path(__file__).resolve().parent / SHEETS_DIR_NAME
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


def save_ggp(path, title: str, columns_per_line: int, grid: NoteGrid,
             mark_color: str | None = None,
             chord_color: str | None = None) -> None:
    """将乐谱保存为 .ggp JSON 文件（version 2）。

    若文件已存在，保留原 created_at，只更新 updated_at。
    mark_color / chord_color 非空时写入可选字段（#RRGGBB），为空则省略。
    编码 utf-8、ensure_ascii=False。
    """
    path = pathlib.Path(path)
    old_created = None
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                old_data = json.load(f)
            old_created = old_data.get("created_at")
        except (OSError, ValueError):
            old_created = None

    data = {
        "version": VERSION,
        "title": title,
        "created_at": old_created or _now_iso(),
        "updated_at": _now_iso(),
        "columns_per_line": int(columns_per_line),
        "keys": KEYS,
        "rows": ROWS,
        "note_grid": grid.to_list(),
    }
    if mark_color:
        data["mark_color"] = str(mark_color)
    if chord_color:
        data["chord_color"] = str(chord_color)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _is_valid_key(k) -> bool:
    """判断是否为合法的键字母（允许文件里带数字键名等 OCR 扩展，但必须为字符串）。"""
    return isinstance(k, str) and len(k) == 1 and k.isprintable() and not k.isspace()


def _read_color(raw, default: str) -> str:
    """读取颜色字段：合法 hex（#RRGGBB）字符串原样返回，否则回退默认色。"""
    if isinstance(raw, str) and _HEX_COLOR_RE.match(raw):
        return raw
    return default


def load_ggp(path) -> dict:
    """加载 .ggp 文件并返回规范化字典。

    返回字段：{version, title, created_at, updated_at, columns_per_line,
              keys, note_grid, mark_color, chord_color}；字段缺失给安全默认值。
    mark_color / chord_color 为合法 hex（#RRGGBB）颜色字符串，
    缺失或非法分别回退 DEFAULT_MARK_COLOR / DEFAULT_CHORD_COLOR。
    keys 不匹配时以文件为准但校验合法键；note_grid 兼容 v1/v2 格式，
    非合法键按空处理；columns_per_line 默认 4；version 透传原始值。
    """
    path = pathlib.Path(path)
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    if not isinstance(raw, dict):
        raw = {}

    # keys：以文件为准，但过滤非法键；空则退回默认 KEYS
    file_keys = raw.get("keys") or KEYS
    if not isinstance(file_keys, list):
        file_keys = KEYS
    keys = [k for k in file_keys if _is_valid_key(k)]
    if not keys:
        keys = list(KEYS)
    # 去重保持顺序
    keys = list(dict.fromkeys(keys))

    # note_grid：兼容 v1（[col][row] 单字母）与 v2（[beat][音符对象]）
    raw_grid = raw.get("note_grid") or []
    if not isinstance(raw_grid, list):
        raw_grid = []
    grid = NoteGrid()
    grid.from_list(raw_grid)

    # rows 字段以文件为准（>=1），但模型固定 3 行
    rows = raw.get("rows")
    try:
        rows = int(rows) if rows is not None else ROWS
    except (TypeError, ValueError):
        rows = ROWS
    if rows < 1:
        rows = ROWS

    try:
        cpl = int(raw.get("columns_per_line") or 4)
    except (TypeError, ValueError):
        cpl = 4

    mark_color = _read_color(raw.get("mark_color"), DEFAULT_MARK_COLOR)
    chord_color = _read_color(raw.get("chord_color"), DEFAULT_CHORD_COLOR)

    return {
        "version": raw.get("version", VERSION),
        "title": str(raw.get("title") or ""),
        "created_at": str(raw.get("created_at") or ""),
        "updated_at": str(raw.get("updated_at") or ""),
        "columns_per_line": cpl,
        "keys": keys,
        "rows": rows,
        "note_grid": grid.to_list(),
        "mark_color": mark_color,
        "chord_color": chord_color,
    }


def list_sheets(data_dir) -> list[dict]:
    """扫描 data_dir 下所有 *.ggp，返回按修改时间倒序的 [{title, path, mtime}]。

    title 优先读 JSON 内 title，读取失败则用文件名（不含扩展名）。
    """
    data_dir = pathlib.Path(data_dir)
    result: list[dict] = []
    if not data_dir.exists():
        return result

    for f in data_dir.glob("*.ggp"):
        try:
            stat = f.stat()
            mtime = stat.st_mtime
            mtime_text = datetime.datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M")
        except OSError:
            mtime = 0.0
            mtime_text = ""

        title = f.stem
        try:
            with open(f, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, dict) and data.get("title"):
                title = str(data["title"])
        except (OSError, ValueError):
            pass

        result.append({
            "title": title,
            "path": str(f),
            "mtime": mtime,
            "mtime_text": mtime_text,
        })

    result.sort(key=lambda item: item["mtime"], reverse=True)
    return result


def copy_sheet(path) -> str:
    """复制乐谱文件为同目录下"<原名> - 副本.ggp"（重名自动加序号），返回新路径。"""
    src = pathlib.Path(path)
    new_path = src.with_name(f"{src.stem} - 副本{src.suffix}")
    n = 2
    while new_path.exists():
        new_path = src.with_name(f"{src.stem} - 副本{n}{src.suffix}")
        n += 1
    shutil.copy2(src, new_path)
    return str(new_path)


def rename_sheet(path, new_title: str) -> str:
    """重命名乐谱：更新 JSON 内 title 并把文件改名为 <new_title>.ggp，返回新路径。

    new_title 为空时仅返回原路径；目标重名时自动加 (2)/(3)… 后缀。
    """
    src = pathlib.Path(path)
    new_title = (new_title or "").strip()
    if not new_title:
        return str(src)
    # 更新 JSON title（失败不阻断重命名）
    try:
        with open(src, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            data["title"] = new_title
            with open(src, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
    except (OSError, ValueError):
        pass
    # 目标文件名（重名自动加序号）
    new_path = src.with_name(new_title + src.suffix)
    n = 2
    while new_path != src and new_path.exists():
        new_path = src.with_name(f"{new_title} ({n}){src.suffix}")
        n += 1
    if new_path != src:
        os.replace(str(src), str(new_path))
    return str(new_path)


def delete_sheet(path) -> None:
    """删除乐谱文件（不存在时忽略）。"""
    try:
        os.remove(path)
    except OSError:
        pass
