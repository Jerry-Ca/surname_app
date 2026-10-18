# 运维手册（共享服务器版）

所有命令都在项目目录 `/home/ubuntu/guji-jiaocuo/xungen12` 下执行。**服务器为 Python 3.10.12**（已确认）；代码只用标准库、按 3.8+ 兼容写（`tests/test_compat.py` 有护栏）。**端口以服务器登记端口为准**（下面用 `<PORT>`）。

## 0. 部署位置（唯一，不要在别处另建副本）

项目目录：**`/home/ubuntu/guji-jiaocuo/xungen12`**（执行清单第一条写的路径）。服务、数据库、日志、备份、
交付文档全都在这里；服务器上**没有第二份副本**。

- 用 `guji` 登录后默认落在**家目录** `/home/guji`；不要 `cd ~/xungen12` —— 那个目录已于 2026-10-17 合并删除，
  避免两份代码各自演进（当时 E 的 `docs/prompt-log-E.md` 已移入本项目 `docs/`）。
- 确认自己在哪里：`pwd`；确认项目在哪里：`ls /home/ubuntu/guji-jiaocuo/xungen12`。
- 要在共享目录下建自己的草稿区可以，但**不要叫 xungen12**，也不要把服务/数据库放在别处。

## 1. 首次部署

```bash
python3 --version && python3 -c "import sqlite3, json, csv, http.server"   # 1) 运行时自检，失败就停下并记录原文
sh scripts/runtime_check.sh <PORT>                                        # 2) 目录/端口/数据库 五项自检（输出交 A）
cd xungen12                                                              # 3) 进入项目目录
python3 scripts/init_db.py                                               # 4) 建库：data/xungen.db + schema_version.txt
python3 scripts/validate_package.py <数据包目录>                          # 5) 校验数据包
python3 scripts/import_data.py <数据包目录> --operator B                  # 6) 干跑（默认就不写库，没有 --dry-run 参数）
python3 scripts/import_data.py <数据包目录> --operator B --apply --stats-out docs/db-stats-$(date +%Y%m%d).json
python3 scripts/contract_tests.py                                        # 7) 契约测试
PORT=<PORT> sh scripts/start.sh                                          # 8) 启动
curl http://127.0.0.1:<PORT>/api/health                                  # 9) 健康检查
```

**数据包在哪**：`data/verified/` 是 C 自己 2026-10-17 导入的那两个文件；**成员 B 的包在
`data/incoming/20261018-B{,-delta,-day3}/`**（B 不往 `data/verified/` 写）。导入顺序与三个易踩的坑见
`data/incoming/20261018-B/HOW_TO_IMPORT.md`。**包目录里只放数据文件**：`validate_package.py` /
`import_data.py` 会收下目录里所有 `*.json`，混进说明或响应快照会被判「无法判断数据种类」而整包报错
（错误可读、可修复：把辅助文件移进子目录）。

## 2. 日常操作

| 动作 | 命令 | 说明 |
| --- | --- | --- |
| 启动 | `PORT=<PORT> sh scripts/start.sh` | 写 `run/server.pid`；已在运行会拒绝重复启动 |
| 停止 | `sh scripts/stop.sh` | 只 kill PID 文件里的进程；命令行或 health 对不上就拒绝（不用 killall/pkill） |
| 看日志 | `tail -f logs/app.log` | 请求行与未预期异常的完整栈都在这里 |
| 备份 | `sh scripts/backup.sh [标签]` | 产出 `backups/xungen-YYYYmmdd-HHMM.db`（+ `.sha256`） |
| 恢复 | `sh scripts/restore.sh backups/<文件> --yes` | 先自动备份当前库 → 覆盖 → 跑 health 自检；自检失败自动回滚 |
| 看板数据 | `curl http://127.0.0.1:<PORT>/api/surnames/李` | 需要 URL 编码的中文：`%E6%9D%8E` |
| 重算统计 | `python3 scripts/import_data.py --stats-only --stats-out docs/db-stats-$(date +%Y%m%d).json` | 不导入，只从现行库重算；**部署会覆盖仓库里的旧统计文件**，所以每次部署后重算一次 |
| 改证据状态 | `python3 scripts/apply_review_status.py <核对结果.csv>`（默认预演，`--apply` 才写） | 人工核对结果落库：改状态 + 同事务写 `review_logs` + 重建 FTS；只碰 `verification_status / verified_by / verification_note / updated_at` 四列 |
| 站外自检 | `curl http://<公网IP>:<PORT>/api/health` | 从校外网络再测一次网页 `http://<公网IP>:<PORT>/` |

**写库只有两条通道**：新数据走 `import_data.py`（**只插入**，编号撞库整批回滚）；人工核对的
「待核对 → 已核对 / 已撤回」走 `apply_review_status.py`（CSV 四列：`evidence_id, verification_status,
verified_by, verification_note`；可发布状态必须带核对人与说明，`disputed` 必须已有 `dispute_group`；
任一行不合规整批回滚；重复跑同一份 CSV 幂等）。**手工 UPDATE 不作为通道**——它绕开 `review_logs`，
留痕就断了。

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
- 数据更新后**必须**重建全文索引：`import_data.py --apply` 与 `apply_review_status.py --apply` 都会自动重建；
  手工改库后要跑 `python3 scripts/init_db.py --rebuild-fts`。
  注意 `app/fts.rebuild()` **内部会 commit**（会把同一连接上未提交的改动一起提交），
  不要把它放进「先看看效果再回滚」的预演事务里。
