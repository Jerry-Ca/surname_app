# xungen12 — 共享服务器版后端（成员 C）

课题 12「姓氏郡望与家族迁徙寻根系统」在**共享服务器**上的交付物：没有 root 权限、不能安装数据库服务，
因此用 **Python 3 标准库 + SQLite** 实现稳定 API（**生产服务器已确认 Python 3.10.12**；代码按 3.8+ 兼容写，本机开发环境 3.12，`tests/test_compat.py` 会拦住 3.11+ 的语法与标准库用法）。本目录与服务器目录
`/home/ubuntu/guji-jiaocuo/xungen12` **一一对应**，部署时整体复制过去即可。

## 目录

```
app/            server.py（HTTP 服务）、queries/search/ask、schema/db/fts、contract（响应封装）
scripts/        init_db.py、validate_package.py、import_data.py、contract_tests.py、
                start.sh / stop.sh / backup.sh / restore.sh / runtime_check.sh
data/           xungen.db（唯一数据库）、schema_version.txt、tmp/（临时库）、samples/（契约测试样例）
docs/           api-contract-v1.md（契约草案）、runbook.md（运维手册）、prompt-log.md、handoff/（交接包）、contract/（接口样例）
logs/ run/ backups/   日志、PID、备份（都在 .gitignore 里，不进仓库）
```

## 上服务器前先做（任务 C-07）

```bash
sh scripts/runtime_check.sh <登记端口>      # python3/标准库/目录可写/端口/数据库 五步自检，输出交 A
```

目录不可写、端口被占、`python3` 缺失时**停下**并记录原文（执行清单 §十一 停线规则），不要 sudo、不要装系统包。

## 常用命令

```bash
python3 scripts/init_db.py                                  # 建库（幂等）：data/xungen.db + schema_version.txt
python3 scripts/validate_package.py data/verified           # 校验数据包（UTF-8/表头/必填/枚举/编号/关联）
python3 scripts/import_data.py data/verified --operator B    # 干跑（默认不写库）
python3 scripts/import_data.py data/verified --operator B --apply --stats-out docs/db-stats-$(date +%Y%m%d).json
PORT=<登记端口> sh scripts/start.sh                          # 启动（写 run/server.pid）
sh scripts/stop.sh                                          # 停止（只 kill 自己 PID 里的进程）
sh scripts/backup.sh [标签]                                  # 备份到 backups/xungen-YYYYmmdd-HHMM.db
sh scripts/restore.sh backups/<备份> --yes                    # 恢复（先备份当前库，再恢复并自检）
python3 scripts/contract_tests.py                            # 契约测试（临时库 + 临时端口，不碰正式库）
python3 -m unittest discover -s tests                        # 单元测试
```

## 硬约束（执行清单）

- 只用 Python 标准库；不装第三方包、不用 sudo、不改共享目录之外的东西；
- 数据库只能是 `data/xungen.db`（临时库放 `data/tmp/` 并清理）；
- 启动/停止只影响自己的 PID，禁止 `killall` / `pkill -f`；
- **一个端口对外**：`http://<公网IP>:18888/` 是网页、`/api/*` 是接口，页面与接口同源（不需要反代与 CORS）；
  网页静态资源来自 `static/`（放 D 的构建产物），数据库/`.env`/`logs/`/`backups/` 不对外；
- 接口返回 `data` / `audit` / `message` 三个键，空结果是 `data: []` + HTTP 200，不返回 500；
- 每条证据都带 `evidence_id` 与来源字段；`pending`（待核对）不外发；
- 不把数据库文件、`.env`、`logs/`、`backups/` 当静态资源暴露；静态资源只服务 `static/`（D 的构建产物）。
