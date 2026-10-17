"""Minimal lxml.html-compatible layer built on BeautifulSoup.

This is only used on Android, where lxml's C extension is unavailable.
Desktop builds keep the real lxml.
"""

from __future__ import annotations

import re
from typing import List, Optional

from bs4 import BeautifulSoup, Tag

_STEP_RE = re.compile(r"^(//|\.//)(\*|[A-Za-z0-9_-]+)((?:\[[^\]]*\])*)$")
_ATTR_END_RE = re.compile(r"/@([A-Za-z0-9_:-]+)\s*$")
_PRED_RE = re.compile(r"\[([^\]]*)\]")


class Element:
    def __init__(self, tag: Tag):
        self.tag = tag

    def xpath(self, expression: str) -> list:
        return _xpath(self.tag, expression)

    def get(self, name: str, default=None):
        return self.tag.get(name, default)

    def text_content(self) -> str:
        return self.tag.get_text()

    def getparent(self) -> Optional["Element"]:
        parent = self.tag.parent
        return Element(parent) if isinstance(parent, Tag) else None

    def remove(self, child: "Element") -> None:
        if isinstance(child, Element) and isinstance(child.tag, Tag):
            child.tag.decompose()

    def __repr__(self) -> str:
        return f"<Element {getattr(self.tag, 'name', '?')}>"


class Document:
    def __init__(self, soup: BeautifulSoup):
        self.soup = soup

    def xpath(self, expression: str) -> list:
        return _xpath(self.soup, expression)


def document_fromstring(html_text: str) -> Document:
    return Document(BeautifulSoup(html_text, "html.parser"))


def fragment_fromstring(payload: str, create_parent: str = "div") -> Document:
    return Document(BeautifulSoup(f"<{create_parent}>{payload}</{create_parent}>", "html.parser"))


def tostring(node, encoding: str = "unicode") -> str:
    if isinstance(node, Element):
        return str(node.tag)
    if isinstance(node, Document):
        return str(node.soup)
    return str(node)


# ------------------------------------------------------------------ internals
def _root_of(tag) -> Tag:
    current = tag
    while isinstance(current.parent, Tag):
        current = current.parent
    return current


def _match_pred(tag: Tag, pred: str) -> bool:
    pred = pred.strip()
    if not pred:
        return True

    # contains(concat(" ", normalize-space(@class), " "), " d_post_content ")
    if "normalize-space(@class)" in pred:
        match = re.search(r'["\']([^"\']+)["\']\s*\)\s*$', pred)
        if match:
            token = match.group(1).strip().lower()
            classes = [str(item).lower() for item in (tag.get("class") or [])]
            return token in classes

    # contains(@class, "l_post")
    match = re.match(r'contains\(\s*@([A-Za-z0-9_:-]+)\s*,\s*["\']([^"\']*)["\']\s*\)$', pred)
    if match:
        attr, needle = match.group(1), match.group(2)
        return needle in str(tag.get(attr) or "")

    # @class="l_post"
    match = re.match(r'@([A-Za-z0-9_:-]+)\s*=\s*["\']([^"\']*)["\']$', pred)
    if match:
        return str(tag.get(match.group(1)) or "") == match.group(2)

    # @data-field  (attribute exists)
    match = re.match(r'@([A-Za-z0-9_:-]+)$', pred)
    if match:
        return tag.has_attr(match.group(1))

    return False


def _select(context, expression: str) -> list:
    attr_name = None
    match = _ATTR_END_RE.search(expression)
    if match:
        attr_name = match.group(1)
        expression = expression[: match.start()].strip()

    step = _STEP_RE.match(expression)
    if not step:
        return []
    axis, name, preds_raw = step.group(1), step.group(2), step.group(3)
    predicates = [item for item in _PRED_RE.findall(preds_raw) if item.strip()]

    if axis == "//":
        root = _root_of(context) if isinstance(context, Tag) else context
        candidates = root.find_all(True if name == "*" else name)
    else:
        candidates = context.find_all(True if name == "*" else name)

    results = []
    for tag in candidates:
        if not isinstance(tag, Tag):
            continue
        if name != "*" and tag.name != name:
            continue
        if all(_match_pred(tag, pred) for pred in predicates):
            results.append(tag)
    if attr_name:
        return [str(tag.get(attr_name) or "") for tag in results]
    return [Element(tag) for tag in results]


def _xpath(context, expression: str) -> list:
    expression = expression.strip()
    if not expression:
        return []
    if "|" in expression:
        results = []
        for part in expression.split("|"):
            results.extend(_xpath(context, part))
        return results
    return _select(context, expression)
