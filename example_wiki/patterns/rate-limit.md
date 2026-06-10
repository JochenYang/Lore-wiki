---
title: 限流方案设计
module: patterns
tags: [rate-limit, token-bucket, leaky-bucket, redis, distributed]
owner: platform-team
last_review: 2026-05-22
---

# 限流方案设计

限流是保护后端服务的第一道防线，用于防止突发流量打挂下游、防止恶意刷单、以及实现 SLA 配额管理。本文档对比常用算法、给出工程实现、并说明在网关层与应用层的不同选型。

## 算法选型

### 固定窗口（Fixed Window）

将时间切成固定窗口，每个窗口内独立计数：

```
[12:00:00 ~ 12:00:59]  count = 0
[12:01:00 ~ 12:01:59]  count = 0
```

**优点**：实现简单，仅需一个计数器 + 一个 TTL。
**缺点**：窗口边界处会出现**双倍突发**。例如限制 100 req/min，攻击者可在 12:00:59 发 100 个，12:01:00 再发 100 个，1 秒内承受 200 次。

**适用场景**：对精度不敏感的低频接口（如发短信验证码）。

### 滑动窗口（Sliding Window）

将固定窗口切成更细的子窗口，加权统计当前窗口：

```
count(now) = count(current_minute) + count(previous_minute) × (1 - elapsed_ratio)
```

**优点**：平滑度更好，避免边界突发。
**缺点**：实现略复杂，仍存在「平均限速」与「瞬时峰值」的偏差。

**适用场景**：网关层通用限流，精度要求中等。

### 令牌桶（Token Bucket）

桶以固定速率生成令牌，每次请求消耗一个令牌，桶空时拒绝：

```
bucket_size = 100        # 桶容量（允许的突发量）
refill_rate = 10 / sec   # 每秒补充 10 个令牌
```

**优点**：

- 允许突发流量（最大突发 = 桶容量）。
- 平均速率可控（= 补充速率）。
- 实现可分布式（Redis Lua）。

**缺点**：实现需要原子操作，单机简单分布式略复杂。

**适用场景**：API 网关、用户级限流。**推荐为默认选型**。

### 漏桶（Leaky Bucket）

请求进入桶后以固定速率漏出，超过桶容量时拒绝：

```
请求 → [桶] → 固定速率处理
```

**优点**：输出速率绝对平滑，不允许任何突发。
**缺点**：不能应对正常的突发请求，用户体验差（合法的瞬时高峰也被拒）。

**适用场景**：对下游负载有严格保护要求的场景（如调用第三方付费 API，必须按合同 QPS 调用）。

## 令牌桶 Redis 实现

分布式场景下，令牌桶通过 Redis Lua 脚本实现原子性：

```lua
-- KEYS[1] = bucket_key
-- ARGV[1] = bucket_capacity, ARGV[2] = refill_rate, ARGV[3] = now_ms, ARGV[4] = cost
local key = KEYS[1]
local capacity = tonumber(ARGV[1])
local rate = tonumber(ARGV[2])        -- tokens per second
local now = tonumber(ARGV[3])
local cost = tonumber(ARGV[4])

local data = redis.call('HMGET', key, 'tokens', 'last_refill')
local tokens = tonumber(data[1]) or capacity
local last = tonumber(data[2]) or now

-- 按时间差补充令牌
local delta = math.max(0, now - last)
tokens = math.min(capacity, tokens + delta * rate / 1000)

local allowed = 0
if tokens >= cost then
    tokens = tokens - cost
    allowed = 1
end

redis.call('HMSET', key, 'tokens', tokens, 'last_refill', now)
redis.call('PEXPIRE', key, math.ceil(capacity / rate * 1000) * 2)

return {allowed, tokens}
```

调用方：

```python
import time
import redis

class TokenBucketLimiter:
    def __init__(self, client: redis.Redis, script_sha: str):
        self.client = client
        self.script_sha = script_sha
    
    def allow(self, key: str, capacity: int, rate: float, cost: int = 1) -> bool:
        result = self.client.evalsha(
            self.script_sha, 1, key,
            capacity, rate, int(time.time() * 1000), cost
        )
        return result[0] == 1
```

## 分布式限流的挑战

### 1. Redis 单点性能瓶颈

单 Redis 实例约 8 万 QPS。当限流 QPS 接近 Redis 上限时，限流器自身成为瓶颈。

**解决方案**：

- **分片**：按用户 ID hash 到多个 Redis 实例。
- **本地预扣**：每个应用实例从 Redis 一次性取 N 个令牌，本地消耗完再请求下一批。延迟 ↓，精度 ↓。
- **多级限流**：网关层粗粒度（全局保护），应用层细粒度（业务限制）。

### 2. Redis 故障的降级策略

Redis 不可用时，限流器必须降级：

| 策略 | 优点 | 缺点 |
|------|------|------|
| **Fail Open**（放行） | 用户体验好 | 下游可能被打挂 |
| **Fail Closed**（拒绝） | 保护下游 | 误伤合法用户 |
| **本地回落**（本机内存计数） | 折衷 | 精度差，多实例无协同 |

本团队默认策略：**Fail Open + 本地回落**，并在监控告警中标记「限流降级中」。高敏接口（支付、下单）显式开启 Fail Closed。

### 3. 时钟漂移

Redis 用 `redis.call('TIME')` 获取时间还是用客户端时间？

- **客户端时间**：性能好，但客户端时钟漂移会导致限流不准。
- **Redis TIME**：精度高，但每次调用多一次网络往返。

**当前选型**：使用客户端时间，但在网关层强制 NTP 同步（漂移 < 50ms）。

## 网关层 vs 应用层

### 网关层限流

- **粒度**：IP、用户、API 路径。
- **目标**：拦截恶意流量、保护整体集群。
- **实现**：Nginx Lua、Kong 插件、Envoy filter、自研 API Gateway。

### 应用层限流

- **粒度**：用户 + 业务维度（如「单用户每分钟下单 ≤ 10」）。
- **目标**：业务规则保护、防刷单。
- **实现**：拦截器 + Redis 令牌桶。

**两层必须配合使用**，单层不够：

- 只有网关层：业务规则无法表达（网关不知道「下单」与「查询」的差异）。
- 只有应用层：恶意流量已经打到应用，浪费连接池与 CPU。

## 限流维度示例

下面是下单接口（参考 [api/order/checkout](../api/order/checkout.md)）的完整限流配置：

| 维度 | 阈值 | 实现位置 | 说明 |
|------|------|---------|------|
| 全局 | 10000 QPS | 网关层 | 保护订单服务集群 |
| 单 IP | 100 QPS | 网关层 | 防 DDoS |
| 单用户 | 10 req/min | 应用层 | 防刷单 |
| 单 SKU | 5000 QPS | 应用层 | 热门商品的库存服务保护 |
| 单优惠券 | 1000 QPS | 应用层 | 秒杀场景的优惠券核销限流 |

## 限流触发后的响应

限流响应必须给客户端足够的信息以正确重试：

```http
HTTP/1.1 429 Too Many Requests
Content-Type: application/json
Retry-After: 5
X-RateLimit-Limit: 10
X-RateLimit-Remaining: 0
X-RateLimit-Reset: 1717249320

{
  "code": 42901,
  "message": "RATE_LIMITED",
  "detail": "user-level rate limit exceeded",
  "retry_after_seconds": 5
}
```

关键 header：

- `Retry-After`：建议的重试等待秒数（客户端应配合 [patterns/retry](retry.md) 的退避算法）。
- `X-RateLimit-*`：当前限流配额信息，便于客户端展示给用户。

## 常见踩坑

### 1. 限流维度过粗导致误伤

按「用户 + 接口」限流，但接口内部分支逻辑差异大。例如 `/api/data/query`，简单查询消耗 1 个令牌即可，复杂聚合查询应消耗 10 个令牌。

**解决方案**：在业务层根据请求复杂度动态调整 `cost`：

```python
cost = 1
if request.has_aggregation:
    cost = 5
if request.time_range_days > 30:
    cost *= 2
limiter.allow(f"user:{user_id}:query", capacity=100, rate=10, cost=cost)
```

### 2. 突发流量被限制后客户端集体重试

限流触发后，客户端在 `Retry-After` 秒后**同时**重试，形成第二波流量峰值。

**解决方案**：

- `Retry-After` 返回 **[base, 2×base]** 范围的随机值。
- 客户端必须叠加 jitter（参考 [patterns/retry](retry.md)）。

### 3. 限流计数器内存膨胀

按用户 + 接口限流时，键空间 = 用户数 × 接口数。1000 万用户 × 100 接口 = 10 亿键。

**解决方案**：

- 所有限流键设置 TTL（一般 = 窗口大小 × 2）。
- 不为冷用户预创建键，按需懒加载。
- 监控 Redis 内存使用，超阈值触发清理。

### 4. 限流配置变更需要瞬时生效

老方案：限流配置写在代码里，改完要发版。
新方案：限流配置存配置中心（Apollo / Nacos），监听变更事件实时更新。

**注意事项**：

- 配置变更需要灰度发布，避免误配置打挂集群（如把 10000 QPS 误写成 10）。
- 配置变更需有审计日志，可追溯责任人。

## 关联文档

- [patterns/retry](retry.md) — 限流触发后的重试策略
- [api/order/checkout](../api/order/checkout.md) — 下单接口的完整限流配置示例
- [api/user/auth](../api/user/auth.md) — 登录接口的限流策略
