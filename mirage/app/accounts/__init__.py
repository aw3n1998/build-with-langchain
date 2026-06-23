"""账号模块 —— 用户系统 + 充值/计费，与核心管线【完全解耦】。

设计原则（同 tts_providers / video providers 的可插拔思路）：
- 认证后端可插拔：auth.AuthProvider 注册表（local 默认；OAuth/微信/手机号可加一个文件接入）。
- 支付渠道可插拔：billing.PaymentProvider 注册表（mock 默认；Stripe/微信支付/支付宝门控接入）。
- 核心零依赖：pipeline/* 不 import 本模块；鉴权与扣费只发生在【路由层】(deps.py)。
- 门控休眠零回归：AUTH_ENABLED=false → 开放访问（单用户开发态）；BILLING_ENABLED=false → 免费不扣费。

入口：main_api 挂 routes.router；受保护/计费的接口用 deps.current_user / deps.require_credits。
"""
