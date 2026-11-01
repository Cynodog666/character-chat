"""统一的 HTTP POST 封装（标准库 urllib）。

错误处理原则：把服务端返回的原始信息带出来。只抛 "400 Bad Request" 对排查毫无帮助，
真正的线索（模型名不对、key 没权限、余额不足）都在响应体里。
"""

import json
from urllib import error, request


class ApiError(RuntimeError):
    pass


def post_json(url: str, payload: dict, api_key: str, *, service: str, timeout: int = 90) -> dict:
    if not api_key:
        raise ApiError(f"{service}：缺少 API Key，请在 .env 中填写")

    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )

    try:
        with request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")[:300]
        raise ApiError(f"{service} 返回 {exc.code}：{detail}") from exc
    except error.URLError as exc:
        raise ApiError(f"{service} 不可达：{exc.reason}") from exc
    except json.JSONDecodeError as exc:
        raise ApiError(f"{service} 返回了非 JSON 内容") from exc
