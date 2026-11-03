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
          - '--caps'
          - 'vision'
          - '--output-dir'
          - 'D:/data/dsh/xiumi-browser-output'
        toolCallTimeoutMs: 60000
        failOnStartupError: true
```

使用独立 Edge 配置目录保存秀米登录。每个配置目录由一个浏览器实例使用；同一图文由一个执行者编辑。首次打开该浏览器后由使用者完成必要登录，再继续操作。数据目录、浏览器目录和截图输出留在使用者本机；安装和发布清单仅包含通用技能文件。

## 模型与截图

按账号实时模型列表选择支持图片输入的模型，并通过真实截图调用确认。部分 DeepSeek 模型仅支持文字，DOM 快照可用于读文字和定位控件；照片身份、遮挡、渐变、留白及手机预览需要图像真正进入模型。将 `vision` 写进 MCP 参数只会开放相应工具，模型的视觉能力仍需单独验证。

工具通常以 `mcp__xiumi_browser__browser_*` 出现。以当前工具 schema 为准：使用快照获取新定位依据、逐块编辑、读取样式和文字、截图检查布局；每次保存后重载回读。模型收到图像诊断或只看到占位时，将视觉验收记为待完成。

## 已验证的能力边界

2026-11-03，使用官方桌面运行时 0.2.1-rc.5、Microsoft Playwright MCP 0.0.84 和账号提供的 DeepSeek-V4.1-Flash，已完成一次真实模型验收：加载本技能与本参考、向中性本地页面输入指定文字、保存并重新打开核对、获取截图，再通过 `read_image` 正确识别画面中的三个彩色图形及其位置。共 11 次工具调用，截图另行视觉复核。该记录证明对应配置下的技能、浏览器和图像输入链路可用；实际秀米草稿编辑、两页滑动及完整文章效果仍按下列步骤分别验收。

## 分层验收

1. **安装层**：核对软件版本、技能发现与正文加载、MCP 工具注册、配置重启后仍生效。
2. **中性页面**：让模型实际输入指定文字、点击保存、重载回读，并识别仅在画面中的图形；记录原始工具调用与截图结果。
3. **秀米小样**：进入当前账号，新建测试草稿，完成一段正文格式、两页不同图片的滑动、保存重载及正反滑动；使用已确认素材。
4. **真实文章**：按主技能检查全部受影响段落、图片映射、手机宽度和交互。测试草稿、真实手机触摸及正式发布各自记录状态。

安装、发现和中性页面通过，分别证明对应层的能力。完整排版效果以真实秀米草稿的回读、视觉与交互证据为准。遇到模型凭据、平台登录或工具不可用时，保存现有成果，写明具体缺口并继续可独立完成的部分。

官方参考：[技能目录](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/skill/skill-filesystem/README.md)、[MCP 配置](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/mcp/mcp-client/README.md)、[模型配置](https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/user/guide/providers.md)、[桌面安装与数据归属](https://github.com/deepseek-ai/deepseek-harness/blob/master/apps/desktop/README.md)。
