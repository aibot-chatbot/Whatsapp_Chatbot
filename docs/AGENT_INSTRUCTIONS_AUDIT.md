# Agent 指令、技能与 workflow 审计

审计日期：2026-09-07。范围：`C:\Users\Vincent\Desktop\Whatsapp_Chatbot`。
目标：对齐 GPT-6 Astra 官方指导，减少上下文浪费和指令冲突，同时保留业务安全约束。

## 1. 结论与原始状态

仓库原先只有 `AGENTS.md`（4,812 字节）和 Claude 的
`.claude/commands/render.md`（9,836 字节），没有仓库 `SKILL.md`、
`.agents/skills`、`.codex` 或 GitHub Actions workflow。这里的 workflow 指开发与
部署操作流程；未修改应用业务 workflow、Langflow、生产部署配置或 CI。
隐藏文件已纳入盘点；依赖、生成产物、运行状态与秘密内容不属于指令审计输入。
`.claude/settings.local.json` 只确认存在，没有读取权限条目或修改它。

主要问题：

| 发现 | 处理 |
|---|---|
| 仓库入口重复过程要求、固定十段报告，缺少具体验证路由 | 入口保留约束，代码工作细节移到按需 `AGENT_WORKFLOW.md` |
| Render 状态模式要求转向 apply；null 被断言为不存在 | 状态模式完成即停止；无法确定时报告 unknown |
| 历史 CLI、认证、服务地址被当成永久事实 | 从当前配置和只读证据确认目标及可用工具 |
| Claude 专用命令、Bash heredoc 不适合作为 Codex 技能入口 | 新增标准仓库技能；Claude 入口转发到同一来源 |
| 测试指南含损坏的 PowerShell 路径及过时通过数 | 使用 `.venv` 解释器路径；明确历史结果不证明当前通过 |

独立审查确认租户、权限、秘密、微 MYR、幂等和生产操作授权边界得到保留。
原始技能评审保存在 [AGENT_SKILL_REVIEW.md](AGENT_SKILL_REVIEW.md)，其中评分
描述修改前提交，不作为修改后的自评通过证据。

## 2. 官方依据与设计选择

官方 Astra 指南强调明确自主完成任务、消除技能冲突、按任务调整委派与测试力度。
因此保留必要边界，允许常规本地工作直接完成，并在有独立任务时使用子代理；
不为每个小修改强制访谈、团队模式或全量测试。
[GPT-6 Astra 指南](https://developers.openai.com/api/docs/guides/latest-model)

官方说明 AGENTS.md 在启动时形成指令链，默认总上限为 32 KiB。本机全局文件实测
30,692 字节，原仓库文件令合计达到 35,506 字节；未发现全局 override 文件，
配置中未找到 `project_doc_max_bytes` 自定义值。新合计为 32,627 字节，低于默认
上限，但只余 141 字节；全局文件继续增长仍会构成截断风险。
[AGENTS.md 加载规则](https://learn.chatgpt.com/docs/agent-configuration/agents-md)

技能采用 `.agents/skills/wa-render-ops/SKILL.md`，包含明确的 name/description；
细节放在 reference，按模式读取。没有增加插件、脚本依赖或重复技能副本。
[官方技能文档](https://learn.chatgpt.com/docs/build-skills)

官方建议短而准确的项目规则、清楚的目标和完成条件，并按任务难度选择推理力度。
本机 CLI 为 `codex-cli 0.153.4`；已配置 `gpt-6-astra` 与 `medium`。本次保留配置，
不把固定模型表复制进项目、不强制 max，也不把 API 功能误写成宿主已提供的能力。
[Codex 最佳实践](https://learn.chatgpt.com/guides/best-practices)

## 3. 文件与行为变化

| 文件 | 用途 |
|---|---|
| [AGENTS.md](../AGENTS.md) | 1,933 字节；比原文件减少 59.8%，包含核心业务边界和工作路由 |
| [AGENT_WORKFLOW.md](AGENT_WORKFLOW.md) | 按需开发、委派、测试、安全扫描和完成标准 |
| [SKILL.md](../.agents/skills/wa-render-ops/SKILL.md) | Codex 可发现的 Render 模式入口；默认只读 status |
| [operations.md](../.agents/skills/wa-render-ops/references/operations.md) | 源码核对后的部署约束、各渠道操作及验证边界 |
| [render.md](../.claude/commands/render.md) | 保留 Claude 命令名和参数，转向共用技能 |
| [TESTING_GUIDE.md](TESTING_GUIDE.md) | 修复执行路径、历史计数表述与验证力度说明 |

Render 入口、技能及 reference 合计 7,401 字节，相比原命令减少 24.8%；
简单 status 不需读取部署 reference。按需文档的新增字节不等于启动 token 增加。
字节变化不代表模型速度、成本或质量同比改善；未做前后性能基准测试。

## 4. 验证记录

| 检查 | 当前结果 |
|---|---|
| Skill Creator `quick_validate.py .agents/skills/wa-render-ops` | exit 0，`Skill is valid!` |
| UTF-8、控制字符、相对链接、默认入口预算 | 检查通过；核心六文件 9 个链接有效，组合预算 32,627 字节 |
| 独立原文对照和场景评审 | 未发现阻塞问题；发现 Telegram dry-run 外部读取表述不足，修复后独立复核确认解决 |
| Astra 新进程加载 | exit 0；识别技能、正确引用仓库最后一句、拒绝从 status 推导部署权限 |
| App Server `skills/list` | 当前用户配置下返回唯一 `wa-render-ops`，`scope=repo`、`enabled=true`、路径正确；另有 1 个用户级加载错误 |
| 最终 Markdown 检查 | 8 个文件 UTF-8/控制字符/尾随空白通过，20 个本地链接有效 |
| 改动范围 | 本次已跟踪文件 `git diff --check` exit 0；新增文档逐行空白检查通过；改动前其他文件哈希全部不变 |
| Codex Security | 未完整通过：首轮保存冲突，后续工具兼容性/启动异常；详见下方记录。没有正在后台运行的扫描 |

新进程命令使用 `codex exec --ephemeral --ignore-user-config --sandbox read-only
--model gpt-6-astra -c model_reasoning_effort=low`，仅要求从已加载指令和技能元数据
回答，无工具调用。它验证仓库发现和边界理解；跳过用户 config 的探针不能证明
完整桌面 MCP/hooks 启动、Claude 命令实际执行或线上操作正确。
该探针记录 input_tokens=37308、output_tokens=54、reasoning_output_tokens=0；
这只是一次加载测量，没有对照实验，不能宣称性能提升百分比。

通过独立 App Server stdio 连接执行只读 `skills/list`（`forceReload=true`），
补充验证实际技能发现，而非只依赖模型从 AGENTS.md 中复述名称；没有创建任务、
修改配置或执行该技能。接口依据：[官方 App Server 文档](https://learn.chatgpt.com/docs/app-server)。

全工作树 `git diff --check` 为 exit 2：`app/services/email_service.py:522`
存在末尾新增空行。该文件在任务开始时已修改，哈希复核未变；属于原有工作树问题，
本次没有代改。上述 scoped exit 0 不代表整个工作树无问题。

### 安全扫描的准确状态

首轮命令：`codex-security scan . --path AGENTS.md --path docs/AGENT_WORKFLOW.md
--path .agents/skills/wa-render-ops --path .claude/commands/render.md --output-dir
<临时证据目录>/security --format json`。扫描 ID 为
`dedc8516-8e09-4aea-9d09-e4964e72a299`。
阶段产物的 coverage 标记 complete，列出 5 个文件，findings 为空；但 CLI 最终
exit 1：`Working-tree contents changed while the scan was running`。原因是本次
审计文档在扫描期间仍被更新。**阶段产物不等于成功保存的最终扫描结果**。

停止编辑后尝试重跑：一次推理配置参数被 CLI 以 `Invalid --codex TOML value`
拒绝，未进入扫描；去掉该参数并显式选择 Astra 后，后端 HTTP 400 提示
`The 'gpt-6-astra' model requires a newer version of Codex`，exit 1。
随后恢复默认扫描模型的尝试在启动时报告命令无法解析，exit 1。
最终只读检查确认 `C:\nvm4w\nodejs\codex-security.ps1` 与 `.cmd` 均存在且
可发现，因此不能把启动异常写成“未安装”。稳定可复现的扫描环境这一假设不成立；
按连续失败停止重试的工作约定，没有继续更改工具或安装配置。

首轮和重试证据分别在临时目录的 `security`、`security-final` 下。
本次不宣称 Codex Security 通过；5 文件独立复核、新会话与结构验证仍然有效。
扫描覆盖的是指令文件，未包含应用运行时代码的全面安全验证。

独立模拟的五个场景：Render status 返回 null；仅改按钮文字；只检查 Telegram
不改线上；明确部署到 Fly.io；已授权 Render 部署但未授权发消息。
结果符合范围要求；这些是指令行为模拟，没有调用生产服务。

修改仅涉及 Markdown 指令及流程：未运行应用 pytest、构建、浏览器或生产回归；
未改应用代码，因此不以无关全量测试充当验收。保留现有安全测试入口供后续代码工作使用。

## 5. 限制、恢复与后续

新进程提供两个直接的仓库外问题证据：

- `Exceeded skills context budget. All skill descriptions were removed and 87 additional skills were not included in the model-visible skills list.`
- 用户级 `C:\Users\Vincent\.agents\skills\ponytail\SKILL.md` 报告缺少 YAML frontmatter。

全局 `C:\Users\Vincent\.codex\AGENTS.md` 还包含旧 Sol 模型表、强制工具路由
和 30 分钟等待要求。仓库调整无法移除宿主注入的上游文字；这些文件以及用户级
技能/插件配置保持原状。本次“已优化”只适用于列出的仓库文件。

原始 AGENTS 和 Render 命令，以及改动前状态/文件哈希已备份到
`%TEMP%\whatsapp-agent-audit-20260907`。如需恢复，只还原这两个备份并按本次
文件清单处理新增指令；不要 reset/stash 用户的其他业务改动。未提交、推送或部署。

建议提交说明：`docs: streamline agent guidance and scope Render workflow`。
产品功能状态与阶段未变，未修改已存在业务改动的 FEATURE_STATUS/DEVELOPMENT_ROADMAP。
下一阶段是单独审计用户级指令和技能发现预算，之后用同一组任务比较质量、耗时和 token；
不能仅凭减少规则保证“最大性能”。

手动复验：在本仓库新开 Codex 会话，发送“只检查 Render 状态，不部署”，确认
技能可发现且流程停留在只读；重新加载整个桌面环境的验证仍独立于本次 CLI 探针。
