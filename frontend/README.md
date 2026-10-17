# frontend/ — React + Vite 前端

主责：**D**。契约依据：[../docs/api-contract.md](../docs/api-contract.md)；状态枚举与界面中文的对应见 [../docs/data-dictionary.md](../docs/data-dictionary.md) 第 3、7 节。

## 运行

```bash
cd frontend
npm install
npm run dev        # http://127.0.0.1:5173，/api 已代理到 127.0.0.1:8000
npm run build      # 产物在 dist/，部署时由 Nginx 直接托管
```

后端没启动也能打开页面：接口会返回网络错误，页面显示“无法连接后端服务”并提供重试。

## 当前实现状态（框架阶段）

| 部分 | 状态 |
| --- | --- |
| 路由骨架（搜索页 / 结果页 / 来源详情） | 可用 |
| `api/client.js` | 可用：统一处理空结果、降级、错误与 request_id |
| `EvidenceCard` | 基础版可用（事实、卷次、摘录、出处、核对状态、链接待复查标记） |
| `MigrationTimeline` / `MigrationGraph` | 基础版可用（轻量呈现，不依赖图表库） |
| `StatePanel` + `STATE_TEXT` | 六种异常状态的预置文案（措辞来自验收标准，不要随手改） |
| 结果页四个区块 | 已按契约组装，等 C 接入真实数据后自动显示内容 |
| 问答区 | 已接 `/api/ask`，能显示降级与证据不足两种情况 |

当前后端返回的是契约形状的空结果，因此页面会显示“当前语料中未收录该姓氏”与未命中说明——这正是 D 用来开发空状态的真实路径，不是错误。

## 边界（违反会被打回）

- 只通过 `src/api/client.js` 访问后端；组件里不写 `fetch`，不读数据库，不调用任何模型 API。
- 不显示代码值（`verified`、`disputed` 等），一律经 `src/lib/enums.js` 转成界面中文。
- 界面文案必须区分“当前语料中最早”与“历史上最早”；不确定的表述要用数据字典第 3、7 节规定的措辞。
- 新增需要的字段先改 `docs/api-contract.md` 并请 C 实现，不要在前端拼接或猜测字段。
- 空结果、错误、降级三种状态都要有可见文案与重试入口，不允许出现空白页。

## 目录

```
src/
├─ main.jsx              入口
├─ App.jsx               路由与布局
├─ styles.css            全站样式（含手机宽度适配）
├─ api/client.js         后端接口封装（唯一出口）
├─ lib/enums.js          枚举 → 界面中文
├─ components/
│   ├─ EvidenceCard.jsx        证据卡片
│   ├─ MigrationTimeline.jsx   迁徙时间线
│   ├─ MigrationGraph.jsx      迁徙关系图
│   ├─ AskPanel.jsx            证据问答区
│   └─ StatePanel.jsx          状态提示（六种异常）
└─ pages/
    ├─ SearchPage.jsx          搜索页
    ├─ SurnameResultPage.jsx   结果页（四个必需区块）
    └─ SourceDetailPage.jsx    来源详情页
```