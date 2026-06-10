---
title: 订单下单 API
module: api/order
tags: [order, checkout, idempotency, inventory, coupon]
owner: order-team
last_review: 2026-06-01
---

# 订单下单 API

下单接口是订单服务最核心也是最容易踩坑的入口。本文档描述 `POST /api/v1/orders/checkout` 的完整调用契约、内部处理流程、库存与优惠券一致性保证、以及典型的并发与幂等问题。

## 设计概览

下单流程涉及 5 个上游依赖：

1. **商品服务**：校验商品上下架状态、获取最新价格。
2. **库存服务**：预扣库存，原子性扣减。
3. **优惠券服务**：核销优惠券，幂等扣减。
4. **风控服务**：判断订单是否需要人工审核。
5. **支付服务**：生成预支付订单号，前端拉起支付。

整个流程必须是 **幂等的**，调用方通过 `Idempotency-Key` 头部保证同一笔逻辑订单只会创建一次。库存与优惠券的扣减通过**本地消息表 + 异步补偿**实现最终一致性。

## POST /api/v1/orders/checkout

创建订单并返回支付预订单号。

### 请求头

| Header | 必填 | 说明 |
|--------|------|------|
| `Authorization` | 是 | Bearer access_token，鉴权见 [api/user/auth](../user/auth.md) |
| `Idempotency-Key` | 是 | 客户端生成的 UUID v4，**24 小时内重复提交返回首次结果** |
| `X-Request-Id` | 否 | 链路追踪 ID，未提供时由网关生成 |

### 请求参数

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `items` | array | 是 | 商品列表，最多 50 个 SKU |
| `items[].sku_id` | string | 是 | SKU 唯一标识 |
| `items[].quantity` | integer | 是 | 购买数量，1 ≤ quantity ≤ 999 |
| `coupon_ids` | array<string> | 否 | 使用的优惠券 ID 列表，最多 3 张 |
| `address_id` | string | 是 | 收货地址 ID |
| `payment_method` | string | 是 | `alipay` / `wechat` / `unionpay` |
| `remark` | string | 否 | 买家留言，最长 200 字符 |

### 请求示例

```bash
curl -X POST https://api.example.com/api/v1/orders/checkout \
  -H "Authorization: Bearer eyJ..." \
  -H "Idempotency-Key: 7f3a4e8c-1b2d-4c5e-9a0b-1c2d3e4f5a6b" \
  -H "Content-Type: application/json" \
  -d '{
    "items": [
      {"sku_id": "sku_001", "quantity": 2},
      {"sku_id": "sku_002", "quantity": 1}
    ],
    "coupon_ids": ["cp_8821"],
    "address_id": "addr_123",
    "payment_method": "alipay",
    "remark": "请尽快发货"
  }'
```

### 响应示例

```json
{
  "code": 0,
  "data": {
    "order_id": "ord_2026060112345678",
    "total_amount": 19800,
    "discount_amount": 2000,
    "payable_amount": 17800,
    "currency": "CNY",
    "pay_url": "https://pay.example.com/qr/abc123",
    "pay_expires_at": "2026-06-01T12:30:00Z",
    "items": [
      {"sku_id": "sku_001", "quantity": 2, "unit_price": 5000, "subtotal": 10000},
      {"sku_id": "sku_002", "quantity": 1, "unit_price": 9800, "subtotal": 9800}
    ]
  }
}
```

金额字段单位为**分**，避免浮点精度问题。

### 错误码

| code | HTTP | message | 处理建议 |
|------|------|---------|---------|
| 40001 | 400 | INVALID_PAYLOAD | 参数校验失败 |
| 40010 | 400 | SKU_OFFLINE | 商品已下架，需移除该 SKU |
| 40011 | 400 | COUPON_INVALID | 优惠券不可用（过期/不满足门槛） |
| 40012 | 400 | ADDRESS_INVALID | 地址不存在或不在配送范围 |
| 40901 | 409 | INSUFFICIENT_STOCK | 库存不足，响应体含可售数量 |
| 40902 | 409 | IDEMPOTENCY_KEY_CONFLICT | 相同 key 但参数不一致 |
| 42901 | 429 | RATE_LIMITED | 用户触发下单限流，参考 [patterns/rate-limit](../../patterns/rate-limit.md) |
| 50301 | 503 | INVENTORY_SERVICE_DOWN | 库存服务不可用，建议客户端 3 秒后重试 |

## 内部处理流程

下单接口的内部时序如下，所有步骤均有 **5 秒级联超时** 保护：

```
Client → Gateway → OrderService
                       │
                       ├─ (1) 校验 Idempotency-Key（Redis SETNX）
                       ├─ (2) 商品服务：批量查询 SKU 信息
                       ├─ (3) 优惠券服务：预占（不扣减）
                       ├─ (4) 库存服务：预扣（原子 DECR）
                       ├─ (5) 计算金额（含优惠规则引擎）
                       ├─ (6) 风控服务：异步判断（不阻塞主流程）
                       ├─ (7) 写订单表 + 本地消息表（一个事务）
                       └─ (8) 调用支付服务生成预支付订单
```

任意步骤失败都会触发**反向补偿**：

- 步骤 4 后失败 → 调用库存服务回滚预扣。
- 步骤 3 后失败 → 调用优惠券服务释放预占。
- 全部成功后异步发送 `order.created` 事件，下游消费方负责后续流程。

## 幂等设计

### Idempotency-Key 机制

客户端为每一次「逻辑下单」生成唯一 key（建议 UUID v4），服务端在 Redis 中以 `idem:checkout:{user_id}:{key}` 为键存储 24 小时。

**首次请求**：

1. `SETNX idem:checkout:u_8821:7f3a... "pending"` → 成功，继续处理。
2. 处理完成后，将结果序列化写入相同 key，TTL 24 小时。

**重复请求**：

1. `SETNX` 失败，读取已有值。
2. 若为 `"pending"`：返回 `40902` 提示客户端稍后重试（典型场景：弱网重发，前次请求仍在处理）。
3. 若为序列化结果：**直接返回首次结果**，不重新创建订单。

### 参数一致性校验

重复请求必须携带**完全相同**的 body，否则返回 `40902 IDEMPOTENCY_KEY_CONFLICT`，避免客户端逻辑错误导致幂等被利用。

校验方式：对 body 计算 SHA256，与首次请求的哈希值对比。

## 库存一致性

### 预扣 + 异步回滚

库存采用**预扣模式**：

1. **下单时**：库存服务原子扣减 `available_stock`，同时增加 `reserved_stock`。
2. **支付成功**：扣减 `reserved_stock`，订单状态变为「已支付」。
3. **支付超时（15 分钟）**：定时任务回滚 `reserved_stock` 到 `available_stock`。

### 超卖防御

库存扣减使用 Redis Lua 脚本保证原子性：

```lua
-- 入参：KEYS[1] = stock_key, ARGV[1] = quantity
local stock = tonumber(redis.call('GET', KEYS[1]))
if not stock or stock < tonumber(ARGV[1]) then
  return -1  -- 库存不足
end
redis.call('DECRBY', KEYS[1], ARGV[1])
return stock - tonumber(ARGV[1])
```

DB 层额外加 **乐观锁**（`UPDATE ... WHERE version = ?`）双重保险，防止 Redis 故障期间的超卖。

## 常见踩坑

### 1. Idempotency-Key 长度无限制导致 Redis OOM

早期版本未对 key 长度做校验，被恶意客户端用 4KB key 灌爆 Redis。

**修复**：在网关层强制 key 长度 ≤ 64 字符，超长直接 400。

### 2. 库存预扣后服务崩溃导致库存悬挂

订单服务在步骤 4 成功后崩溃，步骤 7 未执行，库存被预扣但订单未生成。

**修复**：

- 步骤 4 写入 Redis 时附带 `order_id` 占位符与 30 分钟 TTL。
- 后台任务扫描「预扣存在但无对应订单」的记录，自动回滚。
- 详细补偿模式参考 [patterns/retry](../../patterns/retry.md) 中的「定时对账」一节。

### 3. 优惠券与库存的扣减顺序

如果先扣库存再扣优惠券，且优惠券扣减失败，需要回滚库存，但回滚本身可能失败（网络抖动），造成库存丢失。

**当前策略**：

- 优惠券先 **预占**（不扣减），库存扣减成功后再确认核销。
- 优惠券核销失败 → 整单失败，库存通过本地消息表异步回滚（保证最终一致）。

### 4. 下单接口的限流维度

- **全局**：保护订单服务整体不被打挂，1 万 QPS。
- **用户级**：单用户 10 次/分钟，防止刷单。
- **SKU 级**：热门 SKU 5 千 QPS，防止单品压垮库存服务。

限流实现参考 [patterns/rate-limit](../../patterns/rate-limit.md)。

## 关联文档

- [api/user/auth](../user/auth.md) — 下单接口的鉴权要求
- [patterns/retry](../../patterns/retry.md) — 库存回滚的重试策略
- [patterns/rate-limit](../../patterns/rate-limit.md) — 下单限流配置
