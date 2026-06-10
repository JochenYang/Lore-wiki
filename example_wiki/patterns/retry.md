---
title: 重试与幂等设计模式
module: patterns
tags: [retry, idempotency, backoff, jitter, resilience]
owner: platform-team
last_review: 2026-05-15
---

# 重试与幂等设计模式

重试是分布式系统中最常用也最容易用错的容错机制。本文档总结团队在订单、支付、消息等业务中沉淀的重试规范，包括退避算法、幂等保证、反模式与典型踩坑。

## 何时该重试

并非所有错误都应该重试。错误必须满足以下两个条件之一：

1. **瞬时性错误**：网络抖动、连接超时、5xx 服务端错误、数据库锁等待超时。
2. **幂等接口的不确定状态**：客户端不知道服务端是否处理成功，但接口已设计为幂等。

**禁止重试** 的场景：

| 错误类型 | 原因 |
|---------|------|
| 4xx 客户端错误（除 408、429） | 参数本身错误，重试也无法成功 |
| 业务校验失败（库存不足、余额不够） | 业务语义明确，重试浪费资源 |
| 非幂等的写接口且无 idempotency key | 重试会导致重复执行 |
| 鉴权失败（401、403） | 凭证问题，重试只会触发风控 |

## 退避算法

### 固定间隔

最简单但最差的选择。所有客户端在故障恢复瞬间同时重试，会形成 **「重试风暴」（thundering herd）**，二次击垮刚恢复的服务。

```python
for attempt in range(max_retries):
    try:
        return call()
    except RetryableError:
        time.sleep(1)  # 永远不要这么写
```

### 指数退避（Exponential Backoff）

每次重试间隔成倍增长，避免风暴：

```python
delay = base * (2 ** attempt)
# attempt=0 → 100ms, attempt=1 → 200ms, attempt=2 → 400ms ...
```

但仍有问题：所有客户端的退避曲线相同，故障恢复瞬间仍会集中。

### 指数退避 + 抖动（Jitter）

在退避时间上叠加随机抖动，将重试时刻打散：

```python
import random

def backoff_with_jitter(attempt: int, base: float = 0.1, cap: float = 30.0) -> float:
    """Full jitter 退避：[0, min(cap, base * 2^attempt)) 之间随机"""
    expo = min(cap, base * (2 ** attempt))
    return random.uniform(0, expo)
```

`Full Jitter`（AWS 推荐）是工程上最稳的选择，本团队所有服务必须使用此策略。

### 退避参数建议

| 场景 | base | cap | max_retries |
|------|------|-----|-------------|
| 内部服务调用（同 IDC） | 50ms | 2s | 3 |
| 跨 IDC 调用 | 100ms | 5s | 3 |
| 外部第三方 API | 500ms | 30s | 5 |
| 异步消息消费 | 1s | 5min | 10（结合死信队列） |

## 幂等设计

重试的前提是接口幂等。常见的幂等保证方式：

### 1. 天然幂等

`GET`、`PUT`（替换语义）、`DELETE` 天然幂等。`POST` 与 `PATCH` 默认非幂等，需要额外设计。

### 2. Idempotency-Key 模式

客户端为每次逻辑请求生成唯一 key，服务端在窗口期内重复请求返回首次结果。

```python
def checkout(user_id: str, idem_key: str, payload: dict) -> dict:
    cache_key = f"idem:{user_id}:{idem_key}"
    cached = redis.get(cache_key)
    if cached:
        return json.loads(cached)
    result = do_checkout(user_id, payload)
    redis.set(cache_key, json.dumps(result), ex=86400)
    return result
```

完整实现参考 [api/order/checkout](../api/order/checkout.md) 中的「幂等设计」一节。

### 3. 唯一键约束

依赖数据库唯一索引，重复插入被自动拒绝：

```sql
CREATE UNIQUE INDEX idx_payment_request ON payments(request_id);
-- 重复 INSERT 触发 UNIQUE 约束异常，应用层捕获后返回已存在记录
```

### 4. 状态机校验

写操作前校验当前状态，状态不匹配则跳过：

```python
def confirm_order(order_id: str):
    with db.transaction():
        order = db.select_for_update("SELECT * FROM orders WHERE id = ?", order_id)
        if order.status == 'confirmed':
            return order  # 已确认，重复调用直接返回
        if order.status != 'pending':
            raise InvalidStateError(f"cannot confirm from {order.status}")
        db.update("UPDATE orders SET status='confirmed' WHERE id = ?", order_id)
```

## 反模式

### 反模式 1：层层叠加重试

```
Client (retry 3x) → Gateway (retry 3x) → ServiceA (retry 3x) → ServiceB
```

下游一次故障，会被上游放大 **27 倍** 流量，雪崩。

**正确做法**：只在最外层（客户端或网关）做重试，内部调用 **失败即返回**。

### 反模式 2：不区分错误类型

```python
try:
    call()
except Exception:  # 错的
    retry()
```

任何异常都重试，包括 `InvalidArgumentError` 这种永远不会成功的错误。

**正确做法**：定义明确的 `RetryableError` 基类，只重试该基类异常。

### 反模式 3：无熔断的重试

依赖服务彻底挂掉时，重试只是在浪费资源、增加延迟。

**正确做法**：重试必须配合熔断器（如 `resilience4j`、`pybreaker`），熔断打开时直接快速失败。

### 反模式 4：长尾请求重试

请求已经耗时 10 秒（接近超时），失败后立即重试，下游可能仍在处理上一次请求，导致并发倍增。

**正确做法**：

- 重试前等待至少 `original_timeout × 0.5` 时间。
- 配合 hedged request（同时发出多个并取最快响应）时，需要在所有非首次响应到达时主动取消。

## 请求合并（Request Coalescing）

针对短时间内对同一资源的并发请求，可以合并为一次调用：

```python
class RequestCoalescer:
    def __init__(self):
        self._inflight: dict[str, Future] = {}
        self._lock = threading.Lock()
    
    def call(self, key: str, fn: Callable):
        with self._lock:
            if key in self._inflight:
                return self._inflight[key].result()  # 复用进行中的调用
            future = executor.submit(fn)
            self._inflight[key] = future
        try:
            return future.result()
        finally:
            with self._lock:
                self._inflight.pop(key, None)
```

典型应用：登录 Token 刷新。客户端在弱网下可能并发发起多次 refresh，本地合并后保证只有一次真正打到服务端，避免触发 [api/user/auth](../api/user/auth.md) 中的 `TOKEN_REUSED` 全量登出。

## 定时对账

对于「预扣 → 确认」类的两阶段操作，必须有兜底任务清理悬挂状态：

```python
def reconcile_inventory():
    """每 5 分钟扫描超过 30 分钟未确认的库存预扣，自动回滚"""
    candidates = db.query("""
        SELECT i.sku_id, i.reserved_quantity, i.order_id
        FROM inventory_reservations i
        LEFT JOIN orders o ON o.id = i.order_id
        WHERE i.created_at < NOW() - INTERVAL 30 MINUTE
          AND (o.id IS NULL OR o.status IN ('failed', 'cancelled'))
    """)
    for r in candidates:
        try:
            rollback_reservation(r.sku_id, r.reserved_quantity, r.order_id)
            log.info("rollback succeeded", extra=r._asdict())
        except Exception as e:
            log.error("rollback failed, will retry next round", exc_info=e)
```

对账任务本身必须 **幂等**：重复执行不会重复回滚。这是分布式系统最终一致性的最后一道防线。

## 常见踩坑

### 1. 重试导致重复扣款

支付场景中，HTTP 超时但实际已扣款，客户端重试导致用户被扣两次。

**修复**：

- 强制使用 `Idempotency-Key`。
- 超时不要立即重试，先调用「查询订单状态」接口确认真实结果。

### 2. 退避时间超过调用方超时

设置了 `cap=60s` 的退避，但调用方上游超时只有 10 秒，导致重试还没发出就已经超时返回。

**修复**：退避总时间必须 < 调用方超时的 70%。建议使用「截止时间传播」（deadline propagation）模式：

```python
def call_with_deadline(deadline: float):
    while time.time() < deadline:
        try:
            timeout_left = deadline - time.time()
            return call(timeout=min(timeout_left, 3.0))
        except RetryableError:
            backoff = min(backoff_with_jitter(attempt), deadline - time.time() - 0.1)
            if backoff <= 0:
                raise DeadlineExceededError()
            time.sleep(backoff)
```

### 3. 消息重试堵塞死信队列

消费失败的消息全部进入死信队列，但死信队列没有消费者，导致堆积无限增长。

**修复**：

- 死信队列必须有独立的消费者（人工介入或自动转移到归档存储）。
- 设置死信队列长度告警，超过阈值触发 PagerDuty。

## 关联文档

- [api/order/checkout](../api/order/checkout.md) — Idempotency-Key 实现示例
- [api/user/auth](../api/user/auth.md) — Token 刷新的请求合并案例
- [patterns/rate-limit](rate-limit.md) — 限流与重试的协同
