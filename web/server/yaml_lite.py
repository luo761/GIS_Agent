"""极简 YAML 解析器（仅覆盖本项目配置文件的语法子集）。

网页端希望能直接读取项目里的 `config/*.yaml`，但演示环境不一定安装了 pyyaml。
这里实现一个零依赖的解析器，支持：

- 缩进嵌套的 mapping / sequence
- 行内列表 `[a, b, c]`
- 单/双引号字符串、整数、浮点数、true/false/null
- `#` 行内注释（引号内的 # 不会被误判）

用法：

    >>> parse_yaml(Path("config/agents_capability.yaml").read_text(encoding="utf-8"))
"""
from __future__ import annotations

import re
from typing import Any

_BOOL = {"true": True, "false": False, "null": None, "~": None, "none": None}


def _strip_comment(line: str) -> str:
    """去掉不在引号内的 # 注释。"""
    quote = ""
    out: list[str] = []
    for ch in line:
        if quote:
            out.append(ch)
            if ch == quote:
                quote = ""
            continue
        if ch in "\"'":
            quote = ch
            out.append(ch)
        elif ch == "#":
            break
        else:
            out.append(ch)
    return "".join(out).rstrip()


def _split_top_level(text: str, sep: str = ",") -> list[str]:
    """按分隔符切分，忽略括号/引号内部的分隔符。"""
    parts: list[str] = []
    depth = 0
    quote = ""
    buf: list[str] = []
    for ch in text:
        if quote:
            buf.append(ch)
            if ch == quote:
                quote = ""
            continue
        if ch in "\"'":
            quote = ch
            buf.append(ch)
        elif ch in "[{(":
            depth += 1
            buf.append(ch)
        elif ch in "]})":
            depth -= 1
            buf.append(ch)
        elif ch == sep and depth == 0:
            parts.append("".join(buf).strip())
            buf = []
        else:
            buf.append(ch)
    tail = "".join(buf).strip()
    if tail:
        parts.append(tail)
    return parts


def _unquote(text: str) -> str:
    text = text.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        inner = text[1:-1]
        if text[0] == '"':
            inner = inner.replace('\\"', '"').replace("\\n", "\n").replace("\\t", "\t")
        return inner
    return text


def parse_scalar(text: str) -> Any:
    text = text.strip()
    if not text:
        return None
    if text.startswith("[") and text.endswith("]"):
        inner = text[1:-1].strip()
        if not inner:
            return []
        return [parse_scalar(item) for item in _split_top_level(inner)]
    if text.startswith("{") and text.endswith("}"):
        inner = text[1:-1].strip()
        if not inner:
            return {}
        out: dict[str, Any] = {}
        for item in _split_top_level(inner):
            key, _, value = item.partition(":")
            out[_unquote(key.strip())] = parse_scalar(value)
        return out
    if (text.startswith('"') and text.endswith('"')) or (
        text.startswith("'") and text.endswith("'")
    ):
        return _unquote(text)
    low = text.lower()
    if low in _BOOL:
        return _BOOL[low]
    if re.fullmatch(r"[-+]?\d+", text):
        try:
            return int(text)
        except ValueError:
            return text
    if re.fullmatch(r"[-+]?(\d+\.\d*|\.\d+|\d+)([eE][-+]?\d+)?", text):
        try:
            return float(text)
        except ValueError:
            return text
    return text


def _split_key(content: str) -> tuple[str, str] | None:
    """把 `key: value` 拆开；没有冒号时返回 None。"""
    quote = ""
    depth = 0
    for i, ch in enumerate(content):
        if quote:
            if ch == quote:
                quote = ""
            continue
        if ch in "\"'":
            quote = ch
        elif ch in "[{":
            depth += 1
        elif ch in "]}":
            depth -= 1
        elif ch == ":" and depth == 0:
            rest = content[i + 1:]
            if rest and not rest.startswith(" "):
                continue
            return content[:i].strip(), rest.strip()
    return None


class _Parser:
    def __init__(self, lines: list[tuple[int, str]]):
        self.lines = lines
        self.pos = 0

    def _peek(self) -> tuple[int, str] | None:
        return self.lines[self.pos] if self.pos < len(self.lines) else None

    def parse_block(self, indent: int) -> Any:
        """解析当前缩进层级的块。"""
        head = self._peek()
        if head is None:
            return None
        if head[1].startswith("- ") or head[1] == "-":
            return self.parse_list(indent)
        return self.parse_map(indent)

    def parse_list(self, indent: int) -> list[Any]:
        out: list[Any] = []
        while True:
            item = self._peek()
            if item is None or item[0] != indent:
                break
            content = item[1]
            if not (content.startswith("- ") or content == "-"):
                break
            self.pos += 1
            rest = content[2:].strip() if content.startswith("- ") else ""
            if not rest:
                nxt = self._peek()
                if nxt and nxt[0] > indent:
                    out.append(self.parse_block(nxt[0]))
                else:
                    out.append(None)
                continue
            pair = _split_key(rest)
            if pair is not None:
                node: dict[str, Any] = {}
                key, value = pair
                if value:
                    node[_unquote(key)] = parse_scalar(value)
                else:
                    nxt = self._peek()
                    if nxt and nxt[0] > indent:
                        node[_unquote(key)] = self.parse_block(nxt[0])
                    else:
                        node[_unquote(key)] = None
                # 同一列表项里可能还有同级的后续键
                while True:
                    nxt = self._peek()
                    if nxt is None or nxt[0] != indent + 2:
                        break
                    sub_pair = _split_key(nxt[1])
                    if sub_pair is None:
                        break
                    self.pos += 1
                    sub_key, sub_value = sub_pair
                    if sub_value:
                        node[_unquote(sub_key)] = parse_scalar(sub_value)
                    else:
                        deeper = self._peek()
                        if deeper and deeper[0] > nxt[0]:
                            node[_unquote(sub_key)] = self.parse_block(deeper[0])
                        else:
                            node[_unquote(sub_key)] = None
                out.append(node)
            else:
                out.append(parse_scalar(rest))
        return out

    def parse_map(self, indent: int) -> dict[str, Any]:
        out: dict[str, Any] = {}
        while True:
            item = self._peek()
            if item is None or item[0] != indent:
                break
            content = item[1]
            if content.startswith("- "):
                break
            pair = _split_key(content)
            if pair is None:
                self.pos += 1
                continue
            self.pos += 1
            key, value = pair
            key = _unquote(key)
            if value:
                out[key] = parse_scalar(value)
            else:
                nxt = self._peek()
                if nxt and nxt[0] > indent:
                    out[key] = self.parse_block(nxt[0])
                else:
                    out[key] = None
        return out


def parse_yaml(text: str) -> Any:
    lines: list[tuple[int, str]] = []
    for raw in (text or "").splitlines():
        cleaned = _strip_comment(raw.replace("\t", "    "))
        if not cleaned.strip():
            continue
        indent = len(cleaned) - len(cleaned.lstrip(" "))
        lines.append((indent, cleaned.strip()))
    if not lines:
        return None
    parser = _Parser(lines)
    return parser.parse_block(lines[0][0])
