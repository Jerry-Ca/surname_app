# 运维手册（共享服务器版）

所有命令都在项目目录 `/home/ubuntu/guji-jiaocuo/xungen12` 下执行。**服务器为 Python 3.10.12**（已确认）；代码只用标准库、按 3.8+ 兼容写（`tests/test_compat.py` 有护栏）。**端口以服务器登记端口为准**（下面用 `<PORT>`）。

## 1. 首次部署

```bash
python3 --version && python3 -c "import sqlite3, json, csv, http.server"   # 1) 运行时自检，失败就停下并记录原文
sh scripts/runtime_check.sh <PORT>                                        # 2) 目录/端口/数据库 五项自检（输出交 A）
cd xungen12                                                              # 3) 进入项目目录
python3 scripts/init_db.py                                               # 4) 建库：data/xungen.db + schema_version.txt
python3 scripts/validate_package.py data/verified                        # 5) 校验 B 的数据包
python3 scripts/import_data.py data/verified --operator B                # 6) 干跑
python3 scripts/import_data.py data/verified --operator B --apply --stats-out docs/db-stats-$(date +%Y%m%d).json
python3 scripts/contract_tests.py                                        # 7) 契约测试
PORT=<PORT> sh scripts/start.sh                                          # 8) 启动
curl http://127.0.0.1:<PORT>/api/health                                  # 9) 健康检查
```

## 2. 日常操作

| 动作 | 命令 | 说明 |
| --- | --- | --- |
| 启动 | `PORT=<PORT> sh scripts/start.sh` | 写 `run/server.pid`；已在运行会拒绝重复启动 |
| 停止 | `sh scripts/stop.sh` | 只 kill PID 文件里的进程；命令行或 health 对不上就拒绝（不用 killall/pkill） |
| 看日志 | `tail -f logs/app.log` | 请求行与未预期异常的完整栈都在这里 |
| 备份 | `sh scripts/backup.sh [标签]` | 产出 `backups/xungen-YYYYmmdd-HHMM.db`（+ `.sha256`） |
| 恢复 | `sh scripts/restore.sh backups/<文件> --yes` | 先自动备份当前库 → 覆盖 → 跑 health 自检；自检失败自动回滚 |
| 看板数据 | `curl http://127.0.0.1:<PORT>/api/surnames/李` | 需要 URL 编码的中文：`%E6%9D%8E` |
| 站外自检 | `curl http://<公网IP>:<PORT>/api/health` | 从校外网络再测一次网页 `http://<公网IP>:<PORT>/` |

**部署形态（与执行清单一致）**：**同一个端口对外**——`http://<公网IP>:18888/` 是网页，`/api/*` 是接口，
页面与接口**同源**，因此不需要反向代理、也不需要 CORS 配置。静态资源只来自 `static/`
（D 的构建产物复制进去），数据库、`.env`、`logs/`、`backups/` 一律不对外。

站外连不上但 `curl 127.0.0.1:<PORT>/api/health` 正常，说明是安全组/防火墙没放行该端口 ——
这是服务器所有者的决定范围，交 A 协调，不要自行改防火墙。

## 3. 出问题时按这个顺序看

1. `logs/app.log` 最后 20 行（异常栈都在这里）；
2. `curl http://127.0.0.1:<PORT>/api/health` —— `status` 是 `down` 说明数据库路径/权限有问题；
3. `python3 scripts/init_db.py --check` —— 表是否齐、schema 版本是否一致；
4. `python3 -m unittest discover -s tests` 与 `python3 scripts/contract_tests.py`；
5. 仍解决不了：把「复现命令 + 原始输出 + 已确认范围 + 需要谁决定」写成一条消息给 A（执行清单 §十一），
   不要用删除数据库、覆盖别人文件、改全局配置的方式绕过。

## 4. 禁忌（写完命令也会被拒的几件事）

- 不用 `sudo`、不装系统包、不改共享目录之外的东西；
- 不用 `killall` / `pkill -f`；
- 不把 `data/xungen.db`、`.env`、`logs/`、`backups/` 放进静态资源目录；
- 不让服务写库：写库只走 `scripts/import_data.py`（服务用只读连接打开数据库）。

## 5. 定期维护

- 每天至少一次 `sh scripts/backup.sh dayN`，备份文件保留在 `backups/`；
- 演示前跑 `python3 scripts/contract_tests.py` 与 `python3 scripts/import_data.py <包> --operator C`（干跑）；
- 数据更新后**必须**重建全文索引：`import_data.py --apply` 会自动重建，手工改库后要跑
  `python3 scripts/init_db.py --rebuild-fts`。
