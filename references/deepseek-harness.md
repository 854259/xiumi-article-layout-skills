# DeepSeek Harness 接入与验收

本参考用于把现有技能接入 DeepSeek Harness。技能负责工作方法；Harness 提供文件读取、模型调用和浏览器工具。先核对当前安装版及工具列表，再使用对应配置。本文配置形状已对照 Harness 0.2.1-rc.5；实际模型、账号权限和秀米界面继续以当前环境为准。

## 安装与技能发现

Windows 可使用[官方桌面版](https://www.deepseek.com/en/harness/)。桌面版使用 `DSH_HOME/profiles/desktop`，命令行 Web 版使用 `DSH_HOME/profiles/web`；各自管理插件依赖和启用状态。现有数据迁移先保留可恢复版本，再核对会话、账号、技能及必要素材。

将完整技能放到 `DSH_HOME/skills/xiumi-article-layout`，或在当前 profile 的 `cordis.patch.yml` 配置额外根目录。根目录下一层应直接包含 `xiumi-article-layout/SKILL.md`：

```yaml
- id: skill-filesystem
  disabled: false
  config:
    providerName: xiumi
    includeDefaultRoots: false
    customSkillDirs:
      - 'D:/work/skills'
```

该配置额外提供全局技能来源，预设原有的技能发现仍可工作。`SKILL.md` 的 `name` 和 `description` 用于发现与路由；`agents/openai.yaml` 属于其他客户端元数据，Harness 采用自身 frontmatter 调用策略。当前技能允许模型和用户调用，支持按自然语言选择；实际是否加载以技能调用记录及正文回读为证。

## Windows 浏览器工具

使用 Harness 自带的 `@deepseek-ai/dsh-mcp-client` 连接 [Microsoft Playwright MCP](https://github.com/microsoft/playwright-mcp)。Windows 原生桌面 CUA 插件的支持范围另行核对；秀米网页可先通过浏览器 MCP 操作。

在桌面完全退出后，使用桌面安装目录自带的 `resources/runtime/cli/bin/dsh.cmd` 为 desktop profile 安装 `@playwright/mcp`。它是普通依赖，安装完成后继续添加 MCP 配置；插件目录中的包存在与浏览器工具已注册分别验证。固定经过核验的版本并保留 lockfile。以下示例路径按使用者机器替换：

```yaml
- insert:
    - id: mcp-xiumi-browser
      name: '@deepseek-ai/dsh-mcp-client'
      config:
        serverName: xiumi_browser
        transport: stdio
        command: 'D:/apps/DeepSeek Harness/resources/runtime/primary-runtime/dependencies/node/bin/node.exe'
        args:
          - 'D:/data/dsh/profiles/desktop/node_modules/@playwright/mcp/cli.js'
          - '--browser'
          - 'msedge'
          - '--user-data-dir'
          - 'D:/data/dsh/xiumi-browser-profile'
          - '--timeout-action'
          - '15000'
          - '--caps'
          - 'vision'
          - '--output-dir'
          - 'D:/data/dsh/xiumi-browser-output'
        toolCallTimeoutMs: 90000
        failOnStartupError: false
```

使用独立 Edge 配置目录保存秀米登录。每个配置目录由一个浏览器实例使用；同一图文由一个执行者编辑。首次打开该浏览器后由使用者完成必要登录，再继续操作。数据目录、浏览器目录和截图输出留在使用者本机；安装和发布清单仅包含通用技能文件。

### 连接恢复与等待

Harness 0.2.1-rc.5 的 MCP 客户端默认开启连接恢复：初始延迟 500ms、指数退避上限 30s、最多 10 次，连接稳定 30s 后重置计数。`failOnStartupError: false` 允许首次暂态连接失败后继续由该机制尝试；设为 true 会使首次失败退出并销毁该连接实例。优先复用已有机制，核对实际错误及恢复状态。实现依据：[连接监督器](https://github.com/deepseek-ai/deepseek-harness/blob/dsh-v0.2.1-rc.5/packages/mcp/mcp-client/src/connection.ts)、[插件启动行为](https://github.com/deepseek-ai/deepseek-harness/blob/dsh-v0.2.1-rc.5/packages/mcp/mcp-client/src/index.ts)。

自动恢复重新建立连接并发现工具，不自动重放失败的网页操作。上传、保存、删除等结果不明确时，先回读当前稿件，再决定下一步。达到重连上限、登录失效、目录权限拒绝或工具安全停止时，分别保留实际状态并处理对应原因。

当前 Playwright MCP 默认动作等待为 5s，已遇到一次截图等待字体时超时，同一连接稍后截图成功；这不是传输断线证据。示例将动作等待设为 15s，宿主调用等待设为 90s，覆盖默认 60s 导航等待并留出返回余量。该设置提高等待上限，不保证所有页面及时响应；选择器多匹配、文件路径限制和连接错误分别诊断。

## 上传与截图的文件目录

先核对 MCP 实际允许的文件根目录。当前 0.0.84 组合的文件守卫以 `outputDir` 与浏览器服务进程的 `cwd` 为边界，路径经过真实路径解析；Harness 会话工作区可能在这两个目录之外。出现 `outside allowed roots` 时，记录工具返回的允许目录。

把本次已获准上传的素材复制到允许目录，核对文件哈希，再用该副本上传。已有相同副本时直接复用。截图先写入允许的输出目录，完成验证后按项目规则归档；保留当前有效素材，清理本次无用中间物。复制是否需要宿主额外权限，以当前运行环境的具体反馈为准，沿用已经明确的用户授权；拒绝或安全停止分别记录。

网页操作继续使用普通浏览器交互工具；页面脚本限于读取当前 DOM、选区、几何和计算样式。宿主文件整理使用宿主文件工具，不通过 `browser_run_code_unsafe` 探测 Node 环境或读写文件。这里的只读页面规则属于操作约定；当前通用 MCP 接入配置未提供逐工具过滤，不能把该约定表述为已实施的技术隔离。

### 已配置图片整理插件时

若当前工具列表包含 `prepare_xiumi_images`，优先使用它完成选定素材暂存和截图归档：

```json
{"operation":"prepare_upload","files":["images/photo-A.png","images/photo-B.png"]}
```

返回的 `destination` 是传给 `browser_file_upload` 的路径，`sha256` 用于核对字节一致性。工具只接受原始会话工作区内、已获准用于当前任务的图片；相同内容复用已有副本。

```json
{"operation":"archive_screenshots","files":["D:/data/dsh/xiumi-browser-output/preview-A.png"],"destinationDirectory":"evidence"}
```

归档来源限于配置的浏览器输出目录和 profile 目录，目标是原始会话工作区内的相对目录；当前目录用 `"."`。同名不同内容会明确拒绝覆盖，改用具有明确含义的新成果名，核对后按项目规则处理旧版本。插件接受 PNG/JPEG/WebP/GIF，每批 1–16 张、单张不超过 20 MiB、总量不超过 64 MiB，并检查真实路径和文件签名；只读会话拒绝复制。

这是需单独安装的本地 Harness 插件能力，普通技能文件本身不注册工具。通过官方 `dsh plugin --profile desktop add <本地插件目录>` 安装，退出桌面后为 `xiumi-files` 配置 `outputDir`、`profileDir` 并启用，再重启验证；本地链接目录属于仍在使用的依赖。当前插件兼容声明锁定 Harness 0.2.1-rc.5；以后升级宿主时先复核 API 与测试，再更新声明。已验证的插件使用宿主工具守卫阻止 `mcp__xiumi_browser__browser_run_code_unsafe`，没有关闭浏览器路径限制或改变终端访问模式。该守卫仅针对指定工具；其他页面脚本的只读要求仍须遵守，不能描述为整个环境的安全沙箱。

## 模型与截图

按账号实时模型列表选择支持图片输入的模型，并通过真实截图调用确认。部分 DeepSeek 模型仅支持文字，DOM 快照可用于读文字和定位控件；照片身份、遮挡、渐变、留白及手机预览需要图像真正进入模型。将 `vision` 写进 MCP 参数只会开放相应工具，模型的视觉能力仍需单独验证。

工具通常以 `mcp__xiumi_browser__browser_*` 出现。以当前工具 schema 为准：使用快照获取新定位依据、逐块编辑、读取样式和文字、截图检查布局；每次保存后重载回读。模型收到图像诊断或只看到占位时，将视觉验收记为待完成。

## 已验证的能力边界

2026-11-03，使用官方桌面运行时 0.2.1-rc.5、Microsoft Playwright MCP 0.0.84 和账号提供的 DeepSeek-V4.1-Flash，已完成真实模型验收：

- 中性页面：11 次工具调用，加载本技能与参考、输入指定文字、保存并重新打开核对、截图，再通过 `read_image` 正确识别三个彩色图形及其位置。
- 秀米测试草稿：新建一段正文与两页图片滑动；保存重载后实际回读 15px 字号、27px 行高、1px 字间距、约 32px 首行缩进及两侧 20px。手机宽度预览实际横向滚动 A→B→A，三张截图另行复核，正确返回 A 图；侧边模板装饰经界面清理后重做保存、回读与滑动检查。该交互来自桌面横向滚轮，真实手机触摸另行验证。
- 本地图片插件：正式桌面重启后，由模型实际调用，完成两张图片暂存及三张截图归档、回读图片；一次无副作用常量探针被指定工具守卫拒绝。路径越界、链接逃逸、类型与大小、重名冲突（含 Windows 大小写冲突）、只读和调用前取消等本地测试通过；测试输出为 9 tests（1 个父测试、8 个子测试）。
- 连接恢复：在没有浏览器窗口和进行中调用时，受控结束当前 MCP 子进程；宿主保持运行并自动启动新进程。随后真实模型成功导航回已保存测试稿并回读原文和格式，登录仍有效。该实测覆盖空闲连接中断后的恢复；初始化失败重试依据当前源码与配置，未另行注入初始连接故障，也未模拟编辑中断。

这些结果证明该组合能执行对应流程；完整文章的逐图身份、模板清理和视觉质量仍须按当次素材验收，不能由一次小样推定全部文章已合格。测试素材、草稿链接、截图及原始日志留在本机项目，不放进通用技能包。

## 分层验收

1. **安装层**：核对软件版本、技能发现与正文加载、MCP 工具注册、配置重启后仍生效。
2. **中性页面**：让模型实际输入指定文字、点击保存、重载回读，并识别仅在画面中的图形；记录原始工具调用与截图结果。
3. **秀米小样**：进入当前账号，新建测试草稿，完成一段正文格式、两页不同图片的滑动、保存重载及正反滑动；使用已确认素材。
4. **真实文章**：按主技能检查全部受影响段落、图片映射、手机宽度和交互。测试草稿、真实手机触摸及正式发布各自记录状态。

安装、发现和中性页面通过，分别证明对应层的能力。完整排版效果以真实秀米草稿的回读、视觉与交互证据为准。遇到模型凭据、平台登录或工具不可用时，保存现有成果，写明具体缺口并继续可独立完成的部分。

官方参考：[技能目录](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/skill/skill-filesystem/README.md)、[MCP 配置](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/mcp/mcp-client/README.md)、[模型配置](https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/user/guide/providers.md)、[桌面安装与数据归属](https://github.com/deepseek-ai/deepseek-harness/blob/master/apps/desktop/README.md)。
