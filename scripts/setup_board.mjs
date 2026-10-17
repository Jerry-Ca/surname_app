#!/usr/bin/env node
/**
 * 按 docs/collaboration/task-board.md 创建 Projects v2 看板。
 *
 *   node scripts/setup_board.mjs            干跑：只打印将要创建的内容
 *   node scripts/setup_board.mjs --apply    实际创建
 *   node scripts/setup_board.mjs --apply --title "自定义看板名"
 *
 * 会做的事：
 *   1. 创建（或复用同名）看板，并关联到仓库
 *   2. 把列做成 Status 字段的 7 个选项：Backlog / Ready / In progress / Review / Blocked / Verify / Done
 *   3. 新建两个单选字段：角色（A—E）、冲刺日（Day1—Day3）
 *   4. 把 30 张任务卡加入看板，并填好 Status=Backlog 与角色、冲刺日
 *   5. 建三个视图：按人（表格）、按日（看板）、阻塞（表格 + label:blocked 过滤）
 *
 * 幂等：重复执行不会重复建看板、字段、条目或视图；已存在条目只会补齐字段值。
 * 需要 token 具备 project scope：gh auth refresh -s project
 *
 * 无法脚本化的两件事（必须在界面里点一次，脚本末尾会打印步骤）：
 *   - 视图的 Group by（API 的 view configuration 只接受 visibleFieldIds）
 *   - 内置自动化（Item closed → Done 等，Projects v2 没有创建 workflow 的 API）
 */

import { execFileSync } from 'node:child_process'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..')
const APPLY = process.argv.includes('--apply')
const DRY_RUN = !APPLY

function argValue(flag, fallback) {
  const index = process.argv.indexOf(flag)
  return index > -1 && process.argv[index + 1] ? process.argv[index + 1] : fallback
}

const team = JSON.parse(readFileSync(join(ROOT, 'docs', 'collaboration', 'team.json'), 'utf8'))
const { tasks } = JSON.parse(readFileSync(join(ROOT, 'docs', 'collaboration', 'tasks.json'), 'utf8'))
const [OWNER, REPO_NAME] = team.repo.split('/')
const TITLE = argValue('--title', '姓氏郡望与家族迁徙寻根系统 · 三日冲刺看板')

// 列 = Status 字段的选项（顺序即看板列顺序，与 task-board.md 第 1 节一致）
const COLUMNS = [
  { name: 'Backlog', color: 'GRAY', description: '已在 tasks.json 中定义，尚未认领' },
  { name: 'Ready', color: 'BLUE', description: '依赖满足，可以开工' },
  { name: 'In progress', color: 'YELLOW', description: '已建分支，正在实现' },
  { name: 'Review', color: 'PURPLE', description: 'PR 已开，等评审与 CI' },
  { name: 'Blocked', color: 'RED', description: '被依赖或接口变更阻塞，需在整合时上报' },
  { name: 'Verify', color: 'ORANGE', description: '已合并，等 A 按 acceptance.md 验收' },
  { name: 'Done', color: 'GREEN', description: '验收通过，交付物可访问' },
]

const ROLE_FIELD = {
  name: '角色',
  options: [
    { name: 'A', color: 'PINK', description: '产品与总集成' },
    { name: 'B', color: 'ORANGE', description: '文献数据与管线' },
    { name: 'C', color: 'BLUE', description: '后端与数据库' },
    { name: 'D', color: 'PURPLE', description: '前端与交互' },
    { name: 'E', color: 'GREEN', description: 'RAG、部署与测试' },
  ],
}

const DAY_FIELD = {
  name: '冲刺日',
  options: [
    { name: 'Day1', color: 'BLUE', description: '骨架与首条闭环' },
    { name: 'Day2', color: 'YELLOW', description: '数据规模与主要功能' },
    { name: 'Day3', color: 'ORANGE', description: '部署联调与验收' },
  ],
}

const VIEWS = [
  { name: '按人', layout: 'TABLE_LAYOUT', filter: null, hint: '建议在界面点 Group by → 角色' },
  { name: '按日', layout: 'BOARD_LAYOUT', filter: null, hint: '建议在界面点 Group by → 冲刺日' },
  { name: '阻塞', layout: 'TABLE_LAYOUT', filter: 'label:blocked', hint: '过滤 label:blocked' },
]

// ---------------------------------------------------------------- gh 调用

function gh(args, { input } = {}) {
  try {
    return execFileSync('gh', args, {
      encoding: 'utf8',
      input,
      stdio: input === undefined ? ['ignore', 'pipe', 'pipe'] : ['pipe', 'pipe', 'pipe'],
      maxBuffer: 64 * 1024 * 1024,
    }).trim()
  } catch (error) {
    const stderr = (error.stderr ?? '').toString().trim()
    const stdout = (error.stdout ?? '').toString().trim()
    throw new Error((stderr || stdout || error.message).slice(0, 800))
  }
}

function graphql(query, variables = {}) {
  const raw = gh(['api', 'graphql', '--input', '-'], { input: JSON.stringify({ query, variables }) })
  const parsed = JSON.parse(raw)
  if (parsed.errors?.length) {
    throw new Error(parsed.errors.map((e) => e.message).join('; '))
  }
  return parsed.data
}

// ---------------------------------------------------------------- 查询

const OWNER_QUERY = `query ($login: String!) {
  user(login: $login) {
    id
    projectsV2(first: 50) { nodes { id number title url } }
  }
}`

const REPO_PAGE = `query ($owner: String!, $name: String!, $cursor: String) {
  repository(owner: $owner, name: $name) {
    id
    issues(first: 100, states: [OPEN, CLOSED], after: $cursor) {
      nodes { id number title }
      pageInfo { hasNextPage endCursor }
    }
  }
}`

const PROJECT_PAGE = `query ($number: Int!, $cursor: String) {
  user(login: "${OWNER}") {
    projectV2(number: $number) {
      id number title url
      fields(first: 100) {
        nodes {
          ... on ProjectV2FieldCommon { id name }
          ... on ProjectV2SingleSelectField { options { id name } }
        }
      }
      items(first: 100, after: $cursor) {
        nodes {
          id
          content { ... on Issue { id number title } }
        }
        pageInfo { hasNextPage endCursor }
      }
      views(first: 20) { nodes { id name } }
    }
  }
}`

const CREATE_PROJECT = `mutation ($ownerId: ID!, $title: String!, $repositoryId: ID) {
  createProjectV2(input: { ownerId: $ownerId, title: $title, repositoryId: $repositoryId }) {
    projectV2 { id number title url }
  }
}`

const UPDATE_STATUS_OPTIONS = `mutation ($fieldId: ID!, $options: [ProjectV2SingleSelectFieldOptionInput!]!) {
  updateProjectV2Field(input: { fieldId: $fieldId, singleSelectOptions: $options }) {
    projectV2Field { ... on ProjectV2SingleSelectField { id name options { id name } } }
  }
}`

const CREATE_FIELD = `mutation ($projectId: ID!, $name: String!, $options: [ProjectV2SingleSelectFieldOptionInput!]!) {
  createProjectV2Field(input: { projectId: $projectId, dataType: SINGLE_SELECT, name: $name, singleSelectOptions: $options }) {
    projectV2Field { ... on ProjectV2SingleSelectField { id name options { id name } } }
  }
}`

const ADD_ITEM = `mutation ($projectId: ID!, $contentId: ID!) {
  addProjectV2ItemById(input: { projectId: $projectId, contentId: $contentId }) {
    item { id }
  }
}`

const SET_VALUE = `mutation ($projectId: ID!, $itemId: ID!, $fieldId: ID!, $optionId: String!) {
  updateProjectV2ItemFieldValue(input: {
    projectId: $projectId, itemId: $itemId, fieldId: $fieldId, value: { singleSelectOptionId: $optionId }
  }) {
    projectV2Item { id }
  }
}`

const CREATE_VIEW = `mutation ($projectId: ID!, $name: String!, $layout: ProjectV2ViewLayout!) {
  createProjectV2View(input: { projectId: $projectId, name: $name, layout: $layout }) {
    projectV2View { id name layout }
  }
}`

const UPDATE_VIEW = `mutation ($viewId: ID!, $filter: String) {
  updateProjectV2View(input: { viewId: $viewId, filter: $filter }) {
    projectV2View { id name filter }
  }
}`

function optionInput(options) {
  return options.map((o) => ({ name: o.name, color: o.color, description: o.description ?? '' }))
}

function optionId(field, name) {
  const found = field?.options?.find((o) => o.name === name)
  if (!found) throw new Error(`字段 ${field?.name} 中找不到选项 ${name}`)
  return found.id
}

/** GraphQL 单次最多取 100 条，用游标把 issue 全部取回 */
function fetchRepository() {
  let cursor = null
  let repo = null
  const issues = []
  do {
    const page = graphql(REPO_PAGE, { owner: OWNER, name: REPO_NAME, cursor }).repository
    repo = page
    issues.push(...page.issues.nodes)
    cursor = page.issues.pageInfo.hasNextPage ? page.issues.pageInfo.endCursor : null
  } while (cursor)
  return { id: repo.id, issues }
}

/** 同理取回看板全部条目 */
function fetchProject(number) {
  let cursor = null
  let project = null
  const items = []
  do {
    const page = graphql(PROJECT_PAGE, { number, cursor }).user.projectV2
    project = page
    items.push(...page.items.nodes)
    cursor = page.items.pageInfo.hasNextPage ? page.items.pageInfo.endCursor : null
  } while (cursor)
  return { ...project, items: { nodes: items } }
}

// ---------------------------------------------------------------- 主流程

function main() {
  console.log(`仓库：${team.repo}`)
  console.log(`看板：${TITLE}`)
  console.log(`模式：${DRY_RUN ? '干跑（不会修改任何远程内容）' : '实际创建'}`)
  console.log('')

  const owner = graphql(OWNER_QUERY, { login: OWNER }).user
  const repo = fetchRepository()

  const issues = new Map()
  for (const node of repo.issues) issues.set(node.title, node)
  console.log(`仓库内 issue：${issues.size} 张`)

  const missing = tasks.filter((t) => !issues.has(`[${t.id}] ${t.title}`))
  if (missing.length) {
    console.log(`警告：${missing.length} 个任务在仓库里找不到同名 issue（先跑 seed_github.mjs --apply）：`)
    console.log(`  ${missing.map((t) => t.id).join('、')}`)
  }

  console.log('')
  console.log(`列（Status 字段 ${COLUMNS.length} 个选项）：${COLUMNS.map((c) => c.name).join(' → ')}`)
  console.log(`字段：${ROLE_FIELD.name}（${ROLE_FIELD.options.map((o) => o.name).join('/')}）、` +
    `${DAY_FIELD.name}（${DAY_FIELD.options.map((o) => o.name).join('/')}）`)
  console.log(`视图：${VIEWS.map((v) => `${v.name}（${v.layout === 'BOARD_LAYOUT' ? '看板' : '表格'}）`).join('、')}`)
  console.log(`条目：${tasks.length} 张任务卡，Status 统一置 Backlog 并填角色与冲刺日`)

  if (DRY_RUN) {
    console.log('')
    console.log('干跑完成。确认后运行：node scripts/setup_board.mjs --apply')
    return
  }

  // 1) 看板
  console.log('')
  const existingProject = owner.projectsV2.nodes.find((p) => p.title === TITLE)
  let projectId
  let projectNumber
  let projectUrl
  if (existingProject) {
    ;({ id: projectId, number: projectNumber, url: projectUrl } = existingProject)
    console.log(`复用已有看板：${projectUrl}`)
  } else {
    const created = graphql(CREATE_PROJECT, { ownerId: owner.id, title: TITLE, repositoryId: repo.id }).createProjectV2
      .projectV2
    ;({ id: projectId, number: projectNumber, url: projectUrl } = created)
    console.log(`创建看板：${projectUrl}`)
  }

  // 2) 读取现有字段、条目与视图
  let project = fetchProject(projectNumber)
  const fieldByName = (name) => project.fields.nodes.find((f) => f?.name === name)

  // 3) Status 选项：内置 Status 字段可能不允许改，失败则退回到自建「状态」字段
  let statusField = fieldByName('Status')
  let statusFieldName = 'Status'
  if (statusField) {
    try {
      const result = graphql(UPDATE_STATUS_OPTIONS, { fieldId: statusField.id, options: optionInput(COLUMNS) })
      statusField = result.updateProjectV2Field.projectV2Field
      console.log(`Status 字段选项已更新为 ${statusField.options.length} 个：${statusField.options.map((o) => o.name).join(' → ')}`)
    } catch (error) {
      console.log(`内置 Status 字段不可改（${error.message.slice(0, 120)}），改为自建「状态」字段`)
      statusField = null
      statusFieldName = '状态'
    }
  }
  if (!statusField) {
    let custom = fieldByName(statusFieldName)
    if (!custom) {
      custom = graphql(CREATE_FIELD, { projectId, name: statusFieldName, options: optionInput(COLUMNS) }).createProjectV2Field
        .projectV2Field
      console.log(`已创建字段「${statusFieldName}」，${custom.options.length} 个选项`)
    } else {
      console.log(`复用已存在字段「${statusFieldName}」`)
    }
    statusField = custom
    console.log('提示：请在界面把视图按「' + statusFieldName + '」分组，或删除内置 Status 字段以免混淆')
  }

  // 4) 角色 / 冲刺日 字段
  for (const spec of [ROLE_FIELD, DAY_FIELD]) {
    if (fieldByName(spec.name)) {
      console.log(`字段已存在，跳过：${spec.name}`)
      continue
    }
    graphql(CREATE_FIELD, { projectId, name: spec.name, options: optionInput(spec.options) })
    console.log(`创建字段：${spec.name}（${spec.options.length} 个选项）`)
  }
  project = fetchProject(projectNumber)
  const roleField = project.fields.nodes.find((f) => f?.name === ROLE_FIELD.name)
  const dayField = project.fields.nodes.find((f) => f?.name === DAY_FIELD.name)

  // 5) 条目与字段值
  const itemByNumber = new Map()
  for (const item of project.items.nodes) {
    if (item.content?.number) itemByNumber.set(item.content.number, item)
  }
  let added = 0
  let updated = 0
  for (const task of tasks) {
    const issue = issues.get(`[${task.id}] ${task.title}`)
    if (!issue) continue
    let item = itemByNumber.get(issue.number)
    if (!item) {
      item = graphql(ADD_ITEM, { projectId, contentId: issue.id }).addProjectV2ItemById.item
      added += 1
    } else {
      updated += 1
    }
    const values = [
      [statusField, 'Backlog'],
      [roleField, task.owner],
      [dayField, `Day${task.day}`],
    ]
    for (const [field, name] of values) {
      if (!field) continue
      graphql(SET_VALUE, { projectId, itemId: item.id, fieldId: field.id, optionId: optionId(field, name) })
    }
  }
  console.log(`条目：新增 ${added} 张，补齐字段值 ${updated} 张（共 ${tasks.length} 张任务卡）`)

  // 6) 视图
  const existingViews = new Set(project.views.nodes.map((v) => v.name))
  for (const view of VIEWS) {
    if (existingViews.has(view.name)) {
      console.log(`视图已存在，跳过：${view.name}`)
      continue
    }
    const created = graphql(CREATE_VIEW, { projectId, name: view.name, layout: view.layout }).createProjectV2View
      .projectV2View
    if (view.filter) {
      graphql(UPDATE_VIEW, { viewId: created.id, filter: view.filter })
    }
    console.log(`创建视图：${view.name}${view.filter ? `（过滤 ${view.filter}）` : ''}`)
  }

  console.log('')
  console.log(`看板地址：${projectUrl}`)
  console.log('')
  console.log('还需要在界面里点一次（API 不支持）：')
  for (const view of VIEWS) {
    if (view.hint) console.log(`  · 视图「${view.name}」：${view.hint}`)
  }
  console.log('  · 内置自动化：Project → ⋯ → Workflows 里打开')
  console.log('      Item added to project → 状态置 Backlog')
  console.log('      Item closed → 状态置 Done')
  console.log('      Pull request linked to issue → 状态置 Review')
}

main()