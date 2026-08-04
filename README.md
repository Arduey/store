# Store - 爱发电收款网站

基于爱发电(Afdian)平台实现个人/小团队虚拟商品收款，支持微信支付（支付宝可选开启）。

通过爱发电内部 API 创建赞助订单，获取支付链接/二维码，用户付款后自动检测支付状态。

## 页面一览

| 页面 | 路径 | 说明 |
|------|------|------|
| 首页 | `/` | 三栏式商品选购：左侧商品列表、中间套餐价格、右侧支付方式 |
| 支付页 | `/pay/{out_trade_no}` | 微信扫码 / 支付宝跳转付款 + 自动检测付款状态 |
| 后台管理 | `/admin` | 左右布局：左侧设置、右侧商品管理，拖拽排序，登录频率限制 |

> 页面均为服务端渲染（Jinja2），无需前端构建工具。

## 功能特性

- 🛒 三栏式商品选购页面，左中右布局
- 💰 商品支持多套餐（月/年/永久），自定义价格
- 📱 响应式设计，PC/手机端自适应（手机端汉堡菜单、双列套餐）
- 🔐 后台管理页：左右布局，可视化编辑商品和配置，拖拽排序
- 💳 支付方式可在后台开关（支付宝/微信独立控制）
- 🔄 Quicker 子程序自动获取爱发电 auth_token（登录态）
- 🧾 自动检测付款状态，3秒轮询确认
- 🛡️ 服务端校验价格，前端篡改无效
- ⏱️ 管理页登录频率限制（1分钟5次→锁定5分钟）
- 📋 订单号加粗显示 + 一键复制

## 技术栈

| 层 | 技术 |
|---|------|
| 后端 | Python FastAPI + uvicorn |
| 前端 | Jinja2 模板 + 原生 JavaScript |
| 样式 | 仿 macOS 风格 CSS |
| 支付 | 爱发电内部 API (ifdian.net) |
| Token | Quicker 长链接推送 |

## 部署教程（宝塔面板）

### 环境要求

- 服务器能访问 `ifdian.net`
- Python 3.10+
- 宝塔面板（Python项目管理器）

### 1. 获取项目

**方式一：Git 拉取（推荐）**

宝塔面板 → 终端，执行：

```bash
cd /www/wwwroot
git clone git@github.com:Arduey/store.git pay
```

> 如未配置 SSH Key，先执行 `ssh-keygen -t ed25519 -C "your@email.com"`，然后将 `~/.ssh/id_ed25519.pub` 内容添加到 GitHub → Settings → SSH Keys。
>
> 也可用 HTTPS：`git clone https://github.com/Arduey/store.git pay`

**方式二：手动上传**

宝塔面板 → 文件 → 进入 `/www/wwwroot/` → 新建文件夹 `pay` → 上传所有项目文件（可打包为 zip 后上传解压）。

### 2. 创建 Python 项目

宝塔面板 → 软件商店 → Python项目管理器 → 添加项目：

| 字段 | 值 |
|------|-----|
| 项目路径 | `/www/wwwroot/pay` |
| 启动命令 | `uvicorn main:app --host 0.0.0.0 --port 8000` |
| 端口 | `8000` |
| Python版本 | 3.12+ |
| 启动方式 | 命令行启动 |
| 安装依赖包 | 开启 |

### 3. 配置 config.json

```bash
cd /www/wwwroot/pay
cp config.example.json config.json
```

宝塔面板 → 文件 → 编辑 `/www/wwwroot/pay/config.json`，填写你的真实配置。

> `config.json` 已加入 `.gitignore`，`git pull` 更新代码不会被覆盖。仓库里只有 `config.example.json` 模板文件。

### 4. 添加网站 + 反向代理

宝塔面板 → 网站 → 添加站点 → 填写域名。

站点设置 → 反向代理 → 目标URL: `http://127.0.0.1:8000`

### 5. 快速开始

访问 `https://你的域名/admin`，默认密码 `admin123`，登录后在后台管理页配置：

- **爱发电配置**：大号 user_id
- **站点设置**：Logo、导航链接、支付方式开关、支付提示
- **Quicker 配置**：填写推送信息以启用 token 自动刷新
- **商品管理**：添加商品和套餐，拖拽排序

## 配置说明

### config.json

| 字段 | 说明 |
|------|------|
| `creator_user_id` | 爱发电大号 user_id（收款方） |
| `admin_password` | 管理页登录密码 |
| `quicker.toUser` | Quicker 账号邮箱（用于获取 token） |
| `quicker.code` | 长链接推送 Code |
| `quicker.action` | 处理请求的 Quicker 动作 ID |
| `products` | 商品列表 |

> 站点设置（Logo、导航、支付方式等）在后台管理页配置，保存到 `site` 字段。

### 商品结构

```json
{
    "name": "商品名称",
    "description": "商品说明（可选，显示在主页中间栏）",
    "url": "商品链接（可选，在主页显示为"跳转网站"按钮）",
    "plans": [
        {"number": 1, "unit": "月", "price": 10},
        {"number": 9999, "unit": "永久", "price": 299}
    ]
}
```

> `number` 为 9999 时只显示 `unit` 文字（如"永久"）

### Quicker 子程序约定

子程序通过 `data` 字段区分功能：

| data 值 | 功能 | 返回 |
|---------|------|------|
| `login` | 获取爱发电 auth_token | token 字符串 |

> 支付宝二维码已改为直接跳转方式，不再依赖 Quicker。

## 支付方式说明

| 支付方式 | 实现方式 | Quicker 依赖 |
|---------|---------|:--:|
| 微信 | 爱发电 `redirect_url` → qrcode.js 生成二维码 | ❌ |
| 支付宝 | 爱发电 `redirect_url` → 新窗口跳转付款 | ❌ |
| Token 刷新 | Quicker `data=login` → 返回 auth_token | ✅ |

> 两个支付方式均不依赖 Quicker，只有 token 自动刷新需要。也可以手动从浏览器 Cookie 复制 token 填入后台。

## 优缺点

### ✅ 优点

- **无需营业执照**：通过爱发电平台收款，个人即可使用
- **无需对接支付接口**：不用申请支付宝/微信商户
- **轻量部署**：Python FastAPI，宝塔面板点几下上线
- **配置可视化**：后台管理页直接编辑所有设置，拖拽排序
- **支付方式可控**：支付宝/微信独立开关
- **价格安全**：服务端从配置文件读取真实价格，前端篡改无效
- **响应式设计**：PC/手机端自适应

### ⚠️ 缺点

- **依赖爱发电平台**：爱发电 API 变更可能影响使用
- **非官方 API**：使用了爱发电的内部接口，有被封风险
- **平台抽成 6%**：爱发电收取约 6% 服务费
- **无数据库**：订单数据存内存，重启丢失。建议自行扩展 SQLite；也可直接在爱发电后台查看/管理订单
- **auth_token 自动获取**：通过 Quicker 子程序自动获取，无需手动管理（需配置 Quicker）

## 联系 & 赞赏

**作者**：乐昂岚 (Arduey)

| 微信 | QQ |
|------|-----|
| ![微信](https://cdn.nlark.com/yuque/0/2026/png/40551613/1774510099753-5c6f5dfe-9cbd-420c-9123-fab44ff7d174.png) | ![QQ](https://cdn.nlark.com/yuque/0/2026/png/40551613/1774510106836-e50e9a0d-6158-43d0-8a87-9c310f227360.png) |

- 语雀：[arduey/lan](https://www.yuque.com/arduey/lan/yw9wy2r7bs6y5ccn)
- Quicker 动作 / 技术支持：联系作者获取

### 赞赏码

![赞赏码](https://cdn.nlark.com/yuque/0/2026/jpeg/40551613/1774945478345-956d495f-78bf-4f45-bcb8-d3fb54b7d811.jpeg)

> 💰 如果这个项目对你有帮助，欢迎赞赏支持！

## 安全提示

- 默认密码 `admin123`，请及时修改
- 部署后建议开启 HTTPS
- `config.json` 已 gitignore，不会被提交到仓库
- 爱发电 token 自动获取，不在本地存储
- 登录接口有频率限制防护

## License

MIT
