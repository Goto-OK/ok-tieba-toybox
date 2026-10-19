"""统一错误提示目录。"""

from __future__ import annotations


def _text(error: BaseException) -> str:
    return str(error or "").strip()


def friendly_error(error: BaseException) -> str:
    """把异常转成“原因 + 下一步”，不暴露裸 traceback。"""
    text = _text(error)
    lowered = text.lower()
    name = type(error).__name__

    if "captcha" in name.lower() or "安全验证" in text or "验证码" in text:
        return "被安全验证拦截：请用浏览器打开贴吧完成验证，或更新 Cookie 后重试。"
    if name == "ThreadGoneError" or "404" in text or "不存在" in text or "删除" in text:
        return "帖子不存在或已删除：跳过该帖，检查链接后再试。"
    if "429" in text or "too many" in lowered or "限流" in text:
        return "请求过快被限流：稍后再试，或把请求间隔调大。"
    if "403" in text or "412" in text or "拒绝" in text:
        return "访问被拒绝：可能需要登录/Cookie，或当前网络被限制。"
    if "timeout" in lowered or "timed out" in lowered or "超时" in text:
        return "网络超时：检查网络/代理后重试；已完成的帖子会保留。"
    if "connection" in lowered or "网络" in text or "断网" in text:
        return "网络连接失败：检查网络或代理设置后重试。"
    if "bduss" in lowered or "登录" in text or "cookie" in lowered:
        return "登录信息无效：关注增强会关闭，核心匿名抓取仍可继续；请重新填写 BDUSS。"
    if "permission" in lowered or "拒绝访问" in text or "occupied" in lowered or "占用" in text:
        return "文件被占用或无权限：关闭 Excel/占用程序，或换一个保存位置。"
    if "no space" in lowered or "磁盘" in text or "空间" in text:
        return "磁盘空间不足：清理空间或换保存位置。"
    if "sqlite" in lowered or "database" in lowered or "schema" in lowered:
        return "结果文件损坏或版本不兼容：旧文件会保留，软件从空白开始。"
    return f"操作失败：{text or name}。请重试；如果反复失败，可复制诊断信息反馈。"


__all__ = ["friendly_error"]
