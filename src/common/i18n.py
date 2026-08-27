# common/i18n.py
"""双语国际化框架 —— 根据 Blender 界面语言自动切换中文/英文。

- get_lang(): 返回 'zh' 或 'en'（带模块级缓存）
- T(key): 翻译函数，根据当前语言返回对应文本
- reset_lang(): 重置语言缓存（调试用）
- bl_label_set(cls, key): 动态设置 bl_label（用于 register() 中）
"""

import bpy  # type: ignore


def _get_language() -> str:
    """检测 Blender 当前界面语言，返回 'zh' 或 'en'。"""
    try:
        lang = getattr(bpy.context.preferences.system, 'language', '') or ''
    except Exception:
        lang = ''
    if not lang:
        # 回退：bpy.app.translations_context
        ctx = getattr(bpy.app, 'translations_context', None)
        if ctx and ctx[0]:
            lang = ctx[0]
    return 'zh' if lang.startswith('zh') else 'en'


# 模块级缓存
_lang_cache: str | None = None


def get_lang() -> str:
    """获取当前语言代码（'zh' 或 'en'），结果缓存。"""
    global _lang_cache
    if _lang_cache is None:
        _lang_cache = _get_language()
    return _lang_cache


def reset_lang():
    """重置语言缓存（调试用）。"""
    global _lang_cache
    _lang_cache = None


def T(key: str) -> str:
    """翻译函数：根据当前语言返回对应文本。

    :param key: 双语字典中的键（使用中文原文作为主键）
    :return: 当前语言的字符串；如果键不存在则返回原始 key
    """
    entry = _DICT.get(key)
    if entry is None:
        return key
    return entry.get(get_lang(), key)


def bl_label_set(cls, key: str) -> None:
    """在 register() 中动态设置 bl_label，确保注册时是翻译后的文本。

    用法：
        bpy.utils.register_class(MyPanel)
        bl_label_set(MyPanel, "原始标签")
    """
    cls.bl_label = T(key)


# ── 双语字典 ────────────────────────────────────────────────────────
# 格式：{中文原文: {"zh": "中文", "en": "English"}}
# 键统一使用中文原文（因为中文出现频率更高），值包含两种语言。

_DICT: dict[str, dict[str, str]] = {
    # ═══════════════════════════════════════════════════════════
    # 公共模块 (common/ui_utils.py)
    # ═══════════════════════════════════════════════════════════
    "无": {"zh": "无", "en": "(none)"},
    "（选择乐器）": {"zh": "（选择乐器）", "en": "(Select instrument)"},
    "角色选择器": {"zh": "角色选择器", "en": "Performer Selector"},
    "当前角色": {"zh": "当前角色", "en": "Current Performer"},
    "角色生成器": {"zh": "角色生成器", "en": "Performer Generator"},
    "新建角色": {"zh": "新建角色", "en": "New Performer"},
    "名字": {"zh": "名字", "en": "Name"},
    "乐器": {"zh": "乐器", "en": "Instrument"},
    "角色基础属性": {"zh": "角色基础属性", "en": "Basic Info"},
    "目标骨骼": {"zh": "目标骨骼", "en": "Target Skeleton"},
    "目标乐器": {"zh": "目标乐器", "en": "Target Instrument"},
    "人物信息路径": {"zh": "人物信息路径", "en": "Info Path"},
    "角色操作": {"zh": "角色操作", "en": "Performer Ops"},
    "复制当前角色": {"zh": "复制当前角色", "en": "Duplicate Current Performer"},
    "重命名当前角色": {"zh": "重命名当前角色", "en": "Rename Current Performer"},
    "工具": {"zh": "工具", "en": "Tools"},
    "（无可用工具）": {"zh": "（无可用工具）", "en": "(No tools available)"},
    "显示工具": {"zh": "显示工具", "en": "Show Tools"},
    "展开/折叠工具区": {"zh": "展开/折叠工具区", "en": "Expand/collapse tool area"},
    "当前工具": {"zh": "当前工具", "en": "Active Tool"},
    "当前选中的工具（空 = 未选择）": {
        "zh": "当前选中的工具（空 = 未选择）", "en": "Currently selected tool (empty = none)"},
    "显示角色生成器": {"zh": "显示角色生成器", "en": "Show Performer Generator"},
    "展开/折叠角色生成器区": {"zh": "展开/折叠角色生成器区", "en": "Expand/collapse generator area"},
    "显示角色操作": {"zh": "显示角色操作", "en": "Show Performer Ops"},
    "展开/折叠角色操作区（重命名/复制）": {
        "zh": "展开/折叠角色操作区（重命名/复制）",
        "en": "Expand/collapse ops area (rename/duplicate)"},
    "选择工具": {"zh": "选择工具", "en": "Select Tool"},
    "演奏者骨骼": {"zh": "演奏者骨骼", "en": "Performer Skeleton"},
    "乐器物体": {"zh": "乐器物体", "en": "Instrument Object"},
    "请选择乐器": {"zh": "请选择乐器", "en": "Please select an instrument"},
    "角色所属乐器（只列已注册乐器）": {"zh": "角色所属乐器（只列已注册乐器）", "en": "Instrument of the performer (only registered instruments)"},
    "角色名字（仅英文字母和数字，如 Ayaka / Player01）": {
        "zh": "角色名字（仅英文字母和数字，如 Ayaka / Player01）",
        "en": "Performer name (letters and digits only, e.g. Ayaka / Player01)"},
    "请输入名字": {"zh": "请输入名字", "en": "Please enter a name"},
    "名字只能使用英文字母和数字（如 Ayaka / Player01），不能包含中文": {
        "zh": "名字只能使用英文字母和数字（如 Ayaka / Player01），不能包含中文",
        "en": "Name must use English letters and digits only (e.g. Ayaka / Player01), no Chinese characters allowed"},
    "已存在名字 %s，请换一个": {"zh": "已存在名字 %s，请换一个", "en": "Name %s already exists, please choose another"},
    "已新建角色 %s，乐器=%s": {"zh": "已新建角色 %s，乐器=%s", "en": "Performer %s created, instrument=%s"},
    "当前操作的演奏者（扫描 Performers 根）": {
        "zh": "当前操作的演奏者（扫描 Performers 根）",
        "en": "Currently active performer (scanned from Performers root)"},
    "存储状态数据与演奏者设置的目标角色骨骼（Armature）": {
        "zh": "存储状态数据与演奏者设置的目标角色骨骼（Armature）",
        "en": "Target character skeleton (Armature) for saving state data and performer settings"},
    "当前演奏者的乐器物体（动画作用域）": {
        "zh": "当前演奏者的乐器物体（动画作用域）",
        "en": "Instrument object of current performer (animation scope)"},
    "人物信息保存路径（导入/导出）": {
        "zh": "人物信息保存路径（导入/导出）",
        "en": "Path to save/load performer info (import/export)"},

    # ═══════════════════════════════════════════════════════════
    # FretDance UI
    # ═══════════════════════════════════════════════════════════
    "FretDance 吉他": {"zh": "FretDance 吉他", "en": "FretDance Guitar"},
    "FretDance": {"zh": "FretDance", "en": "FretDance"},
    "初始化": {"zh": "初始化", "en": "Initialization"},
    "设置控制器与指板标记": {"zh": "设置控制器与指板标记", "en": "Setup Controllers & Fret Markers"},
    "检查状态": {"zh": "检查状态", "en": "Check Status"},
    "迁移旧场景到当前演奏者": {"zh": "迁移旧场景到当前演奏者", "en": "Migrate Legacy Scene to Current Performer"},
    "选择左手状态": {"zh": "选择左手状态", "en": "Left Hand State"},
    "选择右手状态": {"zh": "选择右手状态", "en": "Right Hand State"},
    "设置与加载": {"zh": "设置与加载", "en": "Set & Load"},
    "导入/导出人物信息": {"zh": "导入/导出人物信息", "en": "Import/Export Performer Info"},
    "导入": {"zh": "导入", "en": "Import"},
    "导出": {"zh": "导出", "en": "Export"},
    "导出到 Unreal": {"zh": "导出到 Unreal", "en": "Export to Unreal"},
    "生成动画": {"zh": "生成动画", "en": "Generate Animation"},
    "左手动画": {"zh": "左手动画", "en": "Left Hand Animation"},
    "右手动画": {"zh": "右手动画", "en": "Right Hand Animation"},
    "弦动画": {"zh": "弦动画", "en": "String Animation"},
    "吉他偏移": {"zh": "吉他偏移", "en": "Guitar Offset"},
    "一键生成全部动画": {"zh": "一键生成全部动画", "en": "Generate All Animations"},
    "Use Vibrato Bar (颤音摇杆)": {"zh": "使用颤音摇杆", "en": "Use Vibrato Bar"},
    "导出将覆盖「人物信息路径」指向的文件内容，确定继续？": {
        "zh": "导出将覆盖「人物信息路径」指向的文件内容，确定继续？",
        "en": "Export will overwrite the file at 'Info Path'. Continue?"},
    "导入将覆盖场景中的演奏者信息，确定继续？": {
        "zh": "导入将覆盖场景中的演奏者信息，确定继续？",
        "en": "Import will overwrite performer info in scene. Continue?"},
    "请先选择目标骨骼": {"zh": "请先选择目标骨骼", "en": "Please select target skeleton first"},
    "All objects have been setup": {"zh": "All objects have been setup", "en": "All objects have been setup"},
    "Check complete. See console for details.": {"zh": "检查完成，详见控制台", "en": "Check complete. See console for details."},
    "States saved to %s": {"zh": "States saved to %s", "en": "States saved to %s"},
    "States loaded from %s": {"zh": "States loaded from %s", "en": "States loaded from %s"},
    "Invalid right hand state": {"zh": "无效右手状态", "en": "Invalid right hand state"},
    "Controller info exported to %s": {"zh": "Controller info exported to %s", "en": "Controller info exported to %s"},
    "Controller info imported from %s": {"zh": "Controller info imported from %s", "en": "Controller info imported from %s"},
    "请先在「角色操作」面板中设置人物信息路径": {
        "zh": "请先在「角色操作」面板中设置人物信息路径",
        "en": "Please set Info Path in the Performer Ops panel first"},
    "Animation config file loaded successfully": {"zh": "动画配置文件加载成功", "en": "Animation config file loaded successfully"},
    "Missing keys in JSON file: %s": {"zh": "JSON 文件中缺少键：%s", "en": "Missing keys in JSON file: %s"},
    "Following files not found: %s": {"zh": "以下文件未找到：%s", "en": "Following files not found: %s"},
    "Left hand animation generation completed": {"zh": "左手动画生成完成", "en": "Left hand animation generation completed"},
    "Right hand animation generation completed": {"zh": "右手动画生成完成", "en": "Right hand animation generation completed"},
    "String animation generation completed": {"zh": "弦动画生成完成", "en": "String animation generation completed"},
    "Controller root animation generation completed": {"zh": "控制器根动画生成完成", "en": "Controller root animation generation completed"},
    "All animations generation completed": {"zh": "全部动画生成完成", "en": "All animations generation completed"},
    "No animation files found or specified": {"zh": "未找到或未指定任何动画文件", "en": "No animation files found or specified"},
    "已复制角色为 %s": {"zh": "已复制角色为 %s", "en": "Performer duplicated as %s"},
    "已存在名字 %s，请换一个": {"zh": "已存在名字 %s，请换一个", "en": "Name %s already exists, please choose another"},
    "找不到已登记的角色 %s（请先初始化该角色）": {
        "zh": "找不到已登记的角色 %s（请先初始化该角色）",
        "en": "Registered performer %s not found (please initialize it first)"},
    "复制集合失败: %s": {"zh": "复制集合失败: %s", "en": "Failed to duplicate collection: %s"},
    "复制集合失败（未能生成副本）": {"zh": "复制集合失败（未能生成副本）", "en": "Failed to duplicate collection (no copy generated)"},
    "重命名完成，但重建驱动失败: %s": {"zh": "重命名完成，但重建驱动失败: %s", "en": "Rename completed but driver rebuild failed: %s"},
    "已将角色重命名为 %s": {"zh": "已将角色重命名为 %s", "en": "Performer renamed to %s"},
    "新名字与当前相同（%s），无需重命名": {"zh": "新名字与当前相同（%s），无需重命名", "en": "New name is same as current (%s), no rename needed"},
    "迁移旧场景到当前演奏者": {"zh": "迁移旧场景到当前演奏者", "en": "Migrate Legacy Scene to Current Performer"},
    "迁移完成：演奏者 %s (%s)，详见控制台": {"zh": "迁移完成：演奏者 %s (%s)，详见控制台", "en": "Migration complete: performer %s (%s), see console for details"},
    "迁移失败，详见控制台": {"zh": "迁移失败，详见控制台", "en": "Migration failed, see console for details"},
    "请先输入演奏者后缀": {"zh": "请先输入演奏者后缀", "en": "Please enter performer suffix first"},
    "已存在后缀 %s 的演奏者，请换一个后缀": {"zh": "已存在后缀 %s 的演奏者，请换一个后缀", "en": "Performer with suffix %s already exists, please use another"},
    "请先选中/指定目标骨骼": {"zh": "请先选中/指定目标骨骼", "en": "Please select/specify target skeleton first"},
    "找不到当前角色（请先在下拉框选中，或指定其骨骼/乐器）": {
        "zh": "找不到当前角色（请先在下拉框选中，或指定其骨骼/乐器）",
        "en": "Cannot find current performer (please select from dropdown or specify its skeleton/instrument)"},
    "请先在下拉框选中要复制的角色": {
        "zh": "请先在下拉框选中要复制的角色",
        "en": "Please select a performer to duplicate from the dropdown first"},
    "请输入新名字": {"zh": "请输入新名字", "en": "Please enter new name"},
    "Finger Style Guitar": {"zh": "指弹吉他", "en": "Finger Style Guitar"},
    "Finger style guitar": {"zh": "指弹吉他", "en": "Finger style guitar"},
    "Electric Guitar": {"zh": "电吉他", "en": "Electric Guitar"},
    "Electric guitar": {"zh": "电吉他", "en": "Electric guitar"},
    "Bass": {"zh": "贝斯", "en": "Bass"},
    "Bass guitar": {"zh": "贝斯吉他", "en": "Bass guitar"},
    "Position 0": {"zh": "位置 0", "en": "Position 0"},
    "Position 1": {"zh": "位置 1", "en": "Position 1"},
    "Position 2": {"zh": "位置 2", "en": "Position 2"},
    "Position 3": {"zh": "位置 3", "en": "Position 3"},
    "Position 4": {"zh": "位置 4", "en": "Position 4"},
    "Normal state": {"zh": "正常状态", "en": "Normal state"},
    "Outer state": {"zh": "外侧状态", "en": "Outer state"},
    "Barre state": {"zh": "横按状态", "en": "Barre state"},
    "Inner state": {"zh": "内侧状态", "en": "Inner state"},
    "Low position": {"zh": "低位", "en": "Low position"},
    "End position": {"zh": "末端位置", "en": "End position"},
    "High position": {"zh": "高位", "en": "High position"},
    "Vibrato bar release": {"zh": "颤音摇杆释放", "en": "Vibrato bar release"},
    "Vibrato bar up": {"zh": "颤音摇杆上推", "en": "Vibrato bar up"},
    "Vibrato bar down": {"zh": "颤音摇杆下压", "en": "Vibrato bar down"},
    "Enable vibrato bar (颤音摇杆) for electric guitar": {
        "zh": "电吉他启用颤音摇杆", "en": "Enable vibrato bar for electric guitar"},
    "Animation Config File": {"zh": "动画配置文件", "en": "Animation Config File"},
    "Path to animation configuration JSON file": {"zh": "动画配置 JSON 文件路径", "en": "Path to animation configuration JSON file"},
    "The index number of the string": {"zh": "弦的索引号", "en": "The index number of the string"},
    "振幅与弦长的千分比": {"zh": "振幅与弦长的千分比", "en": "Amplitude as per mille of string length"},
    "目标Mesh": {"zh": "目标Mesh", "en": "Target Mesh"},
    "存储控制器状态数据的目标角色 Mesh（旧字段，兼容保留）": {
        "zh": "存储控制器状态数据的目标角色 Mesh（旧字段，兼容保留）",
        "en": "Target character Mesh for controller state data (legacy field, kept for compatibility)"},
    "Controller Data": {"zh": "控制器数据", "en": "Controller Data"},
    "JSON: 所有控制器状态数据（左手各位置、右手各位置、指板位置、其他设置）": {
        "zh": "JSON: 所有控制器状态数据（左手各位置、右手各位置、指板位置、其他设置）",
        "en": "JSON: All controller state data (left hand positions, right hand positions, fretboard positions, other settings)"},
    "设置失败：未找到角色 addons 目录，请先在「角色选择器」新建角色（初始化角色）": {
        "zh": "设置失败：未找到角色 addons 目录，请先在「角色选择器」新建角色（初始化角色）",
        "en": "Setup failed: character addons directory not found, please create a new performer in Performer Selector first"},

    # ═══════════════════════════════════════════════════════════
    # KeyRipple UI
    # ═══════════════════════════════════════════════════════════
    "KeyRipple": {"zh": "KeyRipple", "en": "KeyRipple"},
    "KeyRipple 钢琴": {"zh": "KeyRipple 钢琴", "en": "KeyRipple Piano"},
    "Finger Number": {"zh": "手指数量", "en": "Finger Number"},
    "Number of fingers per hand": {"zh": "每只手的手指数量", "en": "Number of fingers per hand"},
    "Leftest Position": {"zh": "最左位置", "en": "Leftest Position"},
    "Leftmost position": {"zh": "最左侧位置", "en": "Leftmost position"},
    "Left Position": {"zh": "左位置", "en": "Left Position"},
    "Left position": {"zh": "左侧位置", "en": "Left position"},
    "Middle Left Position": {"zh": "中左位置", "en": "Middle Left Position"},
    "Middle left position": {"zh": "中左侧位置", "en": "Middle left position"},
    "Middle Right Position": {"zh": "中右位置", "en": "Middle Right Position"},
    "Middle right position": {"zh": "中右侧位置", "en": "Middle right position"},
    "Right Position": {"zh": "右位置", "en": "Right Position"},
    "Right position": {"zh": "右侧位置", "en": "Right position"},
    "Rightest Position": {"zh": "最右位置", "en": "Rightest Position"},
    "Rightmost position": {"zh": "最右侧位置", "en": "Rightmost position"},
    "Min Key": {"zh": "最低键位", "en": "Min Key"},
    "Lowest key on the piano": {"zh": "钢琴最低键位", "en": "Lowest key on the piano"},
    "Max Key": {"zh": "最高键位", "en": "Max Key"},
    "Highest key on the piano": {"zh": "钢琴最高键位", "en": "Highest key on the piano"},
    "Hand Range": {"zh": "手范围", "en": "Hand Range"},
    "the range of hand": {"zh": "手的跨度范围", "en": "the range of hand"},
    "Left Hand Key Type": {"zh": "左手键类型", "en": "Left Hand Key Type"},
    "Key type for left hand": {"zh": "左手使用的键类型", "en": "Key type for left hand"},
    "White Key": {"zh": "白键", "en": "White Key"},
    "White key": {"zh": "白键", "en": "White key"},
    "Black Key": {"zh": "黑键", "en": "Black Key"},
    "Black key": {"zh": "黑键", "en": "Black key"},
    "Left Hand Position Type": {"zh": "左手位置类型", "en": "Left Hand Position Type"},
    "Position type for left hand": {"zh": "左手位置类型", "en": "Position type for left hand"},
    "Right Hand Key Type": {"zh": "右手键类型", "en": "Right Hand Key Type"},
    "Key type for right hand": {"zh": "右手使用的键类型", "en": "Key type for right hand"},
    "Right Hand Position Type": {"zh": "右手位置类型", "en": "Right Hand Position Type"},
    "Position type for right hand": {"zh": "右手位置类型", "en": "Position type for right hand"},
    "KeyRipple File": {"zh": "KeyRipple 文件", "en": "KeyRipple File"},
    "Path to .keyripple file": {"zh": ".keyripple 文件路径", "en": "Path to .keyripple file"},
    "Check Objects Status": {"zh": "检查对象状态", "en": "Check Objects Status"},
    "Check the status of all KeyRipple objects": {"zh": "检查所有 KeyRipple 对象的状态", "en": "Check the status of all KeyRipple objects"},
    "Setup All Objects": {"zh": "设置所有对象", "en": "Setup All Objects"},
    "Create all KeyRipple controllers": {"zh": "创建所有 KeyRipple 控制器", "en": "Create all KeyRipple controllers"},
    "Save State": {"zh": "保存状态", "en": "Save State"},
    "Save all controller states to performer skeleton custom properties": {
        "zh": "将所有控制器状态保存到演奏者骨骼自定义属性",
        "en": "Save all controller states to performer skeleton custom properties"},
    "Load State": {"zh": "加载状态", "en": "Load State"},
    "Load hand states from performer skeleton custom properties": {
        "zh": "从演奏者骨骼自定义属性加载手部状态",
        "en": "Load hand states from performer skeleton custom properties"},
    "Export Avatar": {"zh": "导出头像", "en": "Export Avatar"},
    "Export avatar to .avatar file": {"zh": "导出头像到 .avatar 文件", "en": "Export avatar to .avatar file"},
    "Import Avatar": {"zh": "导入头像", "en": "Import Avatar"},
    "Import avatar from .avatar file": {"zh": "从 .avatar 文件导入头像", "en": "Import avatar from .avatar file"},
    "Generate Animation": {"zh": "生成动画", "en": "Generate Animation"},
    "Generate KeyRipple animation from .keyripple file": {
        "zh": "从 .keyripple 文件生成 KeyRipple 动画",
        "en": "Generate KeyRipple animation from .keyripple file"},
    "复制角色": {"zh": "复制角色", "en": "Duplicate Performer"},
    "新名字": {"zh": "新名字", "en": "New Name"},
    "Avatar exported to %s": {"zh": "头像已导出到 %s", "en": "Avatar exported to %s"},
    "Avatar imported from %s": {"zh": "头像已从 %s 导入", "en": "Avatar imported from %s"},
    "KeyRipple animation generated from %s": {"zh": "KeyRipple 动画已从 %s 生成", "en": "KeyRipple animation generated from %s"},
    "状态已保存: 左%s/%s 右%s/%s": {"zh": "状态已保存: 左%s/%s 右%s/%s", "en": "State saved: L%s/%s R%s/%s"},

    # ═══════════════════════════════════════════════════════════
    # StringFlow UI
    # ═══════════════════════════════════════════════════════════
    "StringFlow": {"zh": "StringFlow", "en": "StringFlow"},
    "StringFlow 提琴": {"zh": "StringFlow 提琴", "en": "StringFlow Strings"},
    "乐器类型": {"zh": "乐器类型", "en": "Instrument Type"},
    "Left Hand State": {"zh": "左手状态", "en": "Left Hand State"},
    "Right Hand State": {"zh": "右手状态", "en": "Right Hand State"},
    "Hand State Transfer": {"zh": "手部状态传输", "en": "Hand State Transfer"},
    "Recorder Info I/O": {"zh": "记录器信息 I/O", "en": "Recorder Info I/O"},
    "Recorder Info Export": {"zh": "记录器信息导出", "en": "Recorder Info Export"},
    "Recorder Info Import": {"zh": "记录器信息导入", "en": "Recorder Info Import"},
    "String Flow File": {"zh": "StringFlow 文件", "en": "String Flow File"},
    "Path to .string_flow file（Rust 生成的动画配置文件）": {
        "zh": "Path to .string_flow file（Rust 生成的动画配置文件）",
        "en": "Path to .string_flow file (animation config generated by Rust)"},
    "Finger Number": {"zh": "手指数量", "en": "Finger Number"},
    "Number of fingers per hand（可调，外星人多指预留）": {
        "zh": "Number of fingers per hand (adjustable, reserved for multi-finger aliens)",
        "en": "Number of fingers per hand (adjustable, reserved for multi-finger aliens)"},
    "String Number": {"zh": "弦数量", "en": "String Number"},
    "Number of strings（小提琴固定 4 根）": {
        "zh": "Number of strings (violin fixed at 4)",
        "en": "Number of strings (violin fixed at 4)"},
    "Left Hand Position Type": {"zh": "左手位置类型", "en": "Left Hand Position Type"},
    "Position type for left hand": {"zh": "左手位置类型", "en": "Position type for left hand"},
    "Left Hand String": {"zh": "左手弦", "en": "Left Hand String"},
    "String index for left hand": {"zh": "左手使用的弦索引", "en": "String index for left hand"},
    "Left Hand Fret": {"zh": "左手品格", "en": "Left Hand Fret"},
    "Fret index for left hand": {"zh": "左手使用的品格索引", "en": "Fret index for left hand"},
    "Right Hand Position Type": {"zh": "右手位置类型", "en": "Right Hand Position Type"},
    "Position type for right hand": {"zh": "右手位置类型", "en": "Position type for right hand"},
    "Right Hand String": {"zh": "右手弦", "en": "Right Hand String"},
    "String index for right hand": {"zh": "右手使用的弦索引", "en": "String index for right hand"},
    "已复制角色为 %s": {"zh": "已复制角色为 %s", "en": "Performer duplicated as %s"},
    "已存在名字 %s，请换一个": {"zh": "已存在名字 %s，请换一个", "en": "Name %s already exists, please choose another"},
    "找不到已登记的角色 %s（请先初始化该角色）": {
        "zh": "找不到已登记的角色 %s（请先初始化该角色）",
        "en": "Registered performer %s not found (please initialize it first)"},
    "复制集合失败: %s": {"zh": "复制集合失败: %s", "en": "Failed to duplicate collection: %s"},
    "复制集合失败（未能生成副本）": {"zh": "复制集合失败（未能生成副本）", "en": "Failed to duplicate collection (no copy generated)"},
    "已将角色重命名为 %s": {"zh": "已将角色重命名为 %s", "en": "Performer renamed to %s"},
    "新名字与当前相同（%s），无需重命名": {"zh": "新名字与当前相同（%s），无需重命名", "en": "New name is same as current (%s), no rename needed"},
    # StringFlow instrument items
    "小提琴": {"zh": "小提琴", "en": "Violin"},
    "中提琴": {"zh": "中提琴", "en": "Viola"},
    "大提琴": {"zh": "大提琴", "en": "Cello"},
    "Violin（空弦 E4=76 / A3=69 / D3=62 / G3=55）": {
        "zh": "Violin（空弦 E4=76 / A3=69 / D3=62 / G3=55）",
        "en": "Violin (open strings E4=76 / A3=69 / D3=62 / G3=55)"},
    "Viola（空弦 A3=69 / D3=62 / G3=55 / C3=48）": {
        "zh": "Viola（空弦 A3=69 / D3=62 / G3=55 / C3=48）",
        "en": "Viola (open strings A3=69 / D3=62 / G3=55 / C3=48)"},
    "Cello（空弦 A2=45 / D2=38 / G2=31 / C2=24）": {
        "zh": "Cello（空弦 A2=45 / D2=38 / G2=31 / C2=24）",
        "en": "Cello (open strings A2=45 / D2=38 / G2=31 / C2=24)"},
    # StringFlow enum items (Normal/Inner/Outer)
    "Normal": {"zh": "正常", "en": "Normal"},
    "Normal position": {"zh": "正常位置", "en": "Normal position"},
    "Inner": {"zh": "内侧", "en": "Inner"},
    "Inner position": {"zh": "内侧位置", "en": "Inner position"},
    "Outer": {"zh": "外侧", "en": "Outer"},
    "Outer position": {"zh": "外侧位置", "en": "Outer position"},
    # StringFlow enum items (Near/Far/Pizzicato)
    "Near": {"zh": "近侧", "en": "Near"},
    "Near position": {"zh": "近侧位置", "en": "Near position"},
    "Far": {"zh": "远侧", "en": "Far"},
    "Far position": {"zh": "远侧位置", "en": "Far position"},
    "Pizzicato": {"zh": "拨奏", "en": "Pizzicato"},
    "Pizzicato position": {"zh": "拨奏位置", "en": "Pizzicato position"},
    # StringFlow string/fret enum items
    "String 0": {"zh": "弦 0", "en": "String 0"},
    "String 1": {"zh": "弦 1", "en": "String 1"},
    "String 2": {"zh": "弦 2", "en": "String 2"},
    "String 3": {"zh": "弦 3", "en": "String 3"},
    "Fret 1": {"zh": "品格 1", "en": "Fret 1"},
    "Fret 9": {"zh": "品格 9", "en": "Fret 9"},
    "Fret 12": {"zh": "品格 12", "en": "Fret 12"},
    # StringFlow report messages
    "No animations were generated successfully": {
        "zh": "没有动画生成成功",
        "en": "No animations were generated successfully"},
    "请先在下拉框选中要复制的角色": {
        "zh": "请先在下拉框选中要复制的角色",
        "en": "Please select a performer from the dropdown to duplicate"},
    # StringFlow section labels used in panel draw
    "初始化": {"zh": "初始化", "en": "Initialization"},
    "Recorder Info I/O": {"zh": "记录器信息 I/O", "en": "Recorder Info I/O"},
    "生成动画": {"zh": "生成动画", "en": "Generate Animation"},
    "左手动画": {"zh": "左手动画", "en": "Left Hand Animation"},
    "右手动画": {"zh": "右手动画", "en": "Right Hand Animation"},
    "弦动画": {"zh": "弦动画", "en": "String Animation"},
    "一键生成全部动画": {"zh": "一键生成全部动画", "en": "Generate All Animations"},
    "导出": {"zh": "导出", "en": "Export"},
    "导入": {"zh": "导入", "en": "Import"},
    "导出到 Unreal": {"zh": "导出到 Unreal", "en": "Export to Unreal"},

    # ═══════════════════════════════════════════════════════════
    # ZhengDrift UI
    # ═══════════════════════════════════════════════════════════
    "ZhengDrift": {"zh": "ZhengDrift", "en": "ZhengDrift"},
    "ZhengDrift 古筝": {"zh": "ZhengDrift 古筝", "en": "ZhengDrift Zheng"},
    "选择左手状态": {"zh": "选择左手状态", "en": "Left Hand State"},
    "选择右手状态": {"zh": "选择右手状态", "en": "Right Hand State"},
    "设置与加载": {"zh": "设置与加载", "en": "Set & Load"},
    "导入/导出标准姿势": {"zh": "导入/导出标准姿势", "en": "Import/Export Standard Pose"},
    "Save Left Hand": {"zh": "保存左手", "en": "Save Left Hand"},
    "Save Right Hand": {"zh": "保存右手", "en": "Save Right Hand"},
    "Load Left Hand": {"zh": "加载左手", "en": "Load Left Hand"},
    "Load Right Hand": {"zh": "加载右手", "en": "Load Right Hand"},
    "导出控制器信息": {"zh": "导出控制器信息", "en": "Export Controller Info"},
    "导入控制器信息": {"zh": "导入控制器信息", "en": "Import Controller Info"},
    "生成左手动画": {"zh": "生成左手动画", "en": "Generate Left Hand Animation"},
    "生成右手动画": {"zh": "生成右手动画", "en": "Generate Right Hand Animation"},
    "生成弦振动动画": {"zh": "生成弦振动动画", "en": "Generate String Vibration Animation"},
    "一键生成全部动画": {"zh": "一键生成全部动画", "en": "Generate All Animations"},
    "复制角色": {"zh": "复制角色", "en": "Duplicate Performer"},
    "重命名当前角色": {"zh": "重命名当前角色", "en": "Rename Current Performer"},
    "新名字": {"zh": "新名字", "en": "New Name"},
    "位置": {"zh": "位置", "en": "Position"},
    "选择左手演奏位置": {"zh": "选择左手演奏位置", "en": "Select left hand playing position"},
    "动作": {"zh": "动作", "en": "Action"},
    "选择左手动作类型": {"zh": "选择左手动作类型", "en": "Select left hand action type"},
    "选择右手演奏位置": {"zh": "选择右手演奏位置", "en": "Select right hand playing position"},
    "选择右手动作类型": {"zh": "选择右手动作类型", "en": "Select right hand action type"},
    "动画文件": {"zh": "动画文件", "en": "Animation File"},
    "动画配置文件路径（.zhengdrift）或手部动画文件路径": {
        "zh": "动画配置文件路径（.zhengdrift）或手部动画文件路径",
        "en": "Animation config path (.zhengdrift) or hand animation file path"},

    # ═══════════════════════════════════════════════════════════
    # HarpGlide UI
    # ═══════════════════════════════════════════════════════════
    "Harp Glide": {"zh": "Harp Glide", "en": "Harp Glide"},
    "HarpGlide 竖琴": {"zh": "HarpGlide 竖琴", "en": "HarpGlide Harp"},
    "竖琴设置": {"zh": "竖琴设置", "en": "Harp Settings"},
    "弦数": {"zh": "弦数", "en": "String Count"},
    "左远": {"zh": "左远", "en": "Left Far"},
    "左近": {"zh": "左近", "en": "Left Near"},
    "左中远": {"zh": "左中远", "en": "Left Mid-Far"},
    "左中近": {"zh": "左中近", "en": "Left Mid-Near"},
    "右远": {"zh": "右远", "en": "Right Far"},
    "右近": {"zh": "右近", "en": "Right Near"},
    "保存配置到骨骼": {"zh": "保存配置到骨骼", "en": "Save Config to Skeleton"},
    "初始化": {"zh": "初始化", "en": "Initialization"},
    "Setup Objects": {"zh": "设置对象", "en": "Setup Objects"},
    "状态设置": {"zh": "状态设置", "en": "State Settings"},
    "手部 + 头部姿势": {"zh": "手部 + 头部姿势", "en": "Hand + Head Pose"},
    "手": {"zh": "手", "en": "Hand"},
    "状态": {"zh": "状态", "en": "State"},
    "踏板（D/C/B→左脚，E/F/G/A→右脚）": {"zh": "踏板（D/C/B→左脚，E/F/G/A→右脚）", "en": "Pedal (D/C/B → left foot, E/F/G/A → right foot)"},
    "唱名": {"zh": "唱名", "en": "Note Name"},
    "位置": {"zh": "位置", "en": "Position"},
    "竖琴倾斜状态": {"zh": "竖琴倾斜状态", "en": "Harp Tilt State"},
    "脚部休息位置": {"zh": "脚部休息位置", "en": "Foot Rest Position"},
    "数据文件 (.harpist)": {"zh": "数据文件 (.harpist)", "en": "Data File (.harpist)"},
    "Export .harpist": {"zh": "导出 .harpist", "en": "Export .harpist"},
    "Import .harpist": {"zh": "导入 .harpist", "en": "Import .harpist"},
    "生成动画": {"zh": "生成动画", "en": "Generate Animation"},
    "演奏者动画": {"zh": "演奏者动画", "en": "Performer Animation"},
    "乐器动画": {"zh": "乐器动画", "en": "Instrument Animation"},
    "一键生成所有动画": {"zh": "一键生成所有动画", "en": "Generate All Animations"},
    "生成弦 Shape Key": {"zh": "生成弦 Shape Key", "en": "Generate String Shape Key"},
    "批量生成所有弦 Shape Key": {"zh": "批量生成所有弦 Shape Key", "en": "Batch Generate All String Shape Keys"},
    "线性分布弦位置": {"zh": "线性分布弦位置", "en": "Linear String Distribution"},
    "复制角色": {"zh": "复制角色", "en": "Duplicate Performer"},
    "重命名当前角色": {"zh": "重命名当前角色", "en": "Rename Current Performer"},
    "新名字": {"zh": "新名字", "en": "New Name"},
    "选中两端 Empty，中间弦标记将线性分布": {
        "zh": "选中两端 Empty，中间弦标记将线性分布",
        "en": "Select two end Empty objects; intermediate string markers will be distributed linearly"},

    # ═══════════════════════════════════════════════════════════
    # WindRise UI
    # ═══════════════════════════════════════════════════════════
    "Wind Rise": {"zh": "Wind Rise", "en": "Wind Rise"},
    "WindRise 吹奏": {"zh": "WindRise 吹奏", "en": "WindRise Wind"},
    "初始化": {"zh": "初始化", "en": "Initialization"},
    "Setup Objects": {"zh": "设置对象", "en": "Setup Objects"},
    "对象选择": {"zh": "对象选择", "en": "Object Selection"},
    "人物Mesh": {"zh": "人物Mesh", "en": "Character Mesh"},
    "乐器: （未设置，请在「角色操作」选择目标乐器）": {
        "zh": "乐器: （未设置，请在「角色操作」选择目标乐器）",
        "en": "Instrument: (not set, please select target instrument in Performer Ops)"},
    "人物 Shape Key（嘴唇）": {"zh": "人物 Shape Key（嘴唇）", "en": "Character Shape Key (Lips)"},
    "乐器 Shape Key": {"zh": "乐器 Shape Key", "en": "Instrument Shape Key"},
    "乐器说明": {"zh": "乐器说明", "en": "Instrument Description"},
    "添加": {"zh": "添加", "en": "Add"},
    "（尚未添加 Shape Key）": {"zh": "（尚未添加 Shape Key）", "en": "(No Shape Keys added yet)"},
    "状态管理": {"zh": "状态管理", "en": "State Management"},
    "当前音高": {"zh": "当前音高", "en": "Current Note"},
    "保存状态": {"zh": "保存状态", "en": "Save State"},
    "加载状态": {"zh": "加载状态", "en": "Load State"},
    "数据文件 (.wind)": {"zh": "数据文件 (.wind)", "en": "Data File (.wind)"},
    "乐器类型": {"zh": "乐器类型", "en": "Instrument Type"},
    "自定义类型": {"zh": "自定义类型", "en": "Custom Type"},
    "最小": {"zh": "最小", "en": "Min"},
    "最大": {"zh": "最大", "en": "Max"},
    "导出 .wind": {"zh": "导出 .wind", "en": "Export .wind"},
    "导入 .wind": {"zh": "导入 .wind", "en": "Import .wind"},
    "导出到 Unreal": {"zh": "导出到 Unreal", "en": "Export to Unreal"},
    "生成动画": {"zh": "生成动画", "en": "Generate Animation"},
    "请先选择含 Shape Key 的 Mesh": {"zh": "请先选择含 Shape Key 的 Mesh", "en": "Please select a Mesh with Shape Keys first"},
    "重置旋转": {"zh": "重置旋转", "en": "Reset Rotation"},
    "重置移动": {"zh": "重置移动", "en": "Reset Translation"},
    "物体1": {"zh": "物体1", "en": "Object 1"},
    "物体2": {"zh": "物体2", "en": "Object 2"},
    "角度": {"zh": "角度", "en": "Angle"},
    "距离": {"zh": "距离", "en": "Distance"},
    "物体2（旋转轴终点）": {"zh": "物体2（旋转轴终点）", "en": "Object 2 (rotation axis endpoint)"},
    "物体2（移动方向终点）": {"zh": "物体2（移动方向终点）", "en": "Object 2 (translation direction endpoint)"},
    # WindRise report messages
    "WindRise 控件已就绪": {"zh": "WindRise 控件已就绪", "en": "WindRise controls ready"},
    "请先在「角色生成器」初始化角色": {
        "zh": "请先在「角色生成器」初始化角色",
        "en": "Please initialize the character in 'Performer Generator' first"},
    "音高 %s 保存完成": {"zh": "音高 %s 保存完成", "en": "Note %s saved"},
    "保存失败: %s": {"zh": "保存失败: %s", "en": "Save failed: %s"},
    "音高 %s 加载完成": {"zh": "音高 %s 加载完成", "en": "Note %s loaded"},
    "加载失败: %s": {"zh": "加载失败: %s", "en": "Load failed: %s"},
    "导出完成: %s": {"zh": "导出完成: %s", "en": "Export complete: %s"},
    "导出失败: %s": {"zh": "导出失败: %s", "en": "Export failed: %s"},
    "文件不存在: %s": {"zh": "文件不存在: %s", "en": "File not found: %s"},
    "导入完成": {"zh": "导入完成", "en": "Import complete"},
    "导入失败: %s": {"zh": "导入失败: %s", "en": "Import failed: %s"},
    "请先选择 .wind_rise 文件": {"zh": "请先选择 .wind_rise 文件", "en": "Please select a .wind_rise file first"},
    "选择的文件不是 .wind_rise 文件": {"zh": "选择的文件不是 .wind_rise 文件", "en": "Selected file is not a .wind_rise file"},
    "动画生成完成": {"zh": "动画生成完成", "en": "Animation generation complete"},
    "动画生成失败: %s": {"zh": "动画生成失败: %s", "en": "Animation generation failed: %s"},
    "请从下拉菜单选择一个 Shape Key": {
        "zh": "请从下拉菜单选择一个 Shape Key",
        "en": "Please select a Shape Key from the dropdown menu"},
    "找不到当前角色": {"zh": "找不到当前角色", "en": "Cannot find current performer"},
    "名字只能用英文字母和数字": {"zh": "名字只能用英文字母和数字", "en": "Name can only use English letters and digits"},
    "新名字与当前相同": {"zh": "新名字与当前相同", "en": "New name is same as current"},
    "已存在名字 %s": {"zh": "已存在名字 %s", "en": "Name %s already exists"},
    "重命名失败：%s": {"zh": "重命名失败：%s", "en": "Rename failed: %s"},
    "已重命名为 %s": {"zh": "已重命名为 %s", "en": "Renamed to %s"},
    "请先选中要复制的角色": {"zh": "请先选中要复制的角色", "en": "Please select the performer to duplicate first"},
    "找不到角色 %s": {"zh": "找不到角色 %s", "en": "Performer %s not found"},
    "复制失败：%s": {"zh": "复制失败：%s", "en": "Duplicate failed: %s"},
    "复制集合失败": {"zh": "复制集合失败", "en": "Failed to duplicate collection"},
    "已复制为 %s": {"zh": "已复制为 %s", "en": "Duplicated as %s"},
    # WindRise PropertyGroup properties
    "新人物 SK": {"zh": "新人物 SK", "en": "New Character SK"},
    "从人物 Mesh 选择要添加的 Shape Key": {
        "zh": "从人物 Mesh 选择要添加的 Shape Key",
        "en": "Select a Shape Key to add from character Mesh"},
    "新乐器 SK": {"zh": "新乐器 SK", "en": "New Instrument SK"},
    "从乐器 Mesh 选择要添加的 Shape Key": {
        "zh": "从乐器 Mesh 选择要添加的 Shape Key",
        "en": "Select a Shape Key to add from instrument Mesh"},
    "自定义乐器类型": {"zh": "自定义乐器类型", "en": "Custom Instrument Type"},
    "自定义乐器类型名称": {"zh": "自定义乐器类型名称", "en": "Custom instrument type name"},
    "最小音高": {"zh": "最小音高", "en": "Min Note"},
    "最大音高": {"zh": "最大音高", "en": "Max Note"},
    ".wind_rise 文件": {"zh": ".wind_rise 文件", "en": ".wind_rise File"},
    "动画汇总 .wind_rise 文件路径": {
        "zh": "动画汇总 .wind_rise 文件路径",
        "en": "Path to animation summary .wind_rise file"},
    "包含嘴唇 Shape Key 的角色网格": {
        "zh": "包含嘴唇 Shape Key 的角色网格",
        "en": "Character mesh containing lip Shape Keys"},
    "指法说明 / 乐器描述（自由文本）": {
        "zh": "指法说明 / 乐器描述（自由文本）",
        "en": "Fingering instructions / instrument description (free text)"},
    "当前正在编辑的 MIDI 音符号": {
        "zh": "当前正在编辑的 MIDI 音符号",
        "en": "MIDI note currently being edited"},
    "导出到 .wind 的 instrument_type": {
        "zh": "导出到 .wind 的 instrument_type",
        "en": "instrument_type for .wind export"},
    "显示人物 Shape Key": {"zh": "显示人物 Shape Key", "en": "Show Character Shape Key"},
    "显示乐器 Shape Key": {"zh": "显示乐器 Shape Key", "en": "Show Instrument Shape Key"},
    "展开/折叠 Shape Key 区": {"zh": "展开/折叠 Shape Key 区", "en": "Expand/collapse Shape Key area"},
    # WindRise MIDI note items
    "MIDI 音高 %s": {"zh": "MIDI 音高 %s", "en": "MIDI note %s"},

    # ═══════════════════════════════════════════════════════════
    # BeatBloom UI
    # ═══════════════════════════════════════════════════════════
    "BeatBloom": {"zh": "BeatBloom", "en": "BeatBloom"},
    "BeatBloom 打击乐": {"zh": "BeatBloom 打击乐", "en": "BeatBloom Percussion"},
    "DrumKit Config": {"zh": "鼓组配置", "en": "DrumKit Config"},
    "Load DrumKit Config": {"zh": "加载鼓组配置", "en": "Load DrumKit Config"},
    "Initialization": {"zh": "初始化", "en": "Initialization"},
    "Setup Objects": {"zh": "设置对象", "en": "Setup Objects"},
    "Set / Load State": {"zh": "设置/加载状态", "en": "Set / Load State"},
    "Component": {"zh": "组件", "en": "Component"},
    "State": {"zh": "状态", "en": "State"},
    "Hit state": {"zh": "击打状态", "en": "Hit state"},
    "Mapping Helpers": {"zh": "映射辅助", "en": "Mapping Helpers"},
    "Slot": {"zh": "槽位", "en": "Slot"},
    "Mapping State": {"zh": "映射状态", "en": "Mapping State"},
    "Mapping helper slot (A/B/C/D)": {"zh": "Mapping helper 槽位 (A/B/C/D)", "en": "Mapping helper slot (A/B/C/D)"},
    "Save Mapping": {"zh": "保存映射", "en": "Save Mapping"},
    "Load Mapping": {"zh": "加载映射", "en": "Load Mapping"},
    "Export / Import": {"zh": "导出/导入", "en": "Export / Import"},
    "Export .drummer": {"zh": "导出 .drummer", "en": "Export .drummer"},
    "Import .drummer": {"zh": "导入 .drummer", "en": "Import .drummer"},
    "Animation": {"zh": "动画", "en": "Animation"},
    "Execute Animation": {"zh": "执行动画", "en": "Execute Animation"},
    "复制角色": {"zh": "复制角色", "en": "Duplicate Performer"},
    "重命名当前角色": {"zh": "重命名当前角色", "en": "Rename Current Performer"},
    "新名字": {"zh": "新名字", "en": "New Name"},

    # ═══════════════════════════════════════════════════════════
    # 公共工具 (common/tools/)
    # ═══════════════════════════════════════════════════════════
    "修正手指骨骼": {"zh": "修正手指骨骼", "en": "Fix Finger Bones"},
    "提示：请先选择一个参照物体，再选中一段手指骨骼链": {
        "zh": "提示：请先选择一个参照物体，再选中一段手指骨骼链",
        "en": "Tip: First select a reference object, then select a finger bone chain"},
    "① 物体模式：先选「参照物」，再选「骨架」为活动对象": {
        "zh": "① 物体模式：先选「参照物」，再选「骨架」为活动对象",
        "en": "① Object Mode: Select 'Reference' first, then select 'Skeleton' as active object"},
    "② 进入编辑模式，选中手指骨骼链的「根骨骼」": {
        "zh": "② 进入编辑模式，选中手指骨骼链的「根骨骼」",
        "en": "② Enter Edit Mode, select the 'root bone' of the finger bone chain"},
    "③ 点击下方按钮执行": {
        "zh": "③ 点击下方按钮执行",
        "en": "③ Click the button below to execute"},
    "骨骼/控制器映射": {"zh": "骨骼/控制器映射", "en": "Bone/Controller Mapping"},
    "提示：自动使用当前演奏者的目标骨骼；添加映射（骨骼 → 控制器）后同步/导出": {
        "zh": "提示：自动使用当前演奏者的目标骨骼；添加映射（骨骼 → 控制器）后同步/导出",
        "en": "Tip: Automatically uses the current performer's target skeleton; sync/export after adding mappings (bone → controller)"},
    "警告：请先在「角色选择器」中选中演奏者并设置目标骨骼": {
        "zh": "警告：请先在「角色选择器」中选中演奏者并设置目标骨骼",
        "en": "Warning: Please select a performer in Performer Selector and set target skeleton first"},
    "添加": {"zh": "添加", "en": "Add"},
    "同步": {"zh": "同步", "en": "Sync"},
    "导出": {"zh": "导出", "en": "Export"},
    "导入": {"zh": "导入", "en": "Import"},
    "未初始化映射集合": {"zh": "未初始化映射集合", "en": "Uninitialized mapping collection"},
    "骨骼": {"zh": "骨骼", "en": "Bone"},
    "控制器": {"zh": "控制器", "en": "Controller"},
    "删除映射项": {"zh": "删除映射项", "en": "Delete Mapping Item"},
    "浏览文件": {"zh": "浏览文件", "en": "Browse File"},
    "骨骼控制器映射": {"zh": "骨骼控制器映射", "en": "Bone Controller Mapping"},
    "映射文件的保存/加载路径": {"zh": "映射文件的保存/加载路径", "en": "Save/load path for mapping file"},
    "显示骨骼映射": {"zh": "显示骨骼映射", "en": "Show Bone Mapping"},
    "展开/折叠骨骼控制器映射模块": {"zh": "展开/折叠骨骼控制器映射模块", "en": "Expand/collapse bone controller mapping module"},

    # ═══════════════════════════════════════════════════════════
    # 工具模块提示文本
    # ═══════════════════════════════════════════════════════════
    "提示：请先选中两个对象（起点 → 终点）定义弦的位置": {
        "zh": "提示：请先选中两个对象（起点 → 终点）定义弦的位置",
        "en": "Tip: First select two objects (start → end) to define string position"},
    "① 物体模式：选中「起点」和「终点」两个对象（且仅这两个）": {
        "zh": "① 物体模式：选中「起点」和「终点」两个对象（且仅这两个）",
        "en": "① Object Mode: Select 'Start' and 'End' objects (and only these two)"},
    "② 设置下方「弦序号」与「振幅」": {
        "zh": "② 设置下方「弦序号」与「振幅」",
        "en": "② Set 'String Index' and 'Amplitude' below"},
    "③ 点击下方按钮，生成弦并创建 0~20 品 shape key": {
        "zh": "③ 点击下方按钮，生成弦并创建 0~20 品 shape key",
        "en": "③ Click the button below to generate strings and create fret 0~20 shape keys"},
    "弦序号": {"zh": "弦序号", "en": "String Index"},
    "振幅": {"zh": "振幅", "en": "Amplitude"},
    "为选中钢琴键创建 Basis + pressed shape keys": {
        "zh": "为选中钢琴键创建 Basis + pressed shape keys",
        "en": "Create Basis + pressed shape keys for selected piano key"},
    "提示：先选中两个端点对象（start / end），再执行": {
        "zh": "提示：先选中两个端点对象（start / end），再执行",
        "en": "Tip: Select two endpoint objects (start / end) first, then execute"},
    "提示：先选中已细分好的琴弦对象，再执行": {
        "zh": "提示：先选中已细分好的琴弦对象，再执行",
        "en": "Tip: Select an already-subdivided string object first, then execute"},
    "法线取反": {"zh": "法线取反", "en": "Flip Normal"},
    "是否将琴弦偏移（弯曲）方向取反（向指板平面另一侧弯，等价于法线方向取反）": {
        "zh": "是否将琴弦偏移（弯曲）方向取反（向指板平面另一侧弯，等价于法线方向取反）",
        "en": "Whether to reverse the string offset (bend) direction (bend to the other side of the fretboard plane, equivalent to flipping normal direction)"},
    "弦号": {"zh": "弦号", "en": "String Number"},
    "先选中弦（或用弦序号），再执行；需先 Setup 并定位弦记录器": {
        "zh": "先选中弦（或用弦序号），再执行；需先 Setup 并定位弦记录器",
        "en": "Select a string (or use string index) first, then execute; requires Setup and string recorder positioning first"},
    "提示：先选中两个端点记录器（如 s0head / s20head），再执行": {
        "zh": "提示：先选中两个端点记录器（如 s0head / s20head），再执行",
        "en": "Tip: Select two endpoint recorders (e.g. s0head / s20head) first, then execute"},
    "将把该序号范围内的所有记录器线性分布在两端点之间": {
        "zh": "将把该序号范围内的所有记录器线性分布在两端点之间",
        "en": "Will linearly distribute all recorders within this index range between the two endpoints"},
    "一键创建琴弦": {"zh": "一键创建琴弦", "en": "Create Strings (One Click)"},
    "生成ShapeKey": {"zh": "生成ShapeKey", "en": "Generate ShapeKey"},
    "生成弦 Shape Key": {"zh": "生成弦 Shape Key", "en": "Generate String Shape Key"},
    "生成所有弦 Shape Key": {"zh": "生成所有弦 Shape Key", "en": "Generate All String Shape Keys"},
    "线性分布记录器": {"zh": "线性分布记录器", "en": "Linear Distribute Recorders"},
    "弦的索引（0-20）": {"zh": "弦的索引（0-20）", "en": "String index (0-20)"},
    "弦振动的偏移比例（实际偏移 = 弦长 * 比例）": {
        "zh": "弦振动的偏移比例（实际偏移 = 弦长 * 比例）",
        "en": "String vibration offset ratio (actual offset = string length * ratio)"},
    "振幅比例": {"zh": "振幅比例", "en": "Amplitude Ratio"},

    # ═══════════════════════════════════════════════════════════
    # KeyRipple 工具模块 (key_ripple/tools/)
    # ═══════════════════════════════════════════════════════════
    "为钢琴键创建 Shape Keys": {"zh": "为钢琴键创建 Shape Keys", "en": "Create Shape Keys for Piano Keys"},
    "为钢琴键创建 shape keys": {"zh": "为钢琴键创建 shape keys", "en": "Create shape keys for piano keys"},
    "创建钢琴键 Shape Keys": {"zh": "创建钢琴键 Shape Keys", "en": "Create Piano Key Shape Keys"},
    "为所有选中钢琴键创建 Basis 与 pressed shape keys": {
        "zh": "为所有选中钢琴键创建 Basis 与 pressed shape keys",
        "en": "Create Basis and pressed shape keys for all selected piano keys"},
    "钢琴键 shape keys 创建完成": {"zh": "钢琴键 shape keys 创建完成", "en": "Piano key shape keys creation completed"},
    "创建失败: %s": {"zh": "创建失败: %s", "en": "Creation failed: %s"},
    "为选中物体的每个按键创建 Basis + pressed shape key": {
        "zh": "为选中物体的每个按键创建 Basis + pressed shape key",
        "en": "Create Basis + pressed shape key for each key of selected object"},
    "没有选中任何物体": {"zh": "没有选中任何物体", "en": "No objects selected"},
    "请在3D视图中运行此脚本": {"zh": "请在3D视图中运行此脚本", "en": "Please run this script in the 3D Viewport"},
    "跳过非网格物体: %s": {"zh": "跳过非网格物体: %s", "en": "Skipping non-mesh object: %s"},
    "已为 %s 创建形状键: Basis 和 %s": {"zh": "已为 %s 创建形状键: Basis 和 %s", "en": "Created shape keys for %s: Basis and %s"},
    "导出 .avatar（Unreal 引擎格式：坐标 ×100，Y 轴取反，旋转取共轭）": {
        "zh": "导出 .avatar（Unreal 引擎格式：坐标 ×100，Y 轴取反，旋转取共轭）",
        "en": "Export .avatar (Unreal engine format: coordinates ×100, Y axis flipped, rotation conjugated)"},
    "已导出 Unreal 格式 → %s": {"zh": "已导出 Unreal 格式 → %s", "en": "Exported Unreal format → %s"},
    "导出失败：%s": {"zh": "导出失败：%s", "en": "Export failed: %s"},

    # ═══════════════════════════════════════════════════════════
    # FretDance 工具模块 (fret_dance/tools/)
    # ═══════════════════════════════════════════════════════════
    "生成弦（shape key）": {"zh": "生成弦（shape key）", "en": "Create String (shape key)"},
    "已成功创建弦 %s": {"zh": "已成功创建弦 %s", "en": "String %s created successfully"},

    # ═══════════════════════════════════════════════════════════
    # 通用报告消息
    # ═══════════════════════════════════════════════════════════
    "设置失败：未找到角色 addons 目录，请先在「角色选择器」新建角色（初始化角色）": {
        "zh": "设置失败：未找到角色 addons 目录，请先在「角色选择器」新建角色（初始化角色）",
        "en": "Setup failed: character addons directory not found, please create a new performer in Performer Selector first"},
}
