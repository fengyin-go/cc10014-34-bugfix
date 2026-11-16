"""接口出入参模型：列表分页、动作结果与各模块的明细结构。"""
from __future__ import annotations

from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class PageResult(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int = 1
    size: int = 20


class ActionResult(BaseModel):
    ok: bool
    message: str
    entry: dict[str, Any] | None = None


class EntryPayload(BaseModel):
    """登记或修改一条业务记录时提交的字段集合。

    兼容两种调用方式：字段包在 ``values`` 里，或者直接把字段放在顶层
    （页面上的动作按钮就是把 ``{"action": "停用监控"}`` 直接发给接口的）。
    """

    model_config = ConfigDict(extra="allow")

    values: dict[str, Any] = Field(default_factory=dict)
    remark: str | None = None

    def fields(self) -> dict[str, Any]:
        extras = dict(self.model_extra or {})
        extras.update(self.values)
        return extras

    def action(self) -> str:
        return str(self.fields().get("action") or "").strip()



class ServiceEntry(BaseModel):
    """数据服务明细结构。"""

    field_0: str | None = None  # 服务编号
    field_1: str | None = None  # 服务名称
    field_2: str | None = None  # 数据来源
    field_3: str | None = None  # 查询模板
    field_4: str | None = None  # 返回字段
    field_5: str | None = None  # 缓存秒数
    field_6: str | None = None  # 允许并发
    field_7: str | None = None  # 版本号

class FlowEntry(BaseModel):
    """编排流程明细结构。"""

    field_0: str | None = None  # 流程编号
    field_1: str | None = None  # 流程名称
    field_2: str | None = None  # 步骤序列
    field_3: str | None = None  # 数据依赖
    field_4: str | None = None  # 失败回退
    field_5: str | None = None  # 超时秒数
    field_6: str | None = None  # 并行度
    field_7: str | None = None  # 结果合并

class RatelimitEntry(BaseModel):
    """限流规则明细结构。"""

    field_0: str | None = None  # 规则编号
    field_1: str | None = None  # 关联服务
    field_2: str | None = None  # 每秒上限
    field_3: str | None = None  # 突发容量
    field_4: str | None = None  # 限流算法
    field_5: str | None = None  # 拒绝响应
    field_6: str | None = None  # 降级服务
    field_7: str | None = None  # 生效时段

class AuthEntry(BaseModel):
    """鉴权配置明细结构。"""

    field_0: str | None = None  # 配置编号
    field_1: str | None = None  # 关联服务
    field_2: str | None = None  # 鉴权方式
    field_3: str | None = None  # 密钥标识
    field_4: str | None = None  # 有效期天数
    field_5: str | None = None  # IP白名单
    field_6: str | None = None  # 调用上限
    field_7: str | None = None  # 请求签名

class MonitorEntry(BaseModel):
    """监控指标明细结构。"""

    field_0: str | None = None  # 指标编号
    field_1: str | None = None  # 关联服务
    field_2: str | None = None  # QPS阈值
    field_3: str | None = None  # 延迟阈值
    field_4: str | None = None  # 错误率阈值
    field_5: str | None = None  # 告警级别
    field_6: str | None = None  # 通知渠道
    field_7: str | None = None  # 静默分钟

class ConsumerEntry(BaseModel):
    """消费应用明细结构。"""

    field_0: str | None = None  # 应用编号
    field_1: str | None = None  # 应用名称
    field_2: str | None = None  # 订阅服务
    field_3: str | None = None  # 调用频率
    field_4: str | None = None  # 最大QPS
    field_5: str | None = None  # 联系人
    field_6: str | None = None  # 到期日期
    field_7: str | None = None  # 状态

class VersionEntry(BaseModel):
    """版本记录明细结构。"""

    field_0: str | None = None  # 版本号
    field_1: str | None = None  # 关联服务
    field_2: str | None = None  # 变更描述
    field_3: str | None = None  # 兼容性标识
    field_4: str | None = None  # 灰度比例
    field_5: str | None = None  # 回滚脚本
    field_6: str | None = None  # 发布时间
    field_7: str | None = None  # 操作人

class CacheEntry(BaseModel):
    """缓存策略明细结构。"""

    field_0: str | None = None  # 策略编号
    field_1: str | None = None  # 关联服务
    field_2: str | None = None  # 缓存键模板
    field_3: str | None = None  # 过期秒数
    field_4: str | None = None  # 淘汰算法
    field_5: str | None = None  # 预热策略
    field_6: str | None = None  # 命中率阈值
    field_7: str | None = None  # 最大条目

class TransformEntry(BaseModel):
    """转换模板明细结构。"""

    field_0: str | None = None  # 模板编号
    field_1: str | None = None  # 关联服务
    field_2: str | None = None  # 输入字段
    field_3: str | None = None  # 输出字段
    field_4: str | None = None  # 格式转换
    field_5: str | None = None  # 默认填充
    field_6: str | None = None  # 数组展开
    field_7: str | None = None  # 嵌套打平

class GatewayEntry(BaseModel):
    """路由规则明细结构。"""

    field_0: str | None = None  # 规则编号
    field_1: str | None = None  # 路径前缀
    field_2: str | None = None  # 目标服务
    field_3: str | None = None  # 重写规则
    field_4: str | None = None  # 超时秒数
    field_5: str | None = None  # 熔断阈值
    field_6: str | None = None  # 重试次数
    field_7: str | None = None  # 负载策略

class SchemaEntry(BaseModel):
    """接口定义明细结构。"""

    field_0: str | None = None  # 定义编号
    field_1: str | None = None  # 关联服务
    field_2: str | None = None  # 请求方法
    field_3: str | None = None  # 参数列表
    field_4: str | None = None  # 响应示例
    field_5: str | None = None  # 错误码说明
    field_6: str | None = None  # 调用示例
    field_7: str | None = None  # 文档版本

class DatasourceEntry(BaseModel):
    """数据源连接明细结构。"""

    field_0: str | None = None  # 连接编号
    field_1: str | None = None  # 连接类型
    field_2: str | None = None  # 接入地址
    field_3: str | None = None  # 认证方式
    field_4: str | None = None  # 连接池大小
    field_5: str | None = None  # 超时秒数
    field_6: str | None = None  # 重试上限
    field_7: str | None = None  # 负责人

class QueryEntry(BaseModel):
    """查询定义明细结构。"""

    field_0: str | None = None  # 定义编号
    field_1: str | None = None  # 关联数据源
    field_2: str | None = None  # 查询模板
    field_3: str | None = None  # 参数占位
    field_4: str | None = None  # 结果字段
    field_5: str | None = None  # 排序规则
    field_6: str | None = None  # 分页大小
    field_7: str | None = None  # 超时秒数

class CleanseEntry(BaseModel):
    """清洗规则明细结构。"""

    field_0: str | None = None  # 规则编号
    field_1: str | None = None  # 关联数据集
    field_2: str | None = None  # 空值策略
    field_3: str | None = None  # 格式校验
    field_4: str | None = None  # 异常过滤
    field_5: str | None = None  # 去重字段
    field_6: str | None = None  # 规则版本
    field_7: str | None = None  # 生效日期

class LogEntry(BaseModel):
    """日志记录明细结构。"""

    field_0: str | None = None  # 记录编号
    field_1: str | None = None  # 调用服务
    field_2: str | None = None  # 请求时间
    field_3: str | None = None  # 响应耗时
    field_4: str | None = None  # 返回码
    field_5: str | None = None  # 调用方IP
    field_6: str | None = None  # 请求大小KB
    field_7: str | None = None  # 响应大小KB

class MockEntry(BaseModel):
    """模拟规则明细结构。"""

    field_0: str | None = None  # 规则编号
    field_1: str | None = None  # 关联服务
    field_2: str | None = None  # 触发条件
    field_3: str | None = None  # 响应模板
    field_4: str | None = None  # 延迟毫秒
    field_5: str | None = None  # 错误率模拟
    field_6: str | None = None  # 数据变异
    field_7: str | None = None  # 启用标识

class BackupEntry(BaseModel):
    """备份策略明细结构。"""

    field_0: str | None = None  # 策略编号
    field_1: str | None = None  # 目标服务
    field_2: str | None = None  # 备份周期
    field_3: str | None = None  # 保留份数
    field_4: str | None = None  # 存储介质
    field_5: str | None = None  # 加密开关
    field_6: str | None = None  # 恢复演练
    field_7: str | None = None  # 过期清理

class NotifyEntry(BaseModel):
    """通知规则明细结构。"""

    field_0: str | None = None  # 规则编号
    field_1: str | None = None  # 触发事件
    field_2: str | None = None  # 通知渠道
    field_3: str | None = None  # 接收列表
    field_4: str | None = None  # 消息模板
    field_5: str | None = None  # 合并窗口秒
    field_6: str | None = None  # 重复抑制
    field_7: str | None = None  # 优先级
