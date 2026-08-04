"""
爱发电收款网站 - FastAPI 后端
基于爱发电内部 API 实现：创建订单 + 查询支付状态
"""
import os
import time
import json
import base64
from datetime import datetime
from urllib.parse import urlparse, parse_qs, unquote, urljoin

import httpx
from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = FastAPI(title="Afdian Pay")
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")
templates_env = Environment(loader=FileSystemLoader(os.path.join(BASE_DIR, "templates")))


def render_template(name: str, **context) -> HTMLResponse:
    """手动渲染 Jinja2 模板，绕过 starlette 版本兼容问题"""
    template = templates_env.get_template(name)
    return HTMLResponse(template.render(**context))

# ============================================================
# 配置加载
# ============================================================
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")
CONFIG_EXAMPLE = os.path.join(BASE_DIR, "config.example.json")
AFDIAN_API_BASE = "https://ifdian.net"

PAY_TYPES = {
    "alipay": {"py_type": "apy", "label": "支付宝"},
    "wechat": {"py_type": "wpy_qr", "label": "微信"},
}


def load_config() -> dict:
    """读取 config.json，不存在则回退到 config.example.json"""
    for path in [CONFIG_FILE, CONFIG_EXAMPLE]:
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            continue
    return {"creator_user_id": "", "admin_password": "admin123", "products": []}


def save_config(config: dict):
    """保存配置到 config.json"""
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=4)


def get_config() -> dict:
    """获取当前配置（每次读取，保证管理页修改后即时生效）"""
    return load_config()


def get_site_config() -> dict:
    """获取站点配置，缺失字段用默认值"""
    cfg = get_config()
    site = cfg.get("site", {})
    return {
        "header_logo": site.get("header_logo", "爱发电收款"),
        "header_icon_url": site.get("header_icon_url", ""),
        "header_nav": site.get("header_nav", []),
        "footer_text": site.get("footer_text", ""),
        "pay_tips": site.get("pay_tips", ""),
        "alipay_enabled": site.get("alipay_enabled", False),
        "wechat_enabled": site.get("wechat_enabled", True),
    }


def plan_label(plan: dict) -> str:
    """number + unit，9999 只显示 unit"""
    n = plan.get("number", 1)
    u = plan.get("unit", "月")
    return u if n == 9999 else f"{n}{u}"


def extract_alipay_gateway_url(redirect_url: str) -> str:
    """
    从爱发电返回的 redirect_url 中提取支付宝支付页面链接。
    redirect_url 格式: https://render.alipay.com/...?scheme=alipays://...url=openapi.alipay.com/gateway.do...
    提取出 scheme 参数 → 再从中提取 url 参数 → 返回 openapi.alipay.com/gateway.do 链接
    """
    parsed = urlparse(redirect_url)
    params = parse_qs(parsed.query)
    scheme = params.get("scheme", [None])[0]
    if not scheme:
        return redirect_url

    decoded = unquote(scheme)  # alipays://platformapi/startapp?appId=...&url=...
    parsed_alipay = urlparse(decoded)
    alipay_params = parse_qs(parsed_alipay.query)
    gateway = alipay_params.get("url", [None])[0]
    if not gateway:
        return redirect_url

    return unquote(gateway)  # https://openapi.alipay.com/gateway.do?...




# ============================================================
# 订单存储 + Token 缓存
# ============================================================
orders: dict[str, dict] = {}
_auth_token: str | None = None


async def get_auth_token() -> str:
    """获取小号 auth_token，优先内存缓存，没有则调 Quicker 获取"""
    global _auth_token
    if _auth_token:
        return _auth_token
    token = await quicker_call("login")
    if token:
        # 只保留 ASCII 字符，防止 Quicker 返回中文导致 httpx cookie 编码错误
        _auth_token = token.encode("ascii", errors="ignore").decode("ascii").strip()
    return _auth_token or ""



# ============================================================
# 爱发电内部 API
# ============================================================

async def afdian_create_order(
    creator_user_id: str,
    amount: float,
    remark: str,
    py_type: str = "apy",
) -> tuple[bool, dict | str]:
    """POST /api/order/create-order，token 从 Quicker 获取"""
    auth_token = await get_auth_token()
    if not auth_token:
        return False, "无法获取 auth_token"
    body = {
        "plan_id": "",
        "month": 1,
        "total_amount": amount,
        "out_trade_no": "",
        "py_type": py_type,
        "code": "",
        "user_id": creator_user_id,
        "per_month": str(amount),
        "remark": remark,
        "mp_token": -1,
        "show_amount": amount,
        "user_address_id": "",
        "sku_detail": [],
        "plan_invite_code": "",
        "custom_order_id": "",
        "cmid": "",
        "card_id_list": [],
        "ticket_round_id": "",
        "agreement": "",
        "bundle_count": "",
        "is_cart": "",
        "cart_order_no": "",
        "pay_cart_order_no": "",
        "agreement_npp": "",
        "affiliate_code": "",
    }

    try:
        json_body = json.dumps(body, ensure_ascii=False).encode("utf-8")
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{AFDIAN_API_BASE}/api/order/create-order",
                content=json_body,
                cookies={"auth_token": auth_token.encode("ascii", errors="ignore").decode() if auth_token else ""},
                headers={
                    "accept": "application/json, text/plain, */*",
                    "accept-language": "zh-CN,zh;q=0.9",
                    "content-type": "application/json; charset=utf-8",
                    "origin": AFDIAN_API_BASE,
                    "referer": f"{AFDIAN_API_BASE}/order/create?user_id={creator_user_id}",
                    "afd-fe-version": "1.13.6",
                },
            )
            data = resp.json()
            if data.get("ec") != 200:
                em = data.get("em", "未知错误")
                print(f"[创建订单失败] ec={data.get('ec')} em={em}")
                return False, f"爱发电返回: {em}"
            return True, data.get("data", {})
    except httpx.TimeoutException:
        return False, "连接爱发电超时，服务器可能无法访问 ifdian.net"
    except httpx.ConnectError:
        return False, "无法连接爱发电(ifdian.net)，请检查服务器网络"
    except Exception as e:
        print(f"[创建订单异常] {e}")
        return False, str(e)[:200]


async def afdian_check_order(out_trade_no: str) -> dict | None:
    """GET /api/order/check?out_trade_no=xxx，token 从 Quicker 获取"""
    auth_token = await get_auth_token()
    if not auth_token:
        return None
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{AFDIAN_API_BASE}/api/order/check",
                params={"out_trade_no": out_trade_no},
                cookies={"auth_token": auth_token.encode("ascii", errors="ignore").decode() if auth_token else ""},
                headers={
                    "accept": "application/json, text/plain, */*",
                    "accept-language": "zh-CN,zh;q=0.9",
                    "referer": f"{AFDIAN_API_BASE}/order/create",
                    "afd-fe-version": "1.13.6",
                },
            )
            data = resp.json()
            if data.get("ec") != 200:
                print(f"[查询订单失败] {data}")
                return None
            return data.get("data", {})
    except Exception as e:
        print(f"[查询订单异常] {e}")
        return None


# ============================================================
# 前端页面路由
# ============================================================

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """首页 - 商品列表"""
    config = get_config()
    products = config.get("products", [])

    # 渲染套餐标签（深拷贝，避免污染原始数据）
    products_for_template = []
    for p in products:
        p_copy = dict(p)
        plans_copy = []
        for plan in p.get("plans", []):
            plan_copy = dict(plan)
            plan_copy["_label"] = plan_label(plan)
            plans_copy.append(plan_copy)
        p_copy["plans"] = plans_copy
        products_for_template.append(p_copy)

    return render_template("index.html",
        request=request,
        products=products_for_template,
        site=get_site_config(),
    )


@app.post("/create-order")
async def create_order(
    request: Request,
    product_name: str = Form(...),
    months: int = Form(...),
    unit: str = Form("月"),
    price: float = Form(0),
    pay_type: str = Form("alipay"),
):
    """创建订单，价格从 config 查，不信任前端"""
    config = get_config()

    # 检查配置
    creator_user_id = config.get("creator_user_id", "")

    for key, label in [("creator_user_id", "大号 user_id")]:
        val = config.get(key, "")
        if not val or "\u628a\u8fd9\u91cc\u6539\u6210" in val:
            return JSONResponse({"error": f"请先在后台管理 /admin 填写{label}"}, status_code=400)

    # 从 config 查找套餐和真实价格
    amount = None
    for p in config.get("products", []):
        if p["name"] == product_name:
            for plan in p.get("plans", []):
                if plan["number"] == months and plan.get("unit", "") == unit:
                    amount = plan["price"]
                    break
            break
    if amount is None:
        return JSONResponse({"error": "所选套餐不存在"}, status_code=400)
    if amount < 5:
        return JSONResponse({"error": "配置金额不能低于5元"}, status_code=400)

    pay_info = PAY_TYPES.get(pay_type)
    if not pay_info:
        return JSONResponse({"error": "不支持的支付方式"}, status_code=400)
    if pay_type == "alipay":
        return JSONResponse({"error": "支付宝暂不可用，请选择微信支付"}, status_code=400)

    remark = f"{product_name}-{months}"

    # 调爱发电创建订单
    ok, result = await afdian_create_order(
        creator_user_id=creator_user_id,
        amount=amount,
        remark=remark,
        py_type=pay_info["py_type"],
    )

    if not ok:
        return JSONResponse({"error": f"创建支付订单失败: {result}"}, status_code=500)

    out_trade_no = result["out_trade_no"] if isinstance(result, dict) else ""
    redirect_url = result.get("redirect_url", "") if isinstance(result, dict) else ""

    orders[out_trade_no] = {
        "out_trade_no": out_trade_no,
        "product_name": f"{product_name} - {months}{unit}",
        "amount": amount,
        "remark": remark,
        "pay_type": pay_type,
        "py_type": pay_info["py_type"],
        "qr_url": redirect_url,
        "status": "pending",
        "created_at": int(time.time()),
    }

    return JSONResponse({
        "out_trade_no": out_trade_no,
        "amount": amount,
        "pay_type": pay_type,
    })


@app.get("/pay/{out_trade_no}", response_class=HTMLResponse)
async def pay_page(request: Request, out_trade_no: str):
    """支付页面"""
    order = orders.get(out_trade_no)
    if not order:
        return HTMLResponse("订单不存在", status_code=404)
    return render_template("pay.html",
        request=request,
        order=order,
        site=get_site_config(),
    )


@app.get("/api/order/{out_trade_no}/status")
async def check_order_status(out_trade_no: str):
    """查询订单支付状态（前端轮询）"""
    order = orders.get(out_trade_no)
    if not order:
        return JSONResponse({"error": "订单不存在"}, status_code=404)

    if order["status"] == "paid":
        return JSONResponse({"status": "paid"})

    if time.time() - order["created_at"] > 1800:
        order["status"] = "expired"
        return JSONResponse({"status": "expired"})

    if order.get("out_trade_no"):
        check_result = await afdian_check_order(order["out_trade_no"])
        if check_result:
            afdian_status = check_result.get("order", {}).get("status", 0)
            if afdian_status == 2:
                order["status"] = "paid"
                return JSONResponse({"status": "paid"})

    return JSONResponse({"status": "pending"})


@app.get("/api/order/{out_trade_no}/qrcode")
async def get_order_qrcode(out_trade_no: str):
    """获取订单的支付入口"""
    order = orders.get(out_trade_no)
    if not order:
        return JSONResponse({"error": "订单不存在"}, status_code=404)

    pay_type = order.get("pay_type", "")
    redirect_url = order.get("qr_url", "")

    if not redirect_url:
        return JSONResponse({"error": "无支付链接"}, status_code=404)

    # 支付宝：直接返回链接，前端显示跳转按钮
    if pay_type == "alipay":
        return JSONResponse({"type": "url", "url": redirect_url})

    # 微信：返回链接给前端 qrcode.js 生成二维码
    if pay_type == "wechat":
        return JSONResponse({"type": "url", "url": redirect_url})


# ============================================================
# 登录频率限制（内存）
# ============================================================
_login_fails: dict[str, list] = {}  # ip -> [fail_count, first_fail_time]


def check_login_rate(ip: str) -> str | None:
    """检查登录频率，返回 None 表示允许，否则返回错误信息"""
    now = time.time()
    record = _login_fails.get(ip)
    if not record:
        return None
    count, first = record
    # 5 分钟内超过 5 次失败，锁定
    if count >= 5 and now - first < 300:
        remaining = int(300 - (now - first))
        return f"登录过于频繁，请 {remaining} 秒后再试"
    # 超过 1 分钟窗口重置计数
    if now - first > 60:
        _login_fails.pop(ip, None)
        return None
    return None


def record_login_fail(ip: str):
    now = time.time()
    record = _login_fails.get(ip)
    if not record or now - record[1] > 60:
        _login_fails[ip] = [1, now]
    else:
        record[0] += 1

def check_admin_pwd(password: str) -> bool:
    """验证后台管理密码"""
    config = get_config()
    expected = config.get("admin_password", "admin123")
    return bool(expected) and password == expected


@app.get("/admin", response_class=HTMLResponse)
async def admin_page(request: Request):
    """后台管理页面"""
    return render_template("admin.html", request=request)


@app.post("/admin/login")
async def admin_login(request: Request):
    """验证管理密码"""
    ip = request.client.host if request.client else "unknown"
    limit = check_login_rate(ip)
    if limit:
        return JSONResponse({"ok": False, "error": limit})
    try:
        body = await request.json()
        pwd = body.get("password", "")
        if check_admin_pwd(pwd):
            _login_fails.pop(ip, None)  # 成功清零
            return JSONResponse({"ok": True})
        record_login_fail(ip)
        return JSONResponse({"ok": False, "error": "密码错误"})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)})


@app.get("/admin/config")
async def admin_get_config(pwd: str = ""):
    """获取当前配置（需要密码）"""
    if not check_admin_pwd(pwd):
        return JSONResponse({"error": "密码错误"}, status_code=403)
    return JSONResponse(get_config())


@app.post("/admin/save")
async def admin_save_config(request: Request):
    """保存配置"""
    try:
        config = await request.json()
        pwd = config.pop("_password", "")
        if not check_admin_pwd(pwd):
            return JSONResponse({"ok": False, "error": "密码错误"})
        # 如果用户没改密码，保留原来的
        if "admin_password" in config and not config["admin_password"]:
            config["admin_password"] = get_config().get("admin_password", "admin123")
        if "admin_password" not in config:
            config["admin_password"] = get_config().get("admin_password", "admin123")
        save_config(config)
        return JSONResponse({"ok": True})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)})


async def quicker_call(data: str) -> str | None:
    """调用 Quicker 子程序"""
    config = get_config()
    qk = config.get("quicker", {})
    if not qk.get("toUser") or not qk.get("code"):
        return None
    try:
        async with httpx.AsyncClient(timeout=35) as client:
            resp = await client.post(
                "https://push.getquicker.cn/to/quicker",
                json={
                    "toUser": qk["toUser"],
                    "code": qk["code"],
                    "toDevice": qk.get("toDevice", ""),
                    "operation": "action",
                    "data": data,
                    "action": qk.get("action", ""),
                    "wait": True,
                    "maxWaitMs": 30000,
                    "txt": True,
                },
            )
            return resp.text.strip()
    except Exception as e:
        print(f"[Quicker] {e}")
        return None


@app.post("/admin/refresh-token")
async def admin_refresh_token(request: Request):
    """通过 Quicker 获取新的 auth_token（data=login）"""
    try:
        body = await request.json()
        pwd = body.get("_password", "")
        if not check_admin_pwd(pwd):
            return JSONResponse({"ok": False, "error": "密码错误"})
        global _auth_token
        _auth_token = None
        token = await get_auth_token()
        if not token:
            return JSONResponse({"ok": False, "error": "Quicker 返回为空"})
        return JSONResponse({"ok": True, "token": token})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)})



# ============================================================
# 启动
# ============================================================
if __name__ == "__main__":
    import uvicorn

    cfg = get_config()
    print("=" * 50)
    print("  爱发电收款网站")
    print(f"  前台:    http://127.0.0.1:8000")
    print(f"  后台管理: http://127.0.0.1:8000/admin")
    print(f"  收款方: {cfg.get('creator_user_id', '未配置')}")
    print("=" * 50)
    uvicorn.run(app, host="0.0.0.0", port=8000)
