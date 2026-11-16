"""业务模块路由汇总。

这里统一按别名导入再暴露 ROUTERS：模块名有可能和内置名撞车（某个业务模块就叫 dict、list
这种名字时），按名字直接 import 会把内置类型覆盖掉，函数注解在运行时求值就会报
'module' object is not subscriptable。
"""
from __future__ import annotations

from app.routers import service as router_service
from app.routers import flow as router_flow
from app.routers import ratelimit as router_ratelimit
from app.routers import auth as router_auth
from app.routers import monitor as router_monitor
from app.routers import monitor_batch as router_monitor_batch
from app.routers import monitor_alert as router_monitor_alert
from app.routers import consumer as router_consumer
from app.routers import version as router_version
from app.routers import cache as router_cache
from app.routers import transform as router_transform
from app.routers import gateway as router_gateway
from app.routers import schema as router_schema
from app.routers import datasource as router_datasource
from app.routers import query as router_query
from app.routers import cleanse as router_cleanse
from app.routers import log as router_log
from app.routers import mock as router_mock
from app.routers import backup as router_backup
from app.routers import notify as router_notify

ROUTERS = [router_service, router_flow, router_ratelimit, router_auth, router_monitor, router_monitor_batch, router_monitor_alert, router_consumer, router_version, router_cache, router_transform, router_gateway, router_schema, router_datasource, router_query, router_cleanse, router_log, router_mock, router_backup, router_notify]
