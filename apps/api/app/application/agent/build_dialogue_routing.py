"""Only explicit intake turns belong to the guided build state machine."""
import re

from .natural_build_entries import request_mode
from .system_image_status_queries import is_build_status_question


def is_project_name_question(text):
    return bool(re.fullmatch(
        r"(?:(?:请问|告诉我|请告诉我|查看|查询|看看)?\s*(?:当前|这个|本)?项目(?:的)?"
        r"(?:(?:名称|名字|名)(?:(?:是|叫)(?:什么|啥)|叫什么)?|叫(?:什么|啥)(?:名字)?)"
        r"|(?:what(?:'s| is)\s+(?:the\s+)?(?:current\s+)?project(?:'s)?\s+name)"
        r"|(?:what is (?:this|the current) project called))\s*[？?。.!！]?", text.strip(), re.I))


def is_intake_question(text):
    # Do not infer project names, skip choices or source edits from questions.
    return bool(re.search(r"[？?]|什么|为什么|怎么|如何|是否|是不是|能否|吗|么|"
        r"^(?:请问|解释|介绍|what\b|why\b|how\b|can\b|could\b|is\b|are\b|explain\b)", text.strip(), re.I))


def is_explicit_build_tool_confirmation(text):
    return bool(re.fullmatch(
        r"(?:确认(?:[，, ]*继续执行)?|同意|继续|执行|可以|批准|confirm(?:ed)?|approve(?:d)?|continue|proceed|yes|ok(?:ay)?|go ahead)"
        r"(?:\s+tool_[a-f0-9]+)?[。.!！]?", text.strip(), re.I))


def build_turn_kind(text):
    value = text.strip()
    if is_build_status_question(value) or re.fullmatch(
        r"(?:当前|现在)?(?:构建)?(?:进度|状态)(?:如何|怎么样)?[？?。]?|"
        r"(?:接下来|下一步)(?:做什么|怎么办|怎么做)?[？?。]?|"
        r"(?:status|progress|what(?:'s| is) next)[?.]?|"
        r"(?:确认之前请告诉我预算|不要确认|不要跳过确认|do not (?:confirm|proceed))[。.!！]?", value, re.I):
        return "status"
    if re.fullmatch(r"(?:请|帮我)?(?:查看|查询|看看)?(?:当前|本次|构建)?(?:的)?(?:执行记录|操作记录|执行过程)[？?。]?|"
        r"(?:你)?(?:刚才|已经)?做了什么[？?。]?|(?:show |view )?(?:execution history|build history)[?.]?", value, re.I):
        return "history"
    if re.fullmatch(r"(?:确认采集已有资料|confirm source capture)[。.!！]?", value, re.I):
        return "capture"
    if re.fullmatch(r"(?:确认|同意|继续|确认构建|继续构建|继续分析|确认分析|confirm|continue(?: build| analysis)?|proceed|yes|ok)[。.!！]?", value, re.I):
        return "continue"
    if re.fullmatch(r"(?:选择项目|select project)\s+proj_[a-zA-Z0-9_-]+", value, re.I):
        return "selection"
    if request_mode(value) == "initialize" or re.fullmatch(
        r"(?:请|帮我|请帮我)?(?:构建|建立|初始化|搭建)(?:一个)?系统画像[。！]?", value):
        return "build"
    return None
