---
title: 用户认证 API
module: api/user
tags: [auth, jwt, login, security]
owner: identity-team
last_review: 2026-05-20
---

# 用户认证 API

本文档描述用户认证体系的三个核心接口：登录、登出、Token 刷新。系统采用 **JWT 双 Token 方案**（access + refresh），access token 短时效用于业务调用，refresh token 长时效仅用于换取新的 access token。所有接口位于服务 `identity-service` 之下，统一前缀 `/api/v1/auth`。

## 设计概览

认证流程分为三个阶段：

1. **登录阶段**：用户提交账号密码，服务端验证后签发 `access_token` (15 min) 与 `refresh_token` (30 day)。
2. **业务调用阶段**：客户端在 `Authorization: Bearer <access_token>` 头部携带 access token，网关层验证签名与过期时间。
3. **续期阶段**：access token 过期后，客户端使用 refresh token 调用 `/refresh` 换取新 token 对。

关键设计决策：

- **不使用 Session**：所有状态信息编码进 JWT payload，便于水平扩展。
- **Refresh Token 旋转**：每次刷新均会签发新的 refresh token 并废弃旧的，降低长期凭证泄漏风险。
- **黑名单 + 短时效**：access token 不进黑名单（依赖短时效），refresh token 主动登出时进 Redis 黑名单。

## POST /api/v1/auth/login

用户登录，校验账号密码，签发 token 对。

### 请求参数

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `username` | string | 是 | 用户名或邮箱，最长 64 字符 |
| `password` | string | 是 | 明文密码，服务端使用 bcrypt 校验 |
| `device_id` | string | 否 | 设备指纹，用于风控与登录日志 |
| `captcha_token` | string | 条件 | 当账户处于风控状态时必填 |

### 请求示例

```bash
curl -X POST https://api.example.com/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{
    "username": "alice@example.com",
    "password": "S3cretPa$$",
    "device_id": "ios-abc-123"
  }'
```

### 响应示例

```json
{
  "code": 0,
  "data": {
    "access_token": "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9...",
    "refresh_token": "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9...",
    "access_expires_in": 900,
    "refresh_expires_in": 2592000,
    "user": {
      "id": "u_8821",
      "username": "alice",
      "role": "member"
    }
  }
}
```

### 错误码

| code | HTTP | message | 处理建议 |
|------|------|---------|---------|
| 40001 | 400 | INVALID_PAYLOAD | 检查请求字段格式 |
| 40101 | 401 | INVALID_CREDENTIALS | 账号或密码错误，建议增加防爆破计数 |
| 40301 | 403 | ACCOUNT_LOCKED | 账户被锁定，引导走找回流程 |
| 42901 | 429 | TOO_MANY_ATTEMPTS | 触发风控，需要 captcha_token |
| 50001 | 500 | INTERNAL_ERROR | 服务端异常，已上报告警 |

## POST /api/v1/auth/refresh

使用 refresh token 换取新的 token 对，**旧的 refresh token 立即失效**（旋转策略）。

### 请求参数

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `refresh_token` | string | 是 | 上次签发的 refresh token |
| `device_id` | string | 否 | 必须与登录时一致，否则拒绝 |

### 请求示例

```bash
curl -X POST https://api.example.com/api/v1/auth/refresh \
  -H "Content-Type: application/json" \
  -d '{"refresh_token": "eyJ..."}'
```

### 响应示例

响应结构与 `/login` 相同，返回新的 access + refresh token 对。

### 错误码

| code | HTTP | message | 处理建议 |
|------|------|---------|---------|
| 40102 | 401 | INVALID_REFRESH | refresh token 已过期或被废弃 |
| 40103 | 401 | DEVICE_MISMATCH | device_id 与登录时不一致 |
| 40104 | 401 | TOKEN_REUSED | 检测到 refresh token 被重复使用，已强制登出所有设备 |

## POST /api/v1/auth/logout

主动登出，将当前 refresh token 加入黑名单。

### 请求参数

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `refresh_token` | string | 是 | 待废弃的 refresh token |
| `logout_all_devices` | boolean | 否 | true 时废弃该用户所有设备的 token |

### 请求示例

```bash
curl -X POST https://api.example.com/api/v1/auth/logout \
  -H "Authorization: Bearer <access_token>" \
  -H "Content-Type: application/json" \
  -d '{"refresh_token": "eyJ...", "logout_all_devices": false}'
```

### 响应示例

```json
{ "code": 0, "data": { "revoked_count": 1 } }
```

## Token 安全实践

### Refresh Token 旋转

每次调用 `/refresh` 都会：

1. 校验旧 refresh token 签名与黑名单状态。
2. 将旧 token 加入黑名单（保留至原过期时间）。
3. 签发新的 access + refresh token 对。
4. 在 Redis 记录新旧 token 的派生关系，用于检测重放攻击。

如果检测到一个**已被使用过的 refresh token 再次被提交**，意味着 token 可能已泄漏，服务端会**立即废弃该用户所有 refresh token**，强制所有设备重新登录。

### 客户端存储建议

- **Web**：access token 存内存（避免 XSS），refresh token 存 `HttpOnly + Secure + SameSite=Strict` 的 Cookie。
- **Mobile**：access token 存内存，refresh token 存系统 Keychain / Keystore。
- **避免**：localStorage 存 token、URL 参数传 token。

## 常见踩坑

### 1. Refresh 接口的幂等问题

客户端在弱网环境下可能重发 refresh 请求，但由于 token 旋转策略，第二次请求会失败并触发「TOKEN_REUSED」全量登出。

**解决方案**：客户端必须使用本地锁保证 refresh 请求**串行**执行，并对网络错误做 3 秒去抖。详细模式参考 [patterns/retry](../../patterns/retry.md) 中的「请求合并」一节。

### 2. 时钟漂移导致 access token 提前过期

网关与签发服务的服务器时钟差异大于 access token 有效期的 1% 时，会出现 token 已签发但立即失效的现象。

**解决方案**：

- 所有签发与校验节点强制 NTP 同步，漂移阈值 < 200ms。
- JWT 校验时增加 60 秒 `clock_skew` 容忍窗口。

### 3. 黑名单 Redis 故障的降级策略

如果 Redis 不可用，黑名单检查会失败。当前降级策略：

- **登出请求**：直接返回 200，依赖客户端清理本地 token（安全级别降低，仅适用于非高敏业务）。
- **校验请求**：跳过黑名单检查，仅依赖 JWT 签名与过期时间（接受 access token 的短时效兜底风险）。

高敏业务（支付、改密码）需要在网关层显式开启 `strict_revocation` 模式，Redis 不可用时直接拒绝请求。

## 关联文档

- [patterns/retry](../../patterns/retry.md) — 重试与幂等设计
- [patterns/rate-limit](../../patterns/rate-limit.md) — 登录接口限流策略
- `api/order/checkout` — 下单接口的鉴权要求
